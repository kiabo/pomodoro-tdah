import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pomodoro import db, export
from pomodoro.groups import build_group_cards, week_bounds
from pomodoro.repository import Repository
from pomodoro.stats import bias, bias_note
from pomodoro.today import build_today

from .test_repository import FakeClock

TODAY = date(2026, 11, 9)          # segunda-feira


class BiasTest(unittest.TestCase):
    def test_bias(self):
        pairs = [(39 * 60, 30), (33 * 60, 30), (36 * 60, 30)]       # 130%, 110%, 120% -> 1.2
        ratio, samples = bias(pairs)
        self.assertAlmostEqual(ratio, 1.2)
        self.assertEqual(samples, 3)

    def test_not_enough_data(self):
        self.assertEqual(bias([(60, 1), (60, 1)]), (None, 2))
        self.assertEqual(bias([(0, 30), (600, None), (None, 30)]), (None, 0))
        self.assertEqual(bias([(30 * 60, 30)], min_samples=1), (1.0, 1))

    def test_notes(self):
        self.assertEqual(bias_note(None), ("Sem dados suficientes ainda para a IA", "none"))
        self.assertEqual(bias_note(1.22), ("✦ Você subestima tarefas deste grupo em ~22%", "under"))
        self.assertEqual(bias_note(0.75), ("✦ Você superestima tarefas deste grupo em ~25%", "over"))
        self.assertEqual(bias_note(1.05), ("✦ Suas previsões aqui são ótimas", "good"))
        self.assertEqual(bias_note(1.1)[1], "under")
        self.assertEqual(bias_note(0.9)[1], "over")


class GroupCardsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.work = self.repo.create_group("Trabalho", color="#5B5BD6", work_min=50, short_break_min=10)
        self.home = self.repo.create_group("Casa", color="#3DAA7D")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def cards(self, **kwargs):
        return {c.name: c for c in build_group_cards(self.repo, TODAY, **kwargs)}

    def worked(self, task, seconds):
        session = self.repo.start_session("work", task_id=task["id"])
        self.repo.end_session(session, seconds, completed_phase=True)

    def test_week_bounds(self):
        self.assertEqual(week_bounds(TODAY), ("2026-11-09", "2026-11-15"))
        self.assertEqual(week_bounds("2026-11-15"), ("2026-11-09", "2026-11-15"))
        self.assertEqual(week_bounds(date(2026, 11, 8)), ("2026-11-02", "2026-11-08"))

    def test_counts_cycle_and_today_totals(self):
        a = self.repo.create_task(self.work["id"], "A", estimate_min=60, scheduled_for="2026-11-09")
        self.repo.create_task(self.work["id"], "B", estimate_min=30, scheduled_for="2026-11-12")
        self.repo.create_task(self.work["id"], "Semana passada", scheduled_for="2026-11-03")
        self.repo.create_task(self.work["id"], "Sem data")
        gone = self.repo.create_task(self.work["id"], "Descartada", scheduled_for="2026-11-10")
        self.repo.set_task_status(gone["id"], "discarded")
        self.worked(a, 1800)
        cards = self.cards()
        work = cards["Trabalho"]
        self.assertEqual((work.today_count, work.week_count), (3, 2))     # A, Sem data e a atrasada; A e B na semana
        self.assertEqual((work.planned_min, work.real_seconds), (60, 1800))
        self.assertEqual((work.cycle_text, work.work_min, work.short_break_min), ("50/10", 50, 10))
        self.assertIsNone(cards["Casa"].cycle_text)
        self.assertEqual((cards["Casa"].today_count, cards["Casa"].week_count), (0, 0))

    def test_cycle_text_with_only_one_custom_value(self):
        self.repo.update_group(self.home["id"], work_min=40)
        self.assertEqual(self.cards()["Casa"].cycle_text, "40/·")

    def test_accuracy_and_bias_from_done_tasks(self):
        for index, real_min in enumerate((39, 33, 36)):
            task = self.repo.create_task(self.work["id"], f"T{index}", estimate_min=30, scheduled_for="2026-11-09")
            self.worked(task, real_min * 60)
            self.repo.set_task_status(task["id"], "done")
        card = self.cards()["Trabalho"]
        self.assertAlmostEqual(card.bias_ratio, 1.2)
        self.assertEqual(card.bias_samples, 3)
        self.assertAlmostEqual(card.accuracy, 0.8)
        self.assertIsNone(self.cards()["Casa"].accuracy)

    def test_estimate_falls_back_to_subtasks(self):
        task = self.repo.create_task(self.home["id"], "Com subtarefas", scheduled_for="2026-11-09")
        self.repo.add_subtask(task["id"], "A", 10)
        self.repo.add_subtask(task["id"], "B", 20)
        self.worked(task, 30 * 60)
        self.repo.set_task_status(task["id"], "done")
        self.assertAlmostEqual(self.cards()["Casa"].accuracy, 1.0)

    def test_recurring_list_is_unique_by_title_and_sorted(self):
        self.repo.create_task(self.work["id"], "Responder e-mails", estimate_min=20, repeat_rule="weekdays")
        self.clock.advance(days=1)
        self.repo.create_task(self.work["id"], "Responder e-mails", estimate_min=25, repeat_rule="weekdays")
        self.repo.create_task(self.work["id"], "Escrever relatório", estimate_min=90, repeat_rule="monthly:9")
        off = self.repo.create_task(self.work["id"], "Cancelada", repeat_rule="daily")
        self.repo.set_task_status(off["id"], "discarded")
        self.repo.create_task(self.work["id"], "Avulsa")
        recurring = self.cards()["Trabalho"].recurring
        self.assertEqual([(r["title"], r["rule"], r["estimate_min"]) for r in recurring],
                         [("Escrever relatório", "monthly:9", 90), ("Responder e-mails", "weekdays", 25)])

    def test_archived_groups_only_when_asked(self):
        self.repo.archive_group(self.home["id"])
        self.assertNotIn("Casa", self.cards())
        cards = self.cards(include_archived=True)
        self.assertTrue(cards["Casa"].archived)
        self.assertEqual(cards["Casa"].today_count, 0)

    def test_matches_the_today_view_counts(self):
        self.repo.create_task(self.work["id"], "A", scheduled_for="2026-11-09")
        view = build_today(self.repo, "2026-11-09")
        self.assertEqual(self.cards()["Trabalho"].today_count, view.group_counts[self.work["id"]])


