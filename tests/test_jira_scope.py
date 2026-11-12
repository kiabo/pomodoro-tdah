import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pomodoro import settings as settings_mod
from pomodoro.controller import Controller
from pomodoro.jira import client as jc
from pomodoro.jira.client import JiraClient

from .jira_support import FakeJira, raw_issue
from .test_repository import FakeClock
from .test_timer import FakeScheduler

SETTINGS = {"jira_url": "https://x.atlassian.net", "jira_email": "eu@exemplo.com", "jira_token": "tok"}


class JqlForTest(unittest.TestCase):
    def test_scopes(self):
        self.assertEqual(jc.jql_for("mine"), jc.DEFAULT_JQL)
        self.assertIn("assignee is EMPTY", jc.jql_for("mine"))
        self.assertEqual(jc.jql_for("assigned"), jc.ASSIGNED_JQL)
        self.assertNotIn("EMPTY", jc.jql_for("assigned"))
        self.assertEqual(jc.jql_for("custom", "  project = ABC  "), "project = ABC")

    def test_custom_without_text_or_unknown_falls_back_to_default(self):
        self.assertEqual(jc.jql_for("custom", "   "), jc.DEFAULT_JQL)
        self.assertEqual(jc.jql_for("qualquer"), jc.DEFAULT_JQL)


class ScopeSettingTest(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(settings_mod.sanitize({})["jira_scope"], "mine")
        self.assertEqual(settings_mod.sanitize({"jira_scope": "assigned"})["jira_scope"], "assigned")
        self.assertEqual(settings_mod.sanitize({"jira_scope": "lixo"})["jira_scope"], "mine")

    def test_existing_custom_search_keeps_working(self):
        loaded = settings_mod.sanitize({"jira_jql": "project = ABC"})          # arquivo antigo, sem jira_scope
        self.assertEqual((loaded["jira_scope"], loaded["jira_jql"]), ("custom", "project = ABC"))
        explicit = settings_mod.sanitize({"jira_jql": "project = ABC", "jira_scope": "mine"})
        self.assertEqual(explicit["jira_scope"], "mine")                         # a escolha explícita vence
        self.assertEqual(settings_mod.sanitize({"jira_jql": "   "})["jira_scope"], "mine")

    def test_roundtrip_through_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps({"jira_jql": "x = 1"}))
            self.assertEqual(settings_mod.load_settings(tmp)["jira_scope"], "custom")


class ControllerScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJira(pages=[[raw_issue("ABC-1")]])

    def tearDown(self):
        self.c.shutdown()
        self._tmp.cleanup()

    def make(self, **settings):
        self.c = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize({**SETTINGS, **settings}),
            scheduler=FakeScheduler(), now=FakeClock(datetime(2026, 11, 9, 14, 0, 0)),
            today=lambda: date(2026, 11, 9), run_async=lambda job, deliver: deliver(job()),
            jira_factory=lambda url, email, token: JiraClient(url, email, token, transport=self.fake))
        return self.c

    def searched_jql(self):
        self.c.jira_preview(lambda items, error: None)
        return self.fake.calls[-1]["body"]["jql"]

    def test_each_scope_sends_its_search(self):
        self.make()
        self.assertEqual(self.searched_jql(), jc.DEFAULT_JQL)
        self.c.apply_settings({"jira_scope": "assigned"})
        self.fake.pages = [[]]
        self.assertEqual(self.searched_jql(), jc.ASSIGNED_JQL)
        self.c.apply_settings({"jira_scope": "custom", "jira_jql": "project = ABC"})
        self.fake.pages = [[]]
        self.assertEqual(self.searched_jql(), "project = ABC")

    def test_menu_info_counts(self):
        self.make()
        items = []
        self.fake.pages = [[raw_issue("ABC-1")]]
        self.c.jira_preview(lambda result, error: items.extend(result))
        self.c.jira_import(items)
        task_id = self.c.repo.jira_link_by_key("ABC-1")["task_id"]
        info = self.c.jira_menu_info(task_id)
        self.assertEqual(info, {"has_notes": False, "unlogged_seconds": 0, "field_differences": 0, "local_subtasks": 0})
        self.c.repo.update_task(task_id, notes="plano", title="Meu título", estimate_min=45)
        self.c.add_subtask(task_id, "Passo")
        with self.c.conn:
            self.c.conn.execute("INSERT INTO sessions(task_id, kind, started_at, ended_at, seconds) "
                                "VALUES (?, 'work', '2026-11-09T09:00:00', '2026-11-09T09:25:00', 1500)", (task_id,))
        info = self.c.jira_menu_info(task_id)
        self.assertEqual(info, {"has_notes": True, "unlogged_seconds": 1500, "field_differences": 2,
                                "local_subtasks": 1})
        plain = self.c.add_task("Solta")
        with self.assertRaises(ValueError):
            self.c.jira_menu_info(plain["id"])


if __name__ == "__main__":
    unittest.main()
