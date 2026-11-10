import unittest
from datetime import date, datetime

from pomodoro import planning, settings as settings_mod
from pomodoro.controller import Controller

from .test_controller import ControllerTest


class PlanningControllerTest(ControllerTest):
    def make(self, **settings):
        self.day = getattr(self, "day", date(2026, 11, 9))
        base = {"work_min": 25, "end_of_day_reminder": "18:00"}
        base.update(settings)
        self.controller = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize(base), scheduler=self.scheduler,
            notify=self.notes.append, play_sound=self.sounds.append,
            now=self.clock, today=lambda: self.day,
        )
        self.controller.subscribe(self.events.append)
        return self.controller

    def next_day(self, hour=8):
        self.day = date(self.day.year, self.day.month, self.day.day + 1)
        self.clock.current = datetime(self.day.year, self.day.month, self.day.day, hour, 0, 0)


class DayTurnTest(PlanningControllerTest):
    def test_new_day_carries_pending_and_spawns_recurring(self):
        late = self.controller.add_task("Ficou", estimate_min=30)
        daily = self.controller.add_task("Diária", estimate_min=10)
        self.controller.repo.update_task(daily["id"], repeat_rule="daily")
        self.controller.set_task_done(daily["id"], True)
        self.events.clear()
        self.controller.poll_clock()
        self.assertNotIn("day", self.events)                                  # ainda é o mesmo dia
        self.next_day()
        self.controller.poll_clock()
        self.assertIn("day", self.events)
        self.assertEqual(self.controller.repo.get_task(late["id"])["scheduled_for"], "2026-11-10")
        self.assertEqual(self.controller.repo.get_task(late["id"])["postponed_count"], 1)
        titles = [t.title for g in self.controller.today_view().groups for t in g.tasks]
        self.assertEqual(sorted(titles), ["Diária", "Ficou"])

    def test_carry_over_can_be_turned_off(self):
        self.controller.shutdown()
        self.make(carry_over_unfinished=False)
        late = self.controller.add_task("Ficou")
        self.next_day()
        self.controller.poll_clock()
        self.assertEqual(self.controller.repo.get_task(late["id"])["postponed_count"], 0)

    def test_startup_applies_the_day_turn(self):
        self.controller.add_task("Ficou")
        self.controller.shutdown()
        self.next_day()
        self.make()
        (task,) = self.controller.repo.list_tasks()
        self.assertEqual((task["scheduled_for"], task["postponed_count"]), ("2026-11-10", 1))

    def test_completing_a_recurring_task_schedules_the_next(self):
        task = self.controller.add_task("Diária", estimate_min=10)
        self.controller.repo.update_task(task["id"], repeat_rule="weekdays")
        self.controller.focus(task["id"])
        self.assertEqual(self.controller.complete_current(), "task")
        scheduled = [t["scheduled_for"] for t in self.controller.repo.list_tasks(statuses=("todo",))]
        self.assertEqual(scheduled, ["2026-11-10"])


class ReminderTest(PlanningControllerTest):
    def test_reminder_fires_once_when_the_time_arrives(self):
        self.controller.poll_clock()
        self.assertEqual(self.notes, [])                                       # 14:00
        self.clock.current = datetime(2026, 11, 9, 18, 5)
        self.controller.poll_clock()
        self.controller.poll_clock()
        self.assertEqual(len(self.notes), 1)
        self.assertIn("planejar amanhã", self.notes[0])
        self.assertEqual(self.events.count("reminder"), 1)

    def test_no_reminder_when_the_app_opens_after_the_time(self):
        self.controller.shutdown()
        self.clock.current = datetime(2026, 11, 9, 20, 0)
        self.make()
        self.controller.poll_clock()
        self.assertEqual(self.notes, [])

    def test_no_reminder_after_the_plan_was_confirmed_or_when_off(self):
        self.controller.confirm_plan({})
        self.clock.current = datetime(2026, 11, 9, 18, 5)
        self.controller.poll_clock()
        self.assertEqual(self.notes, [])
        self.controller.shutdown()
        self.make(end_of_day_reminder="")
        self.clock.current = datetime(2026, 11, 9, 23, 0)
        self.controller.poll_clock()
        self.assertEqual(self.notes, [])

    def test_reminder_again_next_day(self):
        self.clock.current = datetime(2026, 11, 9, 18, 5)
        self.controller.poll_clock()
        self.next_day(hour=18)
        self.controller.poll_clock()
        self.assertEqual(len(self.notes), 2)


