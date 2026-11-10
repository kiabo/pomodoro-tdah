import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pomodoro import db, planning
from pomodoro.ai.estimator import Estimator
from pomodoro.repository import Repository

from .test_repository import FakeClock

TODAY = date(2026, 11, 9)       # segunda
DAY = "2026-11-09"
TOMORROW = "2026-11-10"


class PlanningTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 9, 18, 10, 0))
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.work = self.repo.create_group("Trabalho", color="#5B5BD6")
        self.home = self.repo.create_group("Casa", color="#3DAA7D")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def task(self, group, title, day=DAY, **kwargs):
        return self.repo.create_task(group["id"], title, scheduled_for=day, **kwargs)

    def finish(self, task, minutes, when=datetime(2026, 11, 9, 10)):
        session = self.repo.start_session("work", task_id=task["id"], started_at=when)
        self.repo.end_session(session, minutes * 60, completed_phase=True, ended_at=when)
        self.repo.set_task_status(task["id"], "done")


class SpawnRecurringTest(PlanningTest):
    def test_done_recurring_task_creates_the_next_one_once(self):
        task = self.task(self.work, "Responder e-mails", estimate_min=20, repeat_rule="weekdays")
        self.repo.add_subtask(task["id"], "Triagem", 5)
        self.repo.set_subtask_done(self.repo.list_subtasks(task["id"])[0]["id"], True)
        self.repo.set_task_status(task["id"], "done")
        created = planning.spawn_recurring(self.repo, TODAY)
        self.assertEqual(len(created), 1)
        copy = created[0]
        self.assertEqual((copy["title"], copy["scheduled_for"], copy["repeat_rule"], copy["status"]),
                         ("Responder e-mails", TOMORROW, "weekdays", "todo"))
        self.assertFalse(self.repo.list_subtasks(copy["id"])[0]["done"])
        self.assertIsNone(self.repo.get_task(task["id"])["repeat_rule"])
        self.assertEqual(planning.spawn_recurring(self.repo, TODAY), [])       # idempotente

    def test_pending_recurring_task_spawns_nothing(self):
        self.task(self.work, "Tomar remédio", repeat_rule="daily")
        self.assertEqual(planning.spawn_recurring(self.repo, TODAY), [])

    def test_discarded_counts_and_overdue_does_not_pile_up(self):
        old = self.task(self.work, "Regar plantas", day="2026-11-03", repeat_rule="daily")
        self.repo.set_task_status(old["id"], "discarded")
        (copy,) = planning.spawn_recurring(self.repo, TODAY)
        self.assertEqual(copy["scheduled_for"], TOMORROW)                        # nunca no passado

    def test_done_ahead_of_time_goes_after_its_own_date(self):
        task = self.task(self.work, "Relatório", day="2026-11-12", repeat_rule="weekly:3")
        self.repo.set_task_status(task["id"], "done")
        (copy,) = planning.spawn_recurring(self.repo, TODAY)
        self.assertEqual(copy["scheduled_for"], "2026-11-19")

    def test_group_requiring_estimate_does_not_break_the_day(self):
        task = self.task(self.work, "Sem previsão", repeat_rule="daily")
        self.repo.set_task_status(task["id"], "done")
        self.repo.update_group(self.work["id"], require_estimate=True)
        self.assertEqual(planning.spawn_recurring(self.repo, TODAY), [])


class RollOverTest(PlanningTest):
    def test_overdue_pending_moves_to_today_and_counts(self):
        late = self.task(self.work, "Atrasada", day="2026-11-05")
        undated = self.task(self.work, "Sem data", day=None)
        future = self.task(self.work, "Futura", day="2026-11-12")
        done = self.task(self.work, "Feita", day="2026-11-05")
        self.repo.set_task_status(done["id"], "done")
        self.assertEqual(planning.roll_over(self.repo, TODAY), 1)
        moved = self.repo.get_task(late["id"])
        self.assertEqual((moved["scheduled_for"], moved["postponed_count"]), (DAY, 1))
        for other in (undated, future, done):
            self.assertEqual(self.repo.get_task(other["id"])["postponed_count"], 0)
        self.assertEqual(planning.roll_over(self.repo, TODAY), 0)               # idempotente

    def test_carry_off_leaves_tasks_alone(self):
        late = self.task(self.work, "Atrasada", day="2026-11-05")
        self.assertEqual(planning.roll_over(self.repo, TODAY, carry=False), 0)
        self.assertEqual(self.repo.get_task(late["id"])["scheduled_for"], "2026-11-05")

    def test_start_of_day_does_both(self):
        self.task(self.work, "Atrasada", day="2026-11-05")
        recurring = self.task(self.work, "Diária", day="2026-11-08", repeat_rule="daily")
        self.repo.set_task_status(recurring["id"], "done")
        self.assertEqual(planning.start_of_day(self.repo, TODAY), (1, 1))


