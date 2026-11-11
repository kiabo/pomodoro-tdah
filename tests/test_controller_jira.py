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


class JiraControllerCase(unittest.TestCase):
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

class ControllerJiraTest(JiraControllerCase):
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


class ControllerJiraPushTest(JiraControllerCase):
    def linked(self, **fields):
        c = self.make()
        items, _ = self.result_of(c.jira_preview)
        c.jira_import(items)
        self.fake.calls.clear()
        task_id = c.repo.jira_link_by_key("ABC-1")["task_id"]
        if fields:
            c.repo.update_task(task_id, **fields)
        return c, task_id

    def writes(self):
        return [call for call in self.fake.calls if call["method"] in ("POST", "PUT") and "search" not in call["url"]]

    def test_preparing_never_writes(self):
        c, task_id = self.linked(notes="minhas notas", title="Outro")
        c.jira_prepare_comment(task_id)
        c.jira_prepare_fields(task_id)
        self.result_of(c.jira_prepare_status, task_id)
        self.assertEqual(self.writes(), [])

    def test_push_requires_confirmation(self):
        c, task_id = self.linked(notes="minhas notas")
        preview = c.jira_prepare_comment(task_id)
        result, error = self.result_of(c.jira_push, preview)
        self.assertIsNone(result)
        self.assertIn("não confirmado", error)
        self.assertEqual(self.writes(), [])
        self.assertEqual(c.jira_pushes(task_id), [])

    def test_comment_is_sent_and_logged(self):
        c, task_id = self.linked(notes="minhas notas")
        preview = c.jira_prepare_comment(task_id)
        preview["confirmed"] = True
        events = []
        c.subscribe(events.append)
        self.assertEqual(self.result_of(c.jira_push, preview), ("Enviado para ABC-1.", None))
        self.assertEqual([w["body"] for w in self.writes()], [{"body": "minhas notas"}])
        self.assertEqual(c.jira_pushes(task_id)[0]["kind"], "comment")
        self.assertIn("data", events)

    def test_failed_push_is_not_logged(self):
        c, task_id = self.linked(notes="minhas notas")
        self.fake.write_status = 403
        preview = c.jira_prepare_comment(task_id)
        preview["confirmed"] = True
        result, error = self.result_of(c.jira_push, preview)
        self.assertIn("permissão", error)
        self.assertEqual(c.jira_pushes(task_id), [])

    def test_status_flow_updates_link(self):
        c, task_id = self.linked()
        preview, error = self.result_of(c.jira_prepare_status, task_id)
        self.assertEqual([o["id"] for o in preview["options"]], ["11", "31"])
        preview.update(confirmed=True, transition_id="31")
        self.assertEqual(self.result_of(c.jira_push, preview)[1], None)
        self.assertEqual(c.jira_link(task_id)["remote_status"], "Done")
        self.assertEqual(c.jira_link(task_id)["remote_status_category"], "done")
        self.assertEqual(self.writes()[0]["body"], {"transition": {"id": "31"}})

    def test_fields_flow_updates_link_so_import_stays_quiet(self):
        c, task_id = self.linked(title="Meu título", estimate_min=45)
        preview = c.jira_prepare_fields(task_id)
        preview["confirmed"] = True
        self.assertIsNone(self.result_of(c.jira_push, preview)[1])
        link = c.jira_link(task_id)
        self.assertEqual((link["remote_title"], link["remote_estimate_min"]), ("Meu título", 45))
        self.fake.pages = [[raw_issue("ABC-1", summary="Meu título", seconds=45 * 60), raw_issue("XYZ-2", project="XYZ")]]
        items, _ = self.result_of(c.jira_preview)
        self.assertEqual(next(i for i in items if i.issue["key"] == "ABC-1").action, "same")

    def test_unlinked_task_cannot_be_pushed(self):
        c = self.make()
        task = c.add_task("Solta")
        with self.assertRaises(ValueError):
            c.jira_prepare_comment(task["id"])
        self.assertIsNone(self.result_of(c.jira_prepare_status, task["id"])[0])

    def test_completing_linked_task_only_offers(self):
        c, task_id = self.linked()
        events = []
        c.subscribe(events.append)
        c.set_task_done(task_id, True)
        self.assertIn(f"jira-offer:{task_id}", events)
        self.assertEqual(self.writes(), [])
        other = c.add_task("Sem Jira")
        events.clear()
        c.set_task_done(other["id"], True)
        self.assertFalse([e for e in events if e.startswith("jira-offer")])
        c.repo.save_jira_link(task_id, "ABC-1", remote_status_category="done")
        events.clear()
        c.set_task_done(task_id, False)
        c.set_task_done(task_id, True)
        self.assertFalse([e for e in events if e.startswith("jira-offer")])      # já está concluída no Jira
