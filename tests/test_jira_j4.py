import re
import tempfile
import unittest
from datetime import date, datetime

from pomodoro import db, settings as settings_mod
from pomodoro.controller import Controller
from pomodoro.jira import client as jc, push
from pomodoro.jira.client import JiraClient

from .jira_support import FakeJira, raw_issue
from .test_repository import FakeClock
from .test_timer import FakeScheduler

URL = "https://x.atlassian.net"
SETTINGS = {"jira_url": URL, "jira_email": "eu@exemplo.com", "jira_token": "tok"}


def make(fake):
    return jc.JiraClient(URL, "eu@exemplo.com", "tok", transport=fake)


class ClientJ4Test(unittest.TestCase):
    def test_add_worklog(self):
        fake = FakeJira()
        self.assertEqual(make(fake).add_worklog("ABC-1", 1500, "2026-11-11T14:00:00.000-0300", "Pomodoro"), "W1")
        call = fake.calls[0]
        self.assertEqual((call["method"], call["url"]), ("POST", URL + "/rest/api/2/issue/ABC-1/worklog"))
        self.assertEqual(call["body"], {"timeSpentSeconds": 1500, "started": "2026-11-11T14:00:00.000-0300",
                                        "comment": "Pomodoro"})
        with self.assertRaises(jc.JiraError):
            make(fake).add_worklog("ABC-1", 30, "x")                 # o Jira não aceita menos de 1 minuto
        self.assertEqual(len(fake.calls), 1)

    def test_subtask_types_only_subtasks_and_error_when_none(self):
        fake = FakeJira()
        self.assertEqual(make(fake).subtask_types("ABC"), [{"id": "10003", "name": "Sub-task"}])
        fake.sub_types = [{"id": "1", "name": "Task", "subtask": False}]
        with self.assertRaises(jc.JiraError) as ctx:
            make(fake).subtask_types("ABC")
        self.assertIn("não permite sub-tarefas", str(ctx.exception))

    def test_create_subtask_payload(self):
        fake = FakeJira()
        key = make(fake).create_subtask("ABC-1", "ABC", " Passo ", "10003", 30)
        self.assertEqual(key, "ABC-101")
        self.assertEqual(fake.calls[0]["body"]["fields"], {
            "project": {"key": "ABC"}, "parent": {"key": "ABC-1"}, "issuetype": {"id": "10003"},
            "summary": "Passo", "timetracking": {"originalEstimate": "30m"}})
        make(fake).create_subtask("ABC-1", "ABC", "Sem tempo", "10003")
        self.assertNotIn("timetracking", fake.calls[1]["body"]["fields"])

    def test_subtasks_of(self):
        fake = FakeJira()
        fake.remote_subtasks = [
            {"key": "ABC-5", "fields": {"summary": "Feita", "status": {"statusCategory": {"key": "done"}}}},
            {"key": "ABC-6", "fields": {"summary": "Aberta", "status": {"statusCategory": {"key": "new"}}}}]
        self.assertEqual(make(fake).subtasks_of("ABC-1"), [
            {"key": "ABC-5", "title": "Feita", "done": True}, {"key": "ABC-6", "title": "Aberta", "done": False}])
        self.assertEqual(fake.calls[0]["method"], "GET")


class PreviewJ4Test(unittest.TestCase):
    TASK = {"id": "t1"}
    LINK = {"issue_key": "ABC-1", "project_key": "ABC"}

    def sessions(self):
        return [
            {"id": 1, "started_at": "2026-11-10T09:00:00", "seconds": 1500},
            {"id": 2, "started_at": "2026-11-10T09:30:00", "seconds": 1500},
            {"id": 3, "started_at": "2026-11-11T10:00:00", "seconds": 30},      # menos de 1 min no dia
            {"id": 4, "started_at": "2026-11-12T08:00:00", "seconds": 600},
            {"id": 5, "started_at": "2026-11-12T08:20:00", "seconds": -120}]    # ajuste manual negativo

    def test_worklog_groups_by_day_and_nets_adjustments(self):
        preview = push.worklog_preview(self.TASK, self.LINK, self.sessions())
        self.assertEqual([(d["day"], d["seconds"], d["session_ids"]) for d in preview["days"]],
                         [("2026-11-10", 3000, [1, 2]), ("2026-11-12", 480, [4, 5])])
        self.assertEqual(preview["skipped_seconds"], 30)
        self.assertRegex(preview["days"][0]["started"], r"^2026-11-10T09:00:00\.000[+-]\d{4}$")

    def test_worklog_with_nothing_raises(self):
        with self.assertRaises(ValueError):
            push.worklog_preview(self.TASK, self.LINK, [])
        with self.assertRaises(ValueError) as ctx:
            push.worklog_preview(self.TASK, self.LINK, [self.sessions()[2]])
        self.assertIn("menor que 1 minuto", str(ctx.exception))

    def test_subtasks_preview_skips_already_linked(self):
        subs = [{"id": "a", "title": "A", "estimate_min": 10, "jira_key": None},
                {"id": "b", "title": "B", "estimate_min": None, "jira_key": "ABC-9"}]
        preview = push.subtasks_preview(self.TASK, self.LINK, subs, [{"id": "1", "name": "Sub"}])
        self.assertEqual([i["subtask_id"] for i in preview["items"]], ["a"])
        with self.assertRaises(ValueError):
            push.subtasks_preview(self.TASK, self.LINK, subs[1:], [{"id": "1", "name": "Sub"}])

    def test_not_confirmed_or_empty_selection_is_refused(self):
        preview = push.worklog_preview(self.TASK, self.LINK, self.sessions())
        with self.assertRaises(ValueError):
            push.validate(preview)
        preview["confirmed"] = True
        for day in preview["days"]:
            day["selected"] = False
        with self.assertRaises(ValueError):
            push.validate(preview)