class ReviewTest(PlanningTest):
    def test_summary_and_leftovers(self):
        done = self.task(self.work, "Responder", estimate_min=20)
        self.finish(done, 18)
        left = self.task(self.work, "Preparar apresentação", estimate_min=80)
        self.repo.postpone_task(left["id"], DAY)
        self.repo.add_subtask(left["id"], "Slides", 40)
        other = self.task(self.home, "Lavar roupa", estimate_min=30)
        gone = self.task(self.home, "Cancelada", estimate_min=10)
        self.repo.set_task_status(gone["id"], "discarded")
        self.repo.save_day_review(DAY, mood="ok")
        review = planning.review_day(self.repo, DAY)
        self.assertEqual((review.done_count, review.total_count), (1, 3))
        self.assertEqual(review.planned_min, 20 + 80 + 30)
        self.assertEqual(review.real_seconds, 18 * 60)
        self.assertEqual(review.mood, "ok")
        self.assertEqual([i.title for i in review.leftovers], ["Preparar apresentação", "Lavar roupa"])
        first = review.leftovers[0]
        self.assertEqual((first.group_name, first.subtask_title, first.postponed_count, first.has_subtasks),
                         ("Trabalho", "Slides", 1, True))
        self.assertEqual(review.leftovers[1].task_id, other["id"])

    def test_estimate_falls_back_to_subtasks(self):
        task = self.task(self.work, "Sem previsão própria")
        self.repo.add_subtask(task["id"], "a", 15)
        self.repo.add_subtask(task["id"], "b", 10)
        self.assertEqual(planning.review_day(self.repo, DAY).leftovers[0].estimate_min, 25)

    def test_default_destinations_follow_carry_setting(self):
        task = self.task(self.work, "X")
        leftovers = planning.review_day(self.repo, DAY).leftovers
        self.assertEqual(planning.default_destinations(leftovers, DAY), {task["id"]: TOMORROW})
        self.assertEqual(planning.default_destinations(leftovers, DAY, carry=False), {task["id"]: None})

    def test_break_suggestion_picks_most_postponed_without_steps(self):
        a = self.task(self.work, "A", estimate_min=30)
        b = self.task(self.work, "B", estimate_min=60)
        c = self.task(self.work, "C", estimate_min=90)
        self.repo.postpone_task(a["id"], DAY)
        self.repo.postpone_task(b["id"], DAY)
        self.repo.postpone_task(b["id"], DAY)
        self.repo.postpone_task(c["id"], DAY)
        self.repo.add_subtask(c["id"], "passo")
        task_id, text = planning.break_suggestion(planning.review_day(self.repo, DAY).leftovers)
        self.assertEqual(task_id, b["id"])
        self.assertIn("“B” já foi adiada 2 vezes", text)
        self.assertIn("passos de 20 min", text)

    def test_break_suggestion_needs_a_postponed_task(self):
        self.task(self.work, "Nova")
        self.assertIsNone(planning.break_suggestion(planning.review_day(self.repo, DAY).leftovers))

    def test_singular_wording(self):
        a = self.task(self.work, "A")
        self.repo.postpone_task(a["id"], DAY)
        self.assertIn("adiada 1 vez.", planning.break_suggestion(planning.review_day(self.repo, DAY).leftovers)[1])


class ApplyDestinationsTest(PlanningTest):
    def test_moves_discards_and_skips(self):
        a, b, c = (self.task(self.work, name) for name in "abc")
        result = planning.apply_destinations(
            self.repo, TODAY, {a["id"]: TOMORROW, b["id"]: planning.DISCARD, c["id"]: None})
        self.assertEqual(result, {"moved": 1, "discarded": 1, "skipped": 1})
        moved = self.repo.get_task(a["id"])
        self.assertEqual((moved["scheduled_for"], moved["postponed_count"]), (TOMORROW, 1))
        self.assertEqual(self.repo.get_task(b["id"])["status"], "discarded")
        self.assertEqual(self.repo.get_task(c["id"])["scheduled_for"], DAY)

    def test_validates_everything_before_writing(self):
        a, b = self.task(self.work, "a"), self.task(self.work, "b")
        with self.assertRaises(ValueError):
            planning.apply_destinations(self.repo, TODAY, {a["id"]: TOMORROW, b["id"]: DAY})
        self.assertEqual(self.repo.get_task(a["id"])["scheduled_for"], DAY)
        with self.assertRaises(KeyError):
            planning.apply_destinations(self.repo, TODAY, {a["id"]: TOMORROW, "nope": TOMORROW})
        self.assertEqual(self.repo.get_task(a["id"])["postponed_count"], 0)

    def test_discarding_a_recurring_task_spawns_the_next(self):
        task = self.task(self.work, "Diária", repeat_rule="daily")
        planning.apply_destinations(self.repo, TODAY, {task["id"]: planning.DISCARD})
        (copy,) = planning.spawn_recurring(self.repo, TODAY)
        self.assertEqual(copy["scheduled_for"], TOMORROW)