class ExportTest(unittest.TestCase):
    def test_export_everything_without_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
            conn = db.open_database(Path(tmp), clock())
            repo = Repository(conn, now=clock)
            group = repo.create_group("Trabalho")
            task = repo.create_task(group["id"], "Relatório", estimate_min=90)
            sub = repo.add_subtask(task["id"], "Gráficos", 30)
            session = repo.start_session("work", task_id=task["id"], subtask_id=sub["id"])
            repo.end_session(session, 600)
            repo.add_distraction("ligar para o banco", task_id=task["id"])
            repo.save_day_review("2026-11-09", mood="ok")
            path = Path(tmp) / "saida.json"
            count = export.write_export(conn, path, now=clock)
            data = json.loads(path.read_text())
            self.assertEqual(data["version"], 1)
            self.assertEqual(data["exported_at"], "2026-11-09T14:00:00")
            self.assertEqual([t["title"] for t in data["tasks"]], ["Relatório"])
            self.assertEqual(data["subtasks"][0]["title"], "Gráficos")
            self.assertEqual(data["sessions"][0]["seconds"], 600)
            self.assertEqual(data["distractions"][0]["text"], "ligar para o banco")
            self.assertEqual(data["day_reviews"][0]["mood"], "ok")
            self.assertEqual(count, sum(len(data[t]) for t in export.TABLES))
            self.assertFalse(any("api" in key.lower() for key in data))
            self.assertFalse((Path(tmp) / "saida.json.tmp").exists())
            conn.close()


class OnlyTaskTest(unittest.TestCase):
    def test_only_task_filters_the_list_but_not_the_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
            conn = db.open_database(Path(tmp), clock())
            repo = Repository(conn, now=clock)
            group = repo.create_group("Trabalho")
            a = repo.create_task(group["id"], "A", estimate_min=30, scheduled_for="2026-11-09")
            repo.create_task(group["id"], "B", estimate_min=20, scheduled_for="2026-11-09")
            view = build_today(repo, "2026-11-09", only_task_id=a["id"])
            self.assertEqual([t.title for t in view.visible_tasks], ["A"])
            self.assertEqual((view.planned_min, view.task_count), (50, 2))
            conn.close()


if __name__ == "__main__":
    unittest.main()