class ReviewFlowTest(PlanningControllerTest):
    def test_review_destinations_and_confirm(self):
        done = self.controller.add_task("Feita", estimate_min=20)
        self.controller.set_task_done(done["id"], True)
        keep = self.controller.add_task("Levar", estimate_min=30)
        drop = self.controller.add_task("Descartar", estimate_min=10)
        wait = self.controller.add_task("Deixar", estimate_min=10)
        review = self.controller.day_review()
        self.assertEqual((review.done_count, review.total_count, len(review.leftovers)), (1, 4, 3))
        destinations = self.controller.default_destinations(review.leftovers)
        self.assertEqual(set(destinations.values()), {"2026-11-10"})
        destinations[drop["id"]] = planning.DISCARD
        destinations[wait["id"]] = "2026-11-14"
        result = self.controller.confirm_plan(destinations)
        self.assertEqual(result, {"moved": 2, "discarded": 1, "skipped": 0})
        repo = self.controller.repo
        self.assertEqual(repo.get_task(keep["id"])["scheduled_for"], "2026-11-10")
        self.assertEqual(repo.get_task(wait["id"])["scheduled_for"], "2026-11-14")
        self.assertEqual(repo.get_task(drop["id"])["status"], "discarded")
        self.assertIsNotNone(repo.get_day_review("2026-11-09")["confirmed_at"])
        self.assertIsNotNone(repo.get_day_review("2026-11-10")["confirmed_at"])

    def test_invalid_destination_changes_nothing(self):
        task = self.controller.add_task("A")
        with self.assertRaises(ValueError):
            self.controller.confirm_plan({task["id"]: "2026-11-08"})
        self.assertEqual(self.controller.repo.get_task(task["id"])["scheduled_for"], "2026-11-09")
        self.assertIsNone(self.controller.repo.get_day_review("2026-11-09"))

    def test_mood_is_saved_for_today(self):
        self.controller.set_day_mood("good")
        self.assertEqual(self.controller.day_review().mood, "good")

    def test_default_destination_is_empty_without_carry_over(self):
        self.controller.shutdown()
        self.make(carry_over_unfinished=False)
        task = self.controller.add_task("A")
        destinations = self.controller.default_destinations(self.controller.day_review().leftovers)
        self.assertEqual(destinations, {task["id"]: None})

    def test_break_suggestion_follows_ai_switch(self):
        task = self.controller.add_task("Grande", estimate_min=80)
        self.controller.repo.postpone_task(task["id"], "2026-11-09")
        leftovers = self.controller.day_review().leftovers
        self.assertEqual(self.controller.break_suggestion(leftovers)[0], task["id"])
        self.controller.apply_settings({"ai_enabled": False})
        self.assertIsNone(self.controller.break_suggestion(leftovers))


class TomorrowPlanTest(PlanningControllerTest):
    def test_plan_free_time_and_quick_add(self):
        group = self.controller.repo.default_group_id()
        self.controller.add_to_tomorrow("Responder e-mails", 20)
        self.controller.add_to_tomorrow("Caminhada", 30, group)
        plan = self.controller.tomorrow_plan()
        self.assertEqual(plan["day"], date(2026, 11, 10))
        self.assertEqual([i.title for i in plan["items"]], ["Responder e-mails", "Caminhada"])
        self.assertEqual((plan["free_min"], plan["capacity"].planned_min), (360, 50))
        self.controller.set_tomorrow_free_minutes(120)
        self.assertEqual(self.controller.tomorrow_plan()["free_min"], 120)
        self.assertEqual(self.controller.today_view().task_count, 0)           # não aparece em Hoje

    def test_reorder_plan_persists(self):
        a = self.controller.add_to_tomorrow("A", 10)
        b = self.controller.add_to_tomorrow("B", 10)
        self.controller.reorder_plan([b["id"], a["id"]])
        self.assertEqual([i.title for i in self.controller.tomorrow_plan()["items"]], ["B", "A"])

    def test_ai_off_keeps_estimates(self):
        self.controller.apply_settings({"ai_enabled": False})
        self.controller.add_to_tomorrow("A", 10)
        (item,) = self.controller.tomorrow_plan()["items"]
        self.assertEqual((item.estimate_min, item.ai_min), (10, 10))


if __name__ == "__main__":
    unittest.main()
