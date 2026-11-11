import tempfile
import unittest
from unittest import mock

from tests_gtk._support import labels, make_controller, populate, require_gtk, walk

require_gtk()

from gi.repository import Gtk  # noqa: E402

from pomodoro.jira.client import JiraClient  # noqa: E402
from pomodoro.ui.dialogs import jira_push as push_dialog  # noqa: E402
from pomodoro.ui.dialogs.jira_import import JiraImportDialog  # noqa: E402
from pomodoro.ui.compact_window import CompactWindow  # noqa: E402
from pomodoro.ui.main_window import MainWindow  # noqa: E402
from pomodoro.ui.pages.settings_page import SettingsPage  # noqa: E402
from pomodoro.ui.pages.task_editor import TaskEditorPage  # noqa: E402
from pomodoro.ui.task_list import TaskList  # noqa: E402
from tests.jira_support import FakeJira, raw_issue  # noqa: E402


class JiraUiCase(unittest.TestCase):
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



class JiraUiTest(JiraUiCase):
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


class JiraPushUiTest(JiraUiCase):
    def writes(self):
        return [c for c in self.fake.calls if c["method"] in ("POST", "PUT") and "search" not in c["url"]]

    def editor_for(self, task_id):
        editor = TaskEditorPage(self.controller)
        self.addCleanup(editor.destroy)
        editor.load(task_id)
        return editor

    def test_comment_dialog_shows_exact_text_and_cancel_sends_nothing(self):
        task_id = self.import_all()
        self.repo.update_task(task_id, notes="Meu plano\n- passo")
        editor = self.editor_for(task_id)
        preview = self.controller.jira_prepare_comment(task_id)
        dialog = push_dialog.JiraPushDialog(None, preview)
        self.addCleanup(dialog.destroy)
        buffer = dialog.text_view.get_buffer()
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), "Meu plano\n- passo")
        self.assertFalse(preview["confirmed"])
        with mock.patch.object(push_dialog, "ask_push", return_value=None):
            editor._on_jira_comment()
        self.assertEqual(self.writes(), [])

    def test_confirmed_comment_goes_out_and_shows_notice(self):
        task_id = self.import_all()
        self.repo.update_task(task_id, notes="Meu plano")
        editor = self.editor_for(task_id)

        def confirm(_parent, preview):
            preview["confirmed"] = True
            return preview

        with mock.patch.object(push_dialog, "ask_push", side_effect=confirm):
            editor._on_jira_comment()
        self.assertEqual([w["body"] for w in self.writes()], [{"body": "Meu plano"}])
        self.assertEqual(editor.notice_label.get_text(), "Enviado para ABC-1.")
        self.assertIn("comentário", editor.jira_last_push.get_text())

    def test_comment_without_notes_shows_error_not_dialog(self):
        editor = self.editor_for(self.import_all())
        with mock.patch.object(push_dialog, "ask_push") as ask:
            editor._on_jira_comment()
        ask.assert_not_called()
        self.assertIn("não tem notas", editor.notice_label.get_text())

    def test_fields_dialog_unchecking_skips_a_field(self):
        task_id = self.import_all()
        self.repo.update_task(task_id, title="Meu título", estimate_min=45)
        preview = self.controller.jira_prepare_fields(task_id)
        dialog = push_dialog.JiraPushDialog(None, preview)
        self.addCleanup(dialog.destroy)
        self.assertTrue(dialog.send_button.get_sensitive())
        dialog.checks[0][0].set_active(False)
        dialog.checks[1][0].set_active(False)
        self.assertFalse(dialog.send_button.get_sensitive())
        dialog.checks[1][0].set_active(True)
        confirmed = dialog.confirm()
        self.assertEqual([c["selected"] for c in confirmed["changes"]], [False, True])
        self.assertTrue(confirmed["confirmed"])

    def test_status_dialog_needs_a_choice(self):
        task_id = self.import_all()
        box = []
        self.controller.jira_prepare_status(task_id, lambda preview, error: box.append(preview))
        dialog = push_dialog.JiraPushDialog(None, box[0])
        self.addCleanup(dialog.destroy)
        self.assertFalse(dialog.send_button.get_sensitive())
        dialog.radios[1][0].set_active(True)
        self.assertTrue(dialog.send_button.get_sensitive())
        self.assertEqual(dialog.confirm()["transition_id"], dialog.radios[1][1]["id"])

    def test_offer_after_completing_asks_and_declining_sends_nothing(self):
        task_id = self.import_all()
        window = MainWindow(self.controller)
        self.addCleanup(window.destroy)
        with mock.patch.object(MainWindow, "get_visible", return_value=True), \
                mock.patch("pomodoro.ui.main_window.dialogs.confirm", return_value=False) as ask:
            window.offer_jira_status(task_id)
        self.assertIn("ABC-1", ask.call_args.args[1])
        self.assertEqual(self.writes(), [])

    def test_offer_accepted_opens_status_dialog(self):
        task_id = self.import_all()
        window = MainWindow(self.controller)
        self.addCleanup(window.destroy)
        with mock.patch.object(MainWindow, "get_visible", return_value=True), \
                mock.patch("pomodoro.ui.main_window.dialogs.confirm", return_value=True), \
                mock.patch.object(push_dialog, "ask_push", return_value=None) as ask:
            window.offer_jira_status(task_id)
        self.assertEqual(ask.call_args.args[1]["kind"], "status")
        self.assertEqual(self.writes(), [])


