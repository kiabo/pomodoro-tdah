import os
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

from pomodoro import settings as settings_mod
from pomodoro.controller import Controller
from pomodoro.jira.client import JiraClient

from .jira_support import FakeJira, raw_issue
from .test_repository import FakeClock
from .test_timer import FakeScheduler

SETTINGS = {"jira_url": "https://x.atlassian.net", "jira_email": "eu@exemplo.com", "jira_token": "tok"}


class ControllerJiraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJira(pages=[[raw_issue("ABC-1"), raw_issue("XYZ-2", project="XYZ", summary="Outra")]])

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def make(self, **settings):
        self.controller = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize({**SETTINGS, **settings}),
            scheduler=FakeScheduler(), now=FakeClock(datetime(2026, 11, 9, 14, 0, 0)),
            today=lambda: date(2026, 11, 9), run_async=lambda job, deliver: deliver(job()),
            jira_factory=lambda url, email, token: JiraClient(url, email, token, transport=self.fake))
        return self.controller

    def result_of(self, call, *args):
        box = []
        call(*args, lambda result, error: box.append((result, error)))
        return box[0]

    def test_not_configured_does_not_call_jira(self):
        c = self.make(jira_token="")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JIRA_API_TOKEN", None)
            self.assertFalse(c.jira_configured())
            result, error = self.result_of(c.test_jira_connection)
        self.assertIsNone(result)
        self.assertIn("Configurações → Jira", error)
        self.assertEqual(self.fake.calls, [])

    def test_token_can_come_from_environment(self):
        c = self.make(jira_token="")
        with mock.patch.dict(os.environ, {"JIRA_API_TOKEN": "do-ambiente"}):
            self.assertTrue(c.jira_configured())

    def test_connection(self):
        c = self.make()
        self.assertEqual(self.result_of(c.test_jira_connection), ("Fabiano", None))

    def test_connection_error_is_a_message(self):
        self.fake.status = 401
        c = self.make()
        result, error = self.result_of(c.test_jira_connection)
        self.assertIsNone(result)
        self.assertIn("recusou", error)

    def test_preview_writes_nothing_and_import_creates_tasks(self):
        c = self.make()
        items, error = self.result_of(c.jira_preview)
        self.assertIsNone(error)
        self.assertEqual([i.issue["key"] for i in items], ["ABC-1", "XYZ-2"])
        self.assertEqual(c.repo.list_jira_links(), [])
        events = []
        c.subscribe(events.append)
        group = c.repo.create_group("Trabalho")
        result = c.jira_import(items, {"ABC": group["id"], "XYZ": ""})
        self.assertEqual(result["created"], 2)
        self.assertIn("data", events)
        abc = c.repo.get_task(c.repo.jira_link_by_key("ABC-1")["task_id"])
        xyz = c.repo.get_task(c.repo.jira_link_by_key("XYZ-2")["task_id"])
        self.assertEqual(abc["group_id"], group["id"])
        self.assertEqual(c.repo.get_group(xyz["group_id"])["name"], "Jira")
        self.assertEqual(c.settings["jira_project_groups"], {"ABC": group["id"]})
        self.assertTrue(all(call["method"] == "GET" or "search" in call["url"] for call in self.fake.calls))

    def test_today_view_shows_jira_key_and_search_finds_it(self):
        c = self.make()
        items, _ = self.result_of(c.jira_preview)
        c.jira_import(items)
        view = c.today_view()
        self.assertEqual(sorted(t.jira_key for t in view.visible_tasks), ["ABC-1", "XYZ-2"])
        self.assertEqual([t.jira_key for t in c.today_view(query="xyz-2").visible_tasks], ["XYZ-2"])

    def test_unlink(self):
        c = self.make()
        items, _ = self.result_of(c.jira_preview)
        c.jira_import(items)
        task_id = c.repo.jira_link_by_key("ABC-1")["task_id"]
        c.jira_unlink(task_id)
        self.assertIsNone(c.jira_link(task_id))
        self.assertIsNotNone(c.repo.get_task(task_id))


if __name__ == "__main__":
    unittest.main()