class CapacityTest(PlanningTest):
    def history(self):
        """Quatro relatórios que levaram o dobro do previsto: a IA corrige as previsões para cima."""
        for index in range(4):
            task = self.task(self.work, f"Escrever relatório {index}", day="2026-11-02", estimate_min=30)
            self.finish(task, 60, datetime(2026, 11, 2, 10))

    def test_plan_items_and_ai_estimate(self):
        self.history()
        a = self.task(self.work, "Escrever relatório novo", day=TOMORROW, estimate_min=30)
        b = self.task(self.home, "Lavar roupa", day=TOMORROW, estimate_min=30, repeat_rule="daily")
        self.task(self.home, "Outro dia", day="2026-11-11", estimate_min=30)
        done = self.task(self.home, "Feita", day=TOMORROW, estimate_min=30)
        self.repo.set_task_status(done["id"], "done")
        items = planning.plan_items(self.repo, TOMORROW, estimator=Estimator())
        self.assertEqual([i.task_id for i in items], [a["id"], b["id"]])
        self.assertEqual((items[0].estimate_min, items[0].ai_min, items[0].recurring), (30, 60, False))
        self.assertEqual((items[1].ai_min, items[1].recurring), (30, True))      # sem histórico: igual ao previsto
        self.assertEqual(items[0].group_color, "#5B5BD6")

    def test_without_estimator_ai_equals_user(self):
        self.task(self.work, "X", day=TOMORROW, estimate_min=45)
        (item,) = planning.plan_items(self.repo, TOMORROW)
        self.assertEqual((item.estimate_min, item.ai_min), (45, 45))

    def test_capacity_numbers_match_the_design(self):
        items = [planning.PlanItem("1", "g", "a", "#000000", 245, 285, False)]
        cap = planning.capacity(items, 360)
        self.assertEqual((cap.planned_min, cap.ai_min, cap.spare_min, cap.level), (245, 285, 75, "tight"))
        self.assertAlmostEqual(cap.planned_fraction, 245 / 360)
        self.assertAlmostEqual(cap.ai_fraction, 285 / 360)

    def test_capacity_over_empty_and_no_free_time(self):
        over = planning.capacity([planning.PlanItem("1", "g", "a", "#000000", 300, 420, False)], 360)
        self.assertEqual((over.level, over.over_min, over.spare_min, over.ai_fraction), ("over", 60, 0, 1.0))
        self.assertEqual(planning.capacity([], 360).level, "empty")
        self.assertEqual(planning.capacity([planning.PlanItem("1", "g", "a", "#000000", 10, 10, False)], 0).level, "over")

    def test_free_minutes_prefers_the_day_review(self):
        self.assertEqual(planning.free_minutes_for(self.repo, TOMORROW, 360), 360)
        self.repo.save_day_review(TOMORROW, free_minutes=240)
        self.assertEqual(planning.free_minutes_for(self.repo, TOMORROW, 360), 240)

    def test_reorder_within_groups_keeps_group_slots(self):
        a1, a2, a3 = (self.task(self.work, f"A{i}", day=TOMORROW) for i in (1, 2, 3))
        b1 = self.task(self.home, "B1", day=TOMORROW)
        outside = self.task(self.work, "Fora do plano", day="2026-11-20")
        # Move A3 para antes de A1; B1 no meio não muda nada (é de outro grupo).
        planning.reorder_within_groups(self.repo, [a3["id"], b1["id"], a1["id"], a2["id"]])
        order = [t["id"] for t in self.repo.list_tasks(group_id=self.work["id"])]
        self.assertEqual(order, [a3["id"], a1["id"], a2["id"], outside["id"]])

    def test_confirm_plan_saves_review(self):
        review = planning.confirm_plan(self.repo, TOMORROW, free_minutes=300)
        self.assertEqual(review["free_minutes"], 300)
        self.assertIsNotNone(review["confirmed_at"])


if __name__ == "__main__":
    unittest.main()