class JiraJ4UiTest(JiraUiCase):
    def setUp(self):
        super().setUp()
        self.task_id = self.import_all()
        self.fake.calls.clear()
        self.editor = TaskEditorPage(self.controller)
        self.addCleanup(self.editor.destroy)
        self.editor.load(self.task_id)

    def writes(self):
        return [c for c in self.fake.calls if c["method"] in ("POST", "PUT")]

    def seed(self):
        with self.controller.conn:
            self.controller.conn.execute(
                "INSERT INTO sessions(task_id, kind, started_at, ended_at, seconds) "
                "VALUES (?, 'work', '2026-11-09T09:00:00', '2026-11-09T09:25:00', 1500)", (self.task_id,))

    def confirm_all(self, _parent, preview):
        preview["confirmed"] = True
        return preview

    def test_worklog_dialog_lists_days_and_needs_a_selection(self):
        self.seed()
        preview = self.controller.jira_prepare_worklog(self.task_id)
        dialog = push_dialog.JiraPushDialog(None, preview)
        self.addCleanup(dialog.destroy)
        self.assertTrue(any("09/11/2026" in t for t in labels(dialog.get_content_area())))
        self.assertTrue(dialog.send_button.get_sensitive())
        dialog.day_checks[0][0].set_active(False)
        self.assertFalse(dialog.send_button.get_sensitive())

    def test_worklog_button_sends_and_updates_card(self):
        self.seed()
        with mock.patch.object(push_dialog, "ask_push", side_effect=self.confirm_all):
            self.editor._on_jira_worklog()
        self.assertEqual(self.writes()[0]["body"]["timeSpentSeconds"], 1500)
        self.assertIn("25m", self.editor.jira_logged_label.get_text().replace(" ", ""))
        self.assertTrue(self.editor.jira_logged_label.get_visible())

    def test_worklog_without_time_shows_notice(self):
        with mock.patch.object(push_dialog, "ask_push") as ask:
            self.editor._on_jira_worklog()
        ask.assert_not_called()
        self.assertIn("Não há tempo novo", self.editor.notice_label.get_text())

    def test_create_subtasks_flow_and_badge(self):
        self.controller.add_subtask(self.task_id, "Passo A", 15)
        self.editor.load(self.task_id)
        with mock.patch.object(push_dialog, "ask_push", side_effect=self.confirm_all):
            self.editor._on_jira_subtasks()
        self.assertEqual(self.writes()[0]["body"]["fields"]["summary"], "Passo A")
        badges = [r.jira_badge.get_text() for r in self.editor.sub_rows_box.get_children()]
        self.assertEqual(badges, ["ABC-101"])

    def test_subtasks_dialog_with_several_types_lets_user_choose(self):
        self.controller.add_subtask(self.task_id, "Passo A")
        self.fake.sub_types = [{"id": "1", "name": "Sub-task", "subtask": True},
                               {"id": "2", "name": "Bug sub", "subtask": True}]
        box = []
        self.controller.jira_prepare_subtasks(self.task_id, lambda preview, error: box.append(preview))
        dialog = push_dialog.JiraPushDialog(None, box[0])
        self.addCleanup(dialog.destroy)
        dialog.type_radios[1][0].set_active(True)
        dialog.sub_checks[0][0].set_active(True)
        self.assertEqual(dialog.confirm()["type_id"], "2")

    def test_pull_subtasks_flow(self):
        self.fake.remote_subtasks = [
            {"key": "ABC-5", "fields": {"summary": "Já existe lá", "status": {"statusCategory": {"key": "new"}}}}]
        with mock.patch.object(push_dialog, "ask_pull", side_effect=lambda parent, key, found: found):
            self.editor._on_jira_pull()
        self.assertIn("1 subtarefa", self.editor.notice_label.get_text())
        self.assertEqual(self.controller.repo.list_subtasks(self.task_id)[0]["jira_key"], "ABC-5")
        self.assertEqual(self.writes(), [])

    def test_pull_dialog_choices(self):
        found = [{"key": "ABC-5", "title": "A", "done": False}, {"key": "ABC-6", "title": "B", "done": True}]
        dialog = push_dialog.JiraPullDialog(None, "ABC-1", found)
        self.addCleanup(dialog.destroy)
        dialog.checks[0][0].set_active(False)
        self.assertEqual([i["key"] for i in dialog.chosen()], ["ABC-6"])
        dialog.checks[1][0].set_active(False)
        self.assertFalse(dialog.import_button.get_sensitive())


