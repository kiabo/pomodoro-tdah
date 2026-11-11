import tempfile
import unittest

from tests_gtk._support import labels, make_controller, populate, require_gtk, walk

require_gtk()

from gi.repository import Gtk  # noqa: E402

from pomodoro.jira.client import JiraClient  # noqa: E402
from pomodoro.ui.dialogs.jira_import import JiraImportDialog  # noqa: E402
from pomodoro.ui.pages.settings_page import SettingsPage  # noqa: E402
from pomodoro.ui.pages.task_editor import TaskEditorPage  # noqa: E402
from pomodoro.ui.task_list import TaskList  # noqa: E402
from tests.jira_support import FakeJira, raw_issue  # noqa: E402


class JiraUiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(
            self._tmp.name, jira_url="https://x.atlassian.net", jira_email="eu@exemplo.com", jira_token="tok")
        self.fake = FakeJira(pages=[[raw_issue("ABC-1", description="Corpo da issue"), raw_issue("ABC-2", seconds=None)]])
        self.controller._jira_factory = lambda url, email, token: JiraClient(url, email, token, transport=self.fake)
        self.controller._run_async = lambda job, deliver: deliver(job())
        self.repo = self.controller.repo

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def import_all(self):
        items, _ = self.preview()
        self.controller.jira_import(items)
        return self.repo.jira_link_by_key("ABC-1")["task_id"]

    def preview(self):
        box = []
        self.controller.jira_preview(lambda items, error: box.append((items, error)))
        return box[0]

    def test_settings_tab_fields_and_test_button(self):
        page = SettingsPage(self.controller)
        self.assertEqual(page.jira_entries["jira_url"].get_text(), "https://x.atlassian.net")
        self.assertFalse(page.jira_entries["jira_token"].get_visibility())
        page.jira_entries["jira_jql"].set_text("project = ABC")
        page._on_jira_test()
        self.assertEqual(page.jira_status.get_text(), "✓ Conectado como Fabiano.")
        self.assertEqual(self.controller.settings["jira_jql"], "project = ABC")
        self.assertTrue(page.jira_test_button.get_sensitive())

    def test_settings_shows_error_message(self):
        self.fake.status = 401
        page = SettingsPage(self.controller)
        page._on_jira_test()
        self.assertIn("recusou", page.jira_status.get_text())

    def test_import_dialog_lists_issues_and_groups(self):
        items, error = self.preview()
        self.assertIsNone(error)
        dialog = JiraImportDialog(None, self.controller, items)
        self.addCleanup(dialog.destroy)
        texts = labels(dialog.get_content_area())
        self.assertTrue(any("2 novas" in t for t in texts))
        self.assertIn("ABC-1", texts)
        self.assertEqual(list(dialog.group_selects), ["ABC"])
        self.assertTrue(dialog.import_button.get_sensitive())
        dialog.checks["ABC-2"].set_active(False)
        self.assertEqual([i.issue["key"] for i in dialog.selected_items()], ["ABC-1"])
        for check in dialog.checks.values():
            check.set_active(False)
        self.assertFalse(dialog.import_button.get_sensitive())

    def test_task_list_shows_badge_and_editor_shows_card(self):
        task_id = self.import_all()
        view = self.controller.today_view()
        tasks = TaskList(self.controller)
        tasks.render(view)
        self.assertIn("ABC-1", labels(tasks))

        editor = TaskEditorPage(self.controller)
        self.addCleanup(editor.destroy)
        editor.load(task_id)
        self.assertTrue(editor.jira_card.get_visible())
        self.assertEqual(editor.jira_key_label.get_text(), "ABC-1")
        self.assertEqual(editor.jira_estimate_label.get_text(), "Previsão no Jira: 1h")
        self.assertFalse(editor.jira_use_estimate.get_visible())      # a tarefa já nasceu com essa previsão
        self.controller.update_task(task_id, estimate_min=45)
        editor.on_data("data")
        self.assertTrue(editor.jira_use_estimate.get_visible())
        editor._on_jira_use_estimate()
        self.assertEqual(self.repo.get_task(task_id)["estimate_min"], 60)

    def test_editor_hides_card_for_plain_tasks(self):
        data = populate(self.controller)
        editor = TaskEditorPage(self.controller)
        self.addCleanup(editor.destroy)
        editor.load(data["report"]["id"])
        self.assertFalse(editor.jira_card.get_visible())


if __name__ == "__main__":
    unittest.main()
