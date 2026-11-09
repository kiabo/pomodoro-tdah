import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from pomodoro import db
from pomodoro.repository import Repository


class FakeClock:
    def __init__(self, start=datetime(2026, 11, 9, 14, 0, 0)):
        self.current = start

    def __call__(self):
        return self.current

    def advance(self, **kwargs):
        self.current += timedelta(**kwargs)


class RepoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.group = self.repo.create_group("Trabalho", color="#5B5BD6")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()


class GroupTest(RepoTest):
    def test_create_list_update(self):
        casa = self.repo.create_group("Casa", color="#3DAA7D", work_min=50, short_break_min=10)
        names = [g["name"] for g in self.repo.list_groups()]
        self.assertEqual(names, ["Geral", "Trabalho", "Casa"])
        self.assertEqual(casa["work_min"], 50)
        updated = self.repo.update_group(casa["id"], name="  Casa nova ", require_estimate=True)
        self.assertEqual(updated["name"], "Casa nova")
        self.assertEqual(updated["require_estimate"], 1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.repo.create_group("   ")
        with self.assertRaises(ValueError):
            self.repo.update_group(self.group["id"], cor="#000")
        with self.assertRaises(ValueError):
            self.repo.create_group("X", work_min=-5)
        with self.assertRaises(KeyError):
            self.repo.update_group("nao-existe", name="X")

    def test_archive_hides_group(self):
        self.repo.archive_group(self.group["id"])
        self.assertNotIn(self.group["id"], [g["id"] for g in self.repo.list_groups()])
        self.assertIn(self.group["id"], [g["id"] for g in self.repo.list_groups(include_archived=True)])

    def test_delete_cascades_tasks(self):
        task = self.repo.create_task(self.group["id"], "Relatório")
        self.repo.add_subtask(task["id"], "Gráficos")
        self.repo.delete_group(self.group["id"])
        self.assertIsNone(self.repo.get_task(task["id"]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subtasks").fetchone()[0], 0)

    def test_deleting_default_group_recreates_one(self):
        default_id = self.repo.default_group_id()
        self.repo.delete_group(default_id)
        new_default = self.repo.default_group_id()
        self.assertNotEqual(new_default, default_id)
        self.assertIsNotNone(self.repo.get_group(new_default))

    def test_reorder(self):
        ids = [g["id"] for g in self.repo.list_groups()]
        self.repo.reorder_groups(list(reversed(ids)))
        self.assertEqual([g["id"] for g in self.repo.list_groups()], list(reversed(ids)))
        with self.assertRaises(ValueError):
            self.repo.reorder_groups(ids[:1])
        with self.assertRaises(ValueError):
            self.repo.reorder_groups(ids + ids[:1])


class TaskTest(RepoTest):
    def test_create_with_fields(self):
        task = self.repo.create_task(
            self.group["id"], " Escrever relatório ", estimate_min=90,
            scheduled_for=date(2026, 11, 9), energy="high", notes="modelo do mês passado",
        )
        self.assertEqual(task["title"], "Escrever relatório")
        self.assertEqual(task["scheduled_for"], "2026-11-09")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["estimate_min"], 90)
        self.assertEqual(task["postponed_count"], 0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.repo.create_task(self.group["id"], "")
        with self.assertRaises(ValueError):
            self.repo.create_task(self.group["id"], "X", energy="altissima")
        with self.assertRaises(ValueError):
            self.repo.create_task(self.group["id"], "X", estimate_min=1.5)
        with self.assertRaises(KeyError):
            self.repo.create_task("nao-existe", "X")
        task = self.repo.create_task(self.group["id"], "X")
        with self.assertRaises(ValueError):
            self.repo.update_task(task["id"], difficulty="impossivel")
        with self.assertRaises(ValueError):
            self.repo.update_task(task["id"], created_at="ontem")

    def test_group_requiring_estimate(self):
        self.repo.update_group(self.group["id"], require_estimate=True)
        with self.assertRaises(ValueError):
            self.repo.create_task(self.group["id"], "Sem previsão")
        self.assertIsNotNone(self.repo.create_task(self.group["id"], "Com previsão", estimate_min=20))

    def test_status_sets_and_clears_done_at(self):
        task = self.repo.create_task(self.group["id"], "X")
        done = self.repo.set_task_status(task["id"], "done")
        self.assertEqual(done["done_at"], "2026-11-09T14:00:00")
        again = self.repo.update_task(task["id"], status="todo", title="Y")
        self.assertIsNone(again["done_at"])
        self.assertEqual(again["title"], "Y")
        with self.assertRaises(ValueError):
            self.repo.set_task_status(task["id"], "feito")

    def test_list_filters(self):
        today, tomorrow = "2026-11-09", "2026-11-10"
        a = self.repo.create_task(self.group["id"], "Hoje", scheduled_for=today)
        b = self.repo.create_task(self.group["id"], "Amanhã", scheduled_for=tomorrow)
        c = self.repo.create_task(self.group["id"], "Sem data")
        self.repo.set_task_status(a["id"], "done")
        self.assertEqual([t["id"] for t in self.repo.list_tasks(scheduled_for=today)], [a["id"]])
        self.assertEqual([t["id"] for t in self.repo.list_tasks(scheduled_for=None)], [c["id"]])
        self.assertEqual(len(self.repo.list_tasks(group_id=self.group["id"])), 3)
        pending = self.repo.list_tasks(group_id=self.group["id"], statuses=("todo",))
        self.assertEqual({t["id"] for t in pending}, {b["id"], c["id"]})

    def test_positions_and_reorder(self):
        ids = [self.repo.create_task(self.group["id"], f"T{i}")["id"] for i in range(3)]
        self.assertEqual([t["position"] for t in self.repo.list_tasks(group_id=self.group["id"])], [0, 1, 2])
        self.repo.reorder_tasks(self.group["id"], [ids[2], ids[0], ids[1]])
        self.assertEqual([t["id"] for t in self.repo.list_tasks(group_id=self.group["id"])],
                         [ids[2], ids[0], ids[1]])

    def test_move_to_other_group(self):
        casa = self.repo.create_group("Casa")
        self.repo.create_task(casa["id"], "Existente")
        task = self.repo.create_task(self.group["id"], "Mover")
        moved = self.repo.move_task(task["id"], casa["id"])
        self.assertEqual(moved["group_id"], casa["id"])
        self.assertEqual(moved["position"], 1)

    def test_postpone_counts(self):
        task = self.repo.create_task(self.group["id"], "Apresentação", scheduled_for="2026-11-09")
        self.repo.postpone_task(task["id"], "2026-11-10")
        again = self.repo.postpone_task(task["id"], date(2026, 11, 11))
        self.assertEqual(again["scheduled_for"], "2026-11-11")
        self.assertEqual(again["postponed_count"], 2)

    def test_duplicate_copies_subtasks_not_time(self):
        task = self.repo.create_task(self.group["id"], "Relatório", estimate_min=90)
        sub = self.repo.add_subtask(task["id"], "Números", 25)
        self.repo.set_subtask_done(sub["id"])
        sid = self.repo.start_session("work", subtask_id=sub["id"])
        self.repo.end_session(sid, 1500)
        copy = self.repo.duplicate_task(task["id"], scheduled_for="2026-11-10")
        self.assertNotEqual(copy["id"], task["id"])
        self.assertEqual(copy["scheduled_for"], "2026-11-10")
        subs = self.repo.list_subtasks(copy["id"])
        self.assertEqual([(s["title"], s["estimate_min"], s["done"]) for s in subs], [("Números", 25, 0)])
        self.assertEqual(self.repo.real_seconds(copy["id"]), 0)


class SubtaskTest(RepoTest):
    def setUp(self):
        super().setUp()
        self.task = self.repo.create_task(self.group["id"], "Escrever relatório mensal", estimate_min=90)

    def test_add_list_estimate_sum(self):
        self.assertIsNone(self.repo.subtasks_estimate_sum(self.task["id"]))
        self.repo.add_subtask(self.task["id"], "Levantar números", 25)
        self.repo.add_subtask(self.task["id"], "Montar gráficos", 30)
        self.repo.add_subtask(self.task["id"], "Revisar texto")
        subs = self.repo.list_subtasks(self.task["id"])
        self.assertEqual([s["position"] for s in subs], [0, 1, 2])
        self.assertEqual(self.repo.subtasks_estimate_sum(self.task["id"]), 55)

    def test_done_toggle_and_edit(self):
        sub = self.repo.add_subtask(self.task["id"], "Gráficos", 30)
        done = self.repo.update_subtask(sub["id"], done=True, title="Gráficos de vendas")
        self.assertEqual((done["done"], done["title"]), (1, "Gráficos de vendas"))
        self.assertIsNotNone(done["done_at"])
        undone = self.repo.set_subtask_done(sub["id"], False)
        self.assertIsNone(undone["done_at"])
        with self.assertRaises(KeyError):
            self.repo.set_subtask_done("nao-existe")

    def test_reorder_and_delete(self):
        ids = [self.repo.add_subtask(self.task["id"], f"S{i}")["id"] for i in range(3)]
        self.repo.reorder_subtasks(self.task["id"], [ids[1], ids[2], ids[0]])
        self.assertEqual([s["id"] for s in self.repo.list_subtasks(self.task["id"])], [ids[1], ids[2], ids[0]])
        self.repo.delete_subtask(ids[1])
        self.assertEqual(len(self.repo.list_subtasks(self.task["id"])), 2)

    def test_add_to_missing_task(self):
        with self.assertRaises(KeyError):
            self.repo.add_subtask("nao-existe", "X")


class SessionTest(RepoTest):
    def setUp(self):
        super().setUp()
        self.task = self.repo.create_task(self.group["id"], "Relatório", estimate_min=90)
        self.sub = self.repo.add_subtask(self.task["id"], "Números", 25)

    def test_real_time_sums_work_and_manual_only(self):
        s1 = self.repo.start_session("work", subtask_id=self.sub["id"])
        self.clock.advance(minutes=25)
        self.repo.end_session(s1, 25 * 60)
        b = self.repo.start_session("short_break", task_id=self.task["id"])
        self.repo.end_session(b, 300)
        s2 = self.repo.start_session("work", task_id=self.task["id"])
        self.repo.end_session(s2, 10 * 60, interrupted=True)
        # Tarefa soma a sessão da subtarefa (task_id herdado) e a da própria tarefa; pausa não conta.
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 35 * 60)
        self.assertEqual(self.repo.real_seconds_subtask(self.sub["id"]), 25 * 60)
        self.repo.add_manual_adjustment(self.task["id"], -5 * 60)
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 30 * 60)
        self.assertEqual(self.repo.get_session(s1)["task_id"], self.task["id"])

    def test_real_time_never_negative(self):
        self.repo.add_manual_adjustment(self.task["id"], -600)
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 0)

    def test_session_validation(self):
        with self.assertRaises(ValueError):
            self.repo.start_session("cochilo")
        sid = self.repo.start_session("work")
        with self.assertRaises(ValueError):
            self.repo.end_session(sid, -1)
        with self.assertRaises(KeyError):
            self.repo.end_session(9999, 10)

    def test_list_and_count(self):
        s1 = self.repo.start_session("work", task_id=self.task["id"])
        self.repo.end_session(s1, 1500)
        self.clock.advance(hours=1)
        s2 = self.repo.start_session("work", task_id=self.task["id"])
        self.repo.end_session(s2, 300, interrupted=True)
        self.clock.advance(minutes=1)
        self.repo.start_session("work", task_id=self.task["id"])  # ainda aberta
        self.assertEqual(len(self.repo.list_sessions(task_id=self.task["id"])), 3)
        self.assertEqual(self.repo.count_work_sessions(), 1)
        later = self.repo.list_sessions(since=datetime(2026, 11, 9, 14, 30))
        self.assertEqual([s["id"] for s in later][0], s2)

    def test_deleting_task_keeps_history(self):
        sid = self.repo.start_session("work", task_id=self.task["id"])
        self.repo.end_session(sid, 600)
        self.repo.delete_task(self.task["id"])
        session = self.repo.get_session(sid)
        self.assertIsNotNone(session)
        self.assertIsNone(session["task_id"])


class DistractionAndReviewTest(RepoTest):
    def test_distractions(self):
        did = self.repo.add_distraction("  ligar para o banco ")
        self.repo.add_distraction("comprar café")
        items = self.repo.list_distractions()
        self.assertEqual([d["text"] for d in items], ["ligar para o banco", "comprar café"])
        self.repo.delete_distraction(did)
        self.assertEqual(len(self.repo.list_distractions()), 1)
        with self.assertRaises(ValueError):
            self.repo.add_distraction("   ")

    def test_day_review_upsert_keeps_previous_values(self):
        self.repo.save_day_review("2026-11-09", mood="ok")
        review = self.repo.save_day_review(date(2026, 11, 9), free_minutes=360, confirmed=True)
        self.assertEqual(review["mood"], "ok")
        self.assertEqual(review["free_minutes"], 360)
        self.assertEqual(review["confirmed_at"], "2026-11-09T14:00:00")
        with self.assertRaises(ValueError):
            self.repo.save_day_review("2026-11-09", mood="ótimo")
        self.assertIsNone(self.repo.get_day_review("2026-11-10"))


if __name__ == "__main__":
    unittest.main()
