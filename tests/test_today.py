import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pomodoro import db
from pomodoro.repository import Repository
from pomodoro.today import build_today, next_day, next_focus

from .test_repository import FakeClock

TODAY = "2026-11-09"


class TodayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.work = self.repo.create_group("Trabalho", color="#5B5BD6")
        self.home = self.repo.create_group("Casa", color="#3DAA7D")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def task(self, group, title, **kwargs):
        kwargs.setdefault("scheduled_for", TODAY)
        return self.repo.create_task(group["id"], title, **kwargs)

    def titles(self, view):
        return [[t.title for t in g.tasks] for g in view.groups]


class MembershipTest(TodayTest):
    def test_which_tasks_show_up(self):
        self.task(self.work, "Hoje")
        self.task(self.work, "Sem data", scheduled_for=None)
        self.task(self.work, "Atrasada", scheduled_for="2026-11-05")
        self.task(self.work, "Amanhã", scheduled_for="2026-11-10")
        done_today = self.task(self.work, "Feita hoje", scheduled_for="2026-11-01")
        self.repo.set_task_status(done_today["id"], "done")            # done_at = hoje
        done_old = self.task(self.work, "Feita antes", scheduled_for="2026-11-01")
        self.repo.set_task_status(done_old["id"], "done")
        self.repo.update_task(done_old["id"], status="done")
        self.conn.execute("UPDATE tasks SET done_at = '2026-11-02T10:00:00' WHERE id = ?", (done_old["id"],))
        discarded = self.task(self.work, "Descartada")
        self.repo.set_task_status(discarded["id"], "discarded")
        view = build_today(self.repo, TODAY)
        self.assertEqual(sorted(self.titles(view)[0]),
                         sorted(["Hoje", "Sem data", "Atrasada", "Feita hoje"]))

    def test_archived_group_is_hidden_and_groups_follow_user_order(self):
        self.task(self.home, "Lavar roupa")
        self.task(self.work, "Relatório")
        legacy = self.repo.create_group("Antigo")
        self.task(legacy, "Velha")
        self.repo.archive_group(legacy["id"])
        view = build_today(self.repo, TODAY)
        self.assertEqual([g.name for g in view.groups], ["Trabalho", "Casa"])
        self.assertNotIn("Velha", [t.title for t in view.visible_tasks])

    def test_empty_groups_are_not_listed_but_counted(self):
        self.task(self.work, "Relatório")
        view = build_today(self.repo, TODAY)
        self.assertEqual([g.name for g in view.groups], ["Trabalho"])
        self.assertEqual(view.group_counts[self.home["id"]], 0)
        self.assertEqual(view.group_counts[self.work["id"]], 1)
        self.assertEqual([g["name"] for g in view.all_groups], ["Geral", "Trabalho", "Casa"])

    def test_task_order_inside_group(self):
        ids = [self.task(self.work, f"T{i}")["id"] for i in range(3)]
        self.repo.reorder_tasks(self.work["id"], [ids[2], ids[0], ids[1]])
        self.assertEqual(self.titles(build_today(self.repo, TODAY)), [["T2", "T0", "T1"]])