class JiraJ5UiTest(JiraUiCase):
    def setUp(self):
        super().setUp()
        self.task_id = self.import_all()
        self.fake.calls.clear()

    def diverge(self):
        self.repo.update_task(self.task_id, title="Meu título", estimate_min=45)
        self.fake.pages = [[raw_issue("ABC-1", summary="Título do time", seconds=7200)]]
        items, _ = self.preview()
        self.controller.jira_import(items)

    def test_settings_auto_sync_choice_is_saved_and_status_shown(self):
        page = SettingsPage(self.controller)
        self.assertEqual(page.jira_auto_select.value, 0)
        page._apply({"jira_auto_sync_min": 30})
        self.assertEqual(self.controller.settings["jira_auto_sync_min"], 30)
        self.assertEqual(page.jira_sync_label.get_text(), "")
        self.fake.pages = [[raw_issue("ABC-1"), raw_issue("ABC-9")]]
        self.controller.jira_auto_sync()
        page.refresh_jira_status()
        self.assertIn("1 nova(s) para importar", page.jira_sync_label.get_text())
        self.fake.status = 401
        self.controller.jira_auto_sync()
        page.refresh_jira_status()
        self.assertIn("falhou", page.jira_sync_label.get_text())

    def test_main_window_refreshes_status_on_sync_event(self):
        window = MainWindow(self.controller)
        self.addCleanup(window.destroy)
        self.fake.pages = [[raw_issue("ABC-1")]]
        self.controller.jira_auto_sync()
        self.assertIn("Atualizado", window.settings_page.jira_sync_label.get_text())

    def test_card_shows_conflicts_and_resolves_them(self):
        self.diverge()
        editor = TaskEditorPage(self.controller)
        self.addCleanup(editor.destroy)
        editor.load(self.task_id)
        texts = labels(editor.jira_conflicts_box)
        self.assertEqual(len([t for t in texts if "foi mantido" in t]), 2)
        self.assertEqual(self.repo.get_task(self.task_id)["title"], "Meu título")
        buttons = [w for w in walk(editor.jira_conflicts_box) if isinstance(w, Gtk.Button)]
        self.assertEqual(sorted(b.get_label() for b in buttons),
                         ["Manter o meu", "Manter o meu", "Usar o do Jira", "Usar o do Jira"])
        editor._resolve_conflict("title", True)
        self.assertEqual(self.repo.get_task(self.task_id)["title"], "Título do time")
        editor._resolve_conflict("estimate", False)
        self.assertEqual(self.repo.get_task(self.task_id)["estimate_min"], 45)
        self.assertEqual(labels(editor.jira_conflicts_box), [])
        self.assertEqual([c for c in self.fake.calls if c["method"] in ("POST", "PUT")
                          and "search" not in c["url"]], [])

    def test_compact_card_shows_issue_key(self):
        window = CompactWindow(self.controller, on_expand=lambda: None, on_close=lambda: None,
                               on_adjust=lambda task_id: None)
        self.addCleanup(window.destroy)
        with mock.patch.object(window, "get_visible", return_value=True):
            self.controller.focus(self.task_id)
            window.refresh()
        self.assertEqual(window.focus_card.parent.get_text(), "ABC-1")
        self.assertTrue(window.focus_card.parent.get_visible())


if __name__ == "__main__":
    unittest.main()