class ControllerJ4Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJira(pages=[[raw_issue("ABC-1")]])
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.c = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize(SETTINGS), scheduler=FakeScheduler(),
            now=self.clock, today=lambda: date(2026, 11, 9), run_async=lambda job, deliver: deliver(job()),
            jira_factory=lambda url, email, token: JiraClient(url, email, token, transport=self.fake))
        items = self.result_of(self.c.jira_preview)[0]
        self.c.jira_import(items)
        self.task_id = self.c.repo.jira_link_by_key("ABC-1")["task_id"]
        self.fake.calls.clear()

    def tearDown(self):
        self.c.shutdown()
        self._tmp.cleanup()

    def result_of(self, call, *args):
        box = []
        call(*args, lambda result, error: box.append((result, error)))
        return box[0]

    def seed_sessions(self):
        conn = self.c.conn
        ids = []
        for started, seconds in (("2026-11-09T09:00:00", 1500), ("2026-11-09T09:30:00", 1500),
                                 ("2026-11-10T09:00:00", 900)):
            with conn:
                cur = conn.execute("INSERT INTO sessions(task_id, kind, started_at, ended_at, seconds) "
                                   "VALUES (?, 'work', ?, ?, ?)", (self.task_id, started, started, seconds))
            ids.append(cur.lastrowid)
        return ids

    def writes(self):
        return [c for c in self.fake.calls if c["method"] in ("POST", "PUT")]

    def test_worklog_sends_per_day_and_never_twice(self):
        self.seed_sessions()
        preview = self.c.jira_prepare_worklog(self.task_id)
        self.assertEqual(self.writes(), [])
        preview["confirmed"] = True
        self.assertEqual(self.result_of(self.c.jira_push, preview), ("Enviado para ABC-1.", None))
        self.assertEqual([w["body"]["timeSpentSeconds"] for w in self.writes()], [3000, 900])
        self.assertEqual(self.c.repo.jira_logged_seconds(self.task_id), 3900)
        self.assertEqual(self.c.task_detail(self.task_id)["jira_logged_seconds"], 3900)
        with self.assertRaises(ValueError):
            self.c.jira_prepare_worklog(self.task_id)           # nada novo: não oferece de novo
        self.seed_sessions()
        again = self.c.jira_prepare_worklog(self.task_id)       # só as 3 novas, nunca as antigas
        self.assertEqual(sum(d["sessions"] for d in again["days"]), 3)

    def test_open_session_is_not_offered(self):
        self.c.repo.start_session("work", task_id=self.task_id)
        with self.assertRaises(ValueError):
            self.c.jira_prepare_worklog(self.task_id)

    def test_unselected_day_is_not_sent_and_stays_available(self):
        self.seed_sessions()
        preview = self.c.jira_prepare_worklog(self.task_id)
        preview["days"][0]["selected"] = False
        preview["confirmed"] = True
        self.result_of(self.c.jira_push, preview)
        self.assertEqual([w["body"]["timeSpentSeconds"] for w in self.writes()], [900])
        self.assertEqual(self.c.jira_prepare_worklog(self.task_id)["days"][0]["seconds"], 3000)

    def test_partial_failure_records_what_went_out(self):
        self.seed_sessions()
        preview = self.c.jira_prepare_worklog(self.task_id)
        preview["confirmed"] = True
        self.fake.fail_write_from = 2                          # o 1º dia passa, o 2º falha
        result, error = self.result_of(self.c.jira_push, preview)
        self.assertIsNone(result)
        self.assertIn("Enviei 1 de 2", error)
        self.assertEqual(self.c.repo.jira_logged_seconds(self.task_id), 3000)
        self.fake.fail_write_from = None
        retry = self.c.jira_prepare_worklog(self.task_id)       # só o dia que falhou
        self.assertEqual([d["day"] for d in retry["days"]], ["2026-11-10"])

    def test_first_failure_records_nothing(self):
        self.seed_sessions()
        preview = self.c.jira_prepare_worklog(self.task_id)
        preview["confirmed"] = True
        self.fake.write_status = 403
        result, error = self.result_of(self.c.jira_push, preview)
        self.assertIn("permissão", error)
        self.assertEqual(self.c.repo.jira_logged_seconds(self.task_id), 0)
        self.assertEqual(self.c.jira_pushes(self.task_id), [])

    def test_create_subtasks_links_them(self):
        a = self.c.add_subtask(self.task_id, "Passo A", 20)
        b = self.c.add_subtask(self.task_id, "Passo B")
        preview, error = self.result_of(self.c.jira_prepare_subtasks, self.task_id)
        self.assertEqual((error, preview["type_id"]), (None, "10003"))
        self.assertEqual(self.writes(), [])
        preview["items"][1]["selected"] = False
        preview["confirmed"] = True
        self.assertIsNone(self.result_of(self.c.jira_push, preview)[1])
        self.assertEqual(self.c.repo.get_subtask(a["id"])["jira_key"], "ABC-101")
        self.assertIsNone(self.c.repo.get_subtask(b["id"])["jira_key"])
        self.assertEqual(self.writes()[0]["body"]["fields"]["parent"], {"key": "ABC-1"})
        again, _ = self.result_of(self.c.jira_prepare_subtasks, self.task_id)
        self.assertEqual([i["subtask_id"] for i in again["items"]], [b["id"]])

    def test_subtask_preview_errors(self):
        self.assertIn("Todas as subtarefas", self.result_of(self.c.jira_prepare_subtasks, self.task_id)[1])
        self.c.add_subtask(self.task_id, "A")
        self.fake.sub_types = []
        self.assertIn("não permite sub-tarefas", self.result_of(self.c.jira_prepare_subtasks, self.task_id)[1])

    def test_local_subtasks_stay_local_by_default(self):
        self.c.add_subtask(self.task_id, "Só minha")
        self.c.set_subtask_done(self.c.repo.list_subtasks(self.task_id)[0]["id"], True)
        self.assertEqual(self.writes(), [])
        self.assertIsNone(self.c.task_detail(self.task_id)["subtasks"][0]["jira_key"])

    def test_pull_existing_subtasks(self):
        self.fake.remote_subtasks = [
            {"key": "ABC-5", "fields": {"summary": "Feita", "status": {"statusCategory": {"key": "done"}}}},
            {"key": "ABC-6", "fields": {"summary": "Aberta", "status": {"statusCategory": {"key": "new"}}}}]
        found, error = self.result_of(self.c.jira_prepare_pull_subtasks, self.task_id)
        self.assertEqual([f["key"] for f in found], ["ABC-5", "ABC-6"])
        self.assertEqual(self.c.jira_pull_subtasks(self.task_id, found), 2)
        subs = self.c.repo.list_subtasks(self.task_id)
        self.assertEqual([(s["title"], s["jira_key"], s["done"]) for s in subs],
                         [("Feita", "ABC-5", 1), ("Aberta", "ABC-6", 0)])
        self.assertEqual(self.writes(), [])
        found, error = self.result_of(self.c.jira_prepare_pull_subtasks, self.task_id)
        self.assertEqual((found, "Não há" in error), ([], True))           # nada novo na segunda vez


class MigrationTest(unittest.TestCase):
    def test_migration_5_keeps_old_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(f"{tmp}/p.db")
            for version in range(4):
                conn.executescript(db.MIGRATIONS[version])
                conn.execute(f"PRAGMA user_version = {version + 1}")
            conn.execute("INSERT INTO groups(id, name, created_at) VALUES ('g', 'G', 'x')")
            conn.execute("INSERT INTO tasks(id, group_id, title, created_at) VALUES ('t', 'g', 'T', 'x')")
            conn.execute("INSERT INTO jira_pushes(task_id, issue_key, kind, detail, sent_at) "
                         "VALUES ('t', 'ABC-1', 'comment', 'antigo', 'x')")
            conn.commit()
            db.migrate(conn)
            self.assertEqual(db.schema_version(conn), db.SCHEMA_VERSION)
            self.assertEqual(conn.execute("SELECT detail FROM jira_pushes").fetchone()[0], "antigo")
            conn.execute("INSERT INTO jira_pushes(task_id, issue_key, kind, sent_at) VALUES ('t', 'ABC-1', 'worklog', 'x')")
            conn.close()


if __name__ == "__main__":
    unittest.main()