class NumbersTest(TodayTest):
    def test_estimate_prefers_own_then_subtask_sum(self):
        own = self.task(self.work, "Com previsão", estimate_min=90)
        self.repo.add_subtask(own["id"], "A", 20)                      # a soma (20) não vale: há previsão própria
        sub_only = self.task(self.work, "Só subtarefas")
        self.repo.add_subtask(sub_only["id"], "A", 25)
        self.repo.add_subtask(sub_only["id"], "B", 30)
        self.repo.add_subtask(sub_only["id"], "C")
        none = self.task(self.work, "Sem nada")
        view = build_today(self.repo, TODAY)
        by_title = {t.title: t for t in view.visible_tasks}
        self.assertEqual(by_title["Com previsão"].estimate_min, 90)
        self.assertEqual(by_title["Só subtarefas"].estimate_min, 55)
        self.assertIsNone(by_title["Sem nada"].estimate_min)
        self.assertEqual(view.planned_min, 145)
        self.assertEqual(none["id"], by_title["Sem nada"].id)

    def test_real_time_per_task_and_subtask_and_group_totals(self):
        t1 = self.task(self.work, "Relatório", estimate_min=90)
        sub = self.repo.add_subtask(t1["id"], "Gráficos", 30)
        t2 = self.task(self.work, "E-mails", estimate_min=20)
        for task_id, subtask_id, seconds in ((t1["id"], sub["id"], 1800), (t1["id"], None, 600), (t2["id"], None, 900)):
            sid = self.repo.start_session("work", task_id=task_id, subtask_id=subtask_id)
            self.repo.end_session(sid, seconds)
        view = build_today(self.repo, TODAY)
        group = view.groups[0]
        by_title = {t.title: t for t in group.tasks}
        self.assertEqual(by_title["Relatório"].real_seconds, 2400)
        self.assertEqual(by_title["Relatório"].subtasks[0].real_seconds, 1800)
        self.assertEqual(by_title["E-mails"].real_seconds, 900)
        self.assertEqual((group.planned_min, group.real_seconds, view.real_seconds), (110, 3300, 3300))
        self.assertEqual(view.real_by_task, {t1["id"]: 2400, t2["id"]: 900})

    def test_done_counts_and_accuracy(self):
        a = self.task(self.work, "A", estimate_min=30)
        b = self.task(self.work, "B", estimate_min=30)
        self.task(self.work, "C", estimate_min=30)
        for task, seconds in ((a, 30 * 60), (b, 15 * 60)):
            sid = self.repo.start_session("work", task_id=task["id"])
            self.repo.end_session(sid, seconds)
            self.repo.set_task_status(task["id"], "done")
        view = build_today(self.repo, TODAY)
        self.assertEqual((view.task_count, view.done_count), (3, 2))
        self.assertAlmostEqual(view.accuracy, 0.75)
        self.assertIsNone(build_today(self.repo, "2026-11-20").accuracy)

    def test_subtask_flags(self):
        task = self.task(self.work, "Relatório")
        s1 = self.repo.add_subtask(task["id"], "Um")
        self.repo.add_subtask(task["id"], "Dois")
        self.repo.set_subtask_done(s1["id"])
        view = build_today(self.repo, TODAY).visible_tasks[0]
        self.assertEqual((view.subtasks_done, len(view.subtasks)), (1, 2))
        self.assertEqual([s.done for s in view.subtasks], [True, False])


class FiltersTest(TodayTest):
    def setUp(self):
        super().setUp()
        report = self.task(self.work, "Escrever relatório")
        self.repo.add_subtask(report["id"], "Montar gráficos")
        self.task(self.work, "Responder e-mails")
        self.task(self.home, "Lavar roupa")

    def test_search_matches_title_and_subtask_case_insensitive(self):
        self.assertEqual(self.titles(build_today(self.repo, TODAY, query="RELATÓRIO")), [["Escrever relatório"]])
        self.assertEqual(self.titles(build_today(self.repo, TODAY, query="gráficos")), [["Escrever relatório"]])
        self.assertEqual(build_today(self.repo, TODAY, query="zzz").groups, [])

    def test_group_filter_and_totals_ignore_filters(self):
        view = build_today(self.repo, TODAY, group_id=self.home["id"])
        self.assertEqual(self.titles(view), [["Lavar roupa"]])
        self.assertEqual(view.task_count, 3)                           # o dia inteiro, sem filtro
        searched = build_today(self.repo, TODAY, query="zzz")
        self.assertEqual(searched.task_count, 3)


class NextFocusTest(TodayTest):
    def test_next_pending_subtask_then_next_task(self):
        t1 = self.task(self.work, "Relatório")
        s1 = self.repo.add_subtask(t1["id"], "Números")
        s2 = self.repo.add_subtask(t1["id"], "Gráficos")
        s3 = self.repo.add_subtask(t1["id"], "Revisão")
        t2 = self.task(self.work, "E-mails")
        self.repo.set_subtask_done(s1["id"])
        view = build_today(self.repo, TODAY)
        self.assertEqual(next_focus(view, t1["id"], s2["id"]), "Revisão")
        self.assertEqual(next_focus(view, t1["id"], s3["id"]), "Gráficos")   # nada depois: volta ao pendente
        self.repo.set_subtask_done(s2["id"])
        self.repo.set_subtask_done(s3["id"])
        view = build_today(self.repo, TODAY)
        self.assertEqual(next_focus(view, t1["id"], None), "E-mails")
        self.assertEqual(t2["title"], "E-mails")

    def test_without_active_task(self):
        self.task(self.work, "Primeira")
        self.task(self.work, "Segunda")
        view = build_today(self.repo, TODAY)
        self.assertEqual(next_focus(view, None, None), "Primeira")

    def test_nothing_left(self):
        t = self.task(self.work, "Única")
        self.repo.set_task_status(t["id"], "done")
        self.assertIsNone(next_focus(build_today(self.repo, TODAY), None, None))


class MiscTest(unittest.TestCase):
    def test_next_day(self):
        self.assertEqual(next_day("2026-11-30"), "2026-12-01")
        self.assertEqual(next_day(date(2026, 12, 31)), "2027-01-01")


if __name__ == "__main__":
    unittest.main()
