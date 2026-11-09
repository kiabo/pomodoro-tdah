import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from tests_gtk._support import find, labels, make_controller, populate, require_gtk, with_class

require_gtk()

from gi.repository import Gtk  # noqa: E402

from pomodoro.ui import dialogs  # noqa: E402
from pomodoro.ui.dialogs import new_task  # noqa: E402
from pomodoro.ui.main_window import MainWindow  # noqa: E402
from pomodoro.ui.pages.task_editor import TaskEditorPage, _SubtaskRow  # noqa: E402


class FakeEstimator:
    def suggest_estimate(self, repo, title, group_id, user_estimate_min):
        return {"minutes": 102, "note": "Baseado em 6 relatórios"}

    def suggest_subtasks(self, repo, title, group_id):
        return [("Parte um", 30), ("Parte dois", 30)]


class EditorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)
        self.repo = self.controller.repo
        self.task_id = self.data["report"]["id"]
        self.page = TaskEditorPage(self.controller)
        self.addCleanup(self.page.destroy)
        self.events = []
        for name in ("back", "focus-started"):
            self.page.connect(name, lambda *_a, n=name: self.events.append(n))
        self.page.connect("open-task", lambda _p, task_id: self.events.append(("open", task_id)))
        self.page.load(self.task_id)

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def task(self):
        return self.repo.get_task(self.task_id)

    def rows(self):
        return [r for r in self.page.sub_rows_box.get_children() if isinstance(r, _SubtaskRow)]

    def tick(self, n):
        for _ in range(n):
            self.controller.timer.tick()


class LoadTest(EditorTest):
    def test_fields_are_filled_from_the_task(self):
        p = self.page
        self.assertEqual(p.title_entry.get_text(), "Escrever relatório")
        self.assertEqual((p.group_select.value, p.group_select.get_text()), (self.data["work"]["id"], "Trabalho"))
        self.assertEqual((p.date_picker.date, p.repeat_select.value, p.energy.value), (date(2026, 11, 9), None, None))
        self.assertEqual((p.stepper.minutes, p.done_check.get_active()), (90, False))
        self.assertEqual(p.group_crumb.get_text(), "Trabalho")
        self.assertEqual(p.estimate_note_label.get_text(), "≈ 4 pomodoros · ⚠ as subtarefas somam 55m")
        self.assertTrue(p.estimate_note_label.get_style_context().has_class("text-danger"))
        self.assertEqual(self.page.real_value.get_text(), "0m")

    def test_lists_and_subtask_rows(self):
        titles = labels(self.page.list_box)
        self.assertIn("Escrever relatório", titles)
        self.assertIn("Lavar roupa", titles)
        self.assertEqual(len(with_class(self.page.list_box, "task-row-focus")), 1)
        self.assertEqual([r.title_entry.get_text() for r in self.rows()], ["Levantar números", "Montar gráficos"])
        self.assertEqual([r.time_entry.get_text() for r in self.rows()], ["25m", "30m"])

    def test_unknown_task_goes_back(self):
        self.page.load("nao-existe")
        self.assertEqual(self.events, ["back"])
        self.assertIsNone(self.page.task_id)

    def test_stored_rule_outside_the_usual_options_is_kept(self):
        self.repo.update_task(self.task_id, repeat_rule="weekly:4")        # sexta, mas a tarefa é de segunda
        self.page.load(self.task_id)
        self.assertEqual((self.page.repeat_select.value, self.page.repeat_select.get_text()),
                         ("weekly:4", "Toda semana (sexta)"))

    def test_no_ai_message_and_hidden_buttons_without_estimator(self):
        self.assertIn("Ainda não há histórico", self.page.ai_note.get_text())
        self.assertEqual(self.page.ai_value.get_text(), "—")
        self.assertFalse(self.page.ai_use.get_visible())
        self.assertFalse(self.page.ai_subs_button.get_visible())


class FieldsTest(EditorTest):
    def test_title(self):
        self.page.title_entry.set_text("  Relatório de novembro ")
        self.page.title_entry.activate()
        self.assertEqual(self.task()["title"], "Relatório de novembro")
        self.page.title_entry.set_text("   ")
        self.page.title_entry.activate()
        self.assertEqual(self.page.title_entry.get_text(), "Relatório de novembro")      # vazio volta ao salvo
        self.assertIn("Relatório de novembro", labels(self.page.list_box))                # lista acompanha

    def test_group_change_and_rule_violation(self):
        self.page.group_select.set_value(self.data["home"]["id"], emit=True)
        self.assertEqual(self.task()["group_id"], self.data["home"]["id"])
        self.assertEqual(self.page.group_crumb.get_text(), "Casa")
        strict = self.repo.create_group("Rígido", require_estimate=True)
        self.repo.update_task(self.task_id, estimate_min=None)
        self.page.load(self.task_id)
        self.page.group_select.set_items([(self.data["home"]["id"], "Casa"), (strict["id"], "Rígido")],
                                         self.data["home"]["id"])
        self.page.group_select.set_value(strict["id"], emit=True)
        self.assertEqual(self.task()["group_id"], self.data["home"]["id"])               # recusado
        self.assertTrue(self.page.notice_label.get_visible())
        self.assertIn("exige a previsão", self.page.notice_label.get_text())
        self.assertTrue(self.page.notice_label.get_style_context().has_class("text-danger"))

    def test_date_repeat_and_energy(self):
        self.page.date_picker.set_date(date(2026, 11, 12), emit=True)
        self.assertEqual(self.task()["scheduled_for"], "2026-11-12")
        self.page.date_picker.set_date(None, emit=True)
        self.assertIsNone(self.task()["scheduled_for"])
        self.page.repeat_select.set_value("weekdays", emit=True)
        self.assertEqual(self.task()["repeat_rule"], "weekdays")
        self.page.energy.set_value("high", emit=True)
        self.assertEqual(self.task()["energy"], "high")

    def test_estimate_stepper(self):
        self.page.stepper.set_minutes(60, emit=True)
        self.assertEqual(self.task()["estimate_min"], 60)
        self.assertEqual(self.page.estimate_note_label.get_text(), "≈ 3 pomodoros · ⚠ as subtarefas somam 55m")
        self.page.stepper.set_minutes(0, emit=True)
        self.assertIsNone(self.task()["estimate_min"])
        self.assertTrue(self.page.estimate_note_label.get_text().startswith("Sem previsão própria"))

    def test_done_check(self):
        self.page.done_check.set_active(True)
        self.assertEqual(self.task()["status"], "done")
        self.page.done_check.set_active(False)
        self.assertEqual(self.task()["status"], "todo")

    def test_notes_are_saved_after_a_pause_or_on_flush(self):
        buffer = self.page.notes_view.get_buffer()
        buffer.set_text("Pedir os custos para a Ana")
        self.assertIsNotNone(self.page._notes_source)                                     # salva depois de um tempo
        self.assertEqual(self.task()["notes"], "")
        self.page.flush()
        self.assertEqual(self.task()["notes"], "Pedir os custos para a Ana")
        self.assertIsNone(self.page._notes_source)

    def test_postponed_caption(self):
        self.repo.postpone_task(self.task_id, "2026-11-09")
        self.page.load(self.task_id)
        self.assertEqual(self.page.postponed_label.get_text(), "adiada 1 vez")


class TimeCardsTest(EditorTest):
    def test_real_card_and_manual_adjustment(self):
        with mock.patch.object(dialogs, "ask_text", return_value="+25"):
            self.page._on_adjust()
        self.assertEqual(self.repo.real_seconds(self.task_id), 25 * 60)
        self.assertEqual(self.page.real_value.get_text(), "25m")
        self.assertTrue(any("Ajuste manual" in t for t in labels(self.page.history_box)))
        with mock.patch.object(dialogs, "ask_text", return_value="-90"):
            self.page._on_adjust()
        self.assertEqual(self.repo.real_seconds(self.task_id), 25 * 60)                   # recusado: ficaria negativo
        self.assertIn("negativo", self.page.notice_label.get_text())
        with mock.patch.object(dialogs, "ask_text", return_value="abc"):
            self.page._on_adjust()
        self.assertIn("Não entendi o ajuste", self.page.notice_label.get_text())
        with mock.patch.object(dialogs, "ask_text", return_value=None):
            self.page._on_adjust()                                                        # cancelou: nada muda
        self.assertEqual(self.repo.real_seconds(self.task_id), 25 * 60)

    def test_live_real_follows_the_timer(self):
        self.controller.focus(self.task_id, self.data["charts"]["id"])
        self.controller.toggle_timer()
        self.tick(180)
        self.page.refresh_live()
        self.assertEqual(self.page.real_value.get_text(), "3m")
        charts_row = [r for r in self.rows() if r.sub["id"] == self.data["charts"]["id"]][0]
        self.assertEqual(charts_row.real_label.get_text(), "3m")

    def test_ai_card_with_estimator(self):
        self.controller.estimator = FakeEstimator()
        self.page.load(self.task_id)
        self.assertEqual((self.page.ai_value.get_text(), self.page.ai_note.get_text()), ("1h 42m", "Baseado em 6 relatórios"))
        self.assertTrue(self.page.ai_use.get_visible())
        self.assertTrue(self.page.ai_subs_button.get_visible())
        self.page.ai_use.clicked()
        self.assertEqual(self.task()["estimate_min"], 102)
        self.assertEqual(self.page.stepper.minutes, 102)                                  # campo recarregado
        self.assertFalse(self.page.ai_use.get_visible())

    def test_ai_subtasks_button(self):
        self.controller.estimator = FakeEstimator()
        self.page.load(self.task_id)
        self.page.ai_subs_button.clicked()
        self.assertEqual([r.title_entry.get_text() for r in self.rows()],
                         ["Levantar números", "Montar gráficos", "Parte um", "Parte dois"])


class SubtasksTest(EditorTest):
    def test_check_and_play(self):
        first = self.rows()[0]
        first.check.set_active(True)
        self.assertEqual(self.repo.get_subtask(self.data["numbers"]["id"])["done"], 1)
        self.rows()[1].play.clicked()
        self.assertEqual(self.controller.tracker.active_subtask_id, self.data["charts"]["id"])
        self.assertTrue(self.controller.timer.running)
        self.assertEqual(self.events, ["focus-started"])

    def test_rename_and_time_commit(self):
        row = self.rows()[0]
        row.title_entry.set_text("Levantar os números do mês")
        row.title_entry.activate()
        self.assertEqual(self.repo.get_subtask(self.data["numbers"]["id"])["title"], "Levantar os números do mês")
        row = self.rows()[0] if self.rows()[0].sub["id"] == self.data["numbers"]["id"] else self.rows()[1]
        row.time_entry.set_text("1h")
        row.time_entry.activate()
        self.assertEqual(self.repo.get_subtask(self.data["numbers"]["id"])["estimate_min"], 60)
        self.assertEqual(self.page.estimate_note_label.get_text(),            # 1h + 30m = o previsto (1h 30m)
                         "≈ 4 pomodoros · soma das subtarefas: 1h 30m ✓")
        row.time_entry.set_text("lixo")
        row.time_entry.activate()
        self.assertEqual(row.time_entry.get_text(), "1h")                                  # inválido volta ao salvo
        self.assertIn("Não entendi o tempo", self.page.notice_label.get_text())
        row.time_entry.set_text("")
        row.time_entry.activate()
        self.assertIsNone(self.repo.get_subtask(self.data["numbers"]["id"])["estimate_min"])

    def test_sum_note_updates_after_subtask_time_change(self):
        self.repo.update_task(self.task_id, estimate_min=55)
        self.page.load(self.task_id)
        self.assertTrue(self.page.estimate_note_label.get_text().endswith("✓"))
        row = self.rows()[1]
        row.time_entry.set_text("45")
        row.time_entry.activate()
        self.assertIn("⚠ as subtarefas somam 1h 10m", self.page.estimate_note_label.get_text())

    def test_draft_flow_keeps_adding(self):
        self.page.add_sub_button.clicked()
        draft = self.rows()[-1]
        self.assertIsNone(draft.sub)
        draft.title_entry.set_text("Revisar texto")
        draft.time_entry.set_text("35")
        draft.title_entry.activate()
        titles = [r.title_entry.get_text() for r in self.rows()]
        self.assertEqual(titles, ["Levantar números", "Montar gráficos", "Revisar texto", ""])    # nova linha pronta
        subs = self.repo.list_subtasks(self.task_id)
        self.assertEqual((subs[-1]["title"], subs[-1]["estimate_min"]), ("Revisar texto", 35))
        self.rows()[-1].title_entry.activate()                                                  # vazio: encerra
        self.assertEqual(len(self.rows()), 3)

    def test_draft_cancel_and_bad_time(self):
        self.page.start_draft()
        draft = self.rows()[-1]
        draft.title_entry.set_text("Algo")
        draft.time_entry.set_text("??")
        draft.title_entry.activate()
        self.assertEqual(len(self.repo.list_subtasks(self.task_id)), 2)                        # não gravou
        self.assertIn("Não entendi o tempo", self.page.notice_label.get_text())
        self.page.cancel_draft()
        self.assertEqual(len(self.rows()), 2)

    def test_enter_on_existing_row_opens_a_new_draft(self):
        self.rows()[0].title_entry.activate()
        self.assertIsNone(self.rows()[-1].sub)
        self.assertEqual(len(self.rows()), 3)

    def test_delete_with_confirmation(self):
        with mock.patch.object(dialogs, "confirm", return_value=False):
            self.rows()[0].get_children()[0].get_children()[-1].clicked()
        self.assertEqual(len(self.repo.list_subtasks(self.task_id)), 2)
        with mock.patch.object(dialogs, "confirm", return_value=True):
            self.page.on_delete_subtask(self.rows()[0])
        self.assertEqual([r.title_entry.get_text() for r in self.rows()], ["Montar gráficos"])

    def test_drag_and_drop_reorders(self):
        first, second = self.data["numbers"]["id"], self.data["charts"]["id"]
        self.page.on_subtask_dropped(first, second, after=True)
        self.assertEqual([s["id"] for s in self.repo.list_subtasks(self.task_id)], [second, first])
        self.assertEqual([r.sub["id"] for r in self.rows()], [second, first])
        self.page.on_subtask_dropped(first, second, after=True)                                  # já está depois: nada muda
        self.assertEqual([s["id"] for s in self.repo.list_subtasks(self.task_id)], [second, first])

    def test_active_subtask_row_is_highlighted(self):
        self.controller.focus(self.task_id, self.data["charts"]["id"])
        self.page.load(self.task_id)
        self.assertEqual(len(with_class(self.page.sub_rows_box, "sub-row-active")), 1)


class ActionsTest(EditorTest):
    def test_duplicate(self):
        self.page._on_duplicate()
        copies = [t for t in self.repo.list_tasks() if t["title"] == "Escrever relatório" and t["id"] != self.task_id]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["scheduled_for"], "2026-11-10")
        self.assertEqual(len(self.repo.list_subtasks(copies[0]["id"])), 2)
        self.assertIn("Cópia criada para amanhã", self.page.notice_label.get_text())
        self.assertTrue(self.page.notice_label.get_style_context().has_class("text-green-dark"))

    def test_delete(self):
        with mock.patch.object(dialogs, "confirm", return_value=False):
            self.page._on_delete()
        self.assertIsNotNone(self.task())
        with mock.patch.object(dialogs, "confirm", return_value=True):
            self.page._on_delete()
        self.assertIsNone(self.task())
        self.assertEqual(self.events, ["back"])

    def test_focus(self):
        self.page._on_focus()
        self.assertEqual(self.controller.tracker.active_task_id, self.task_id)
        self.assertTrue(self.controller.timer.running)
        self.assertEqual(self.events, ["focus-started"])

    def test_back_saves_pending_edits_first(self):
        self.page.title_entry.set_text("Título pendente")
        self.page.go_back()
        self.assertEqual(self.task()["title"], "Título pendente")
        self.assertEqual(self.events, ["back"])

    def test_loading_another_task_saves_the_previous_one(self):
        self.page.title_entry.set_text("Meu relatório")
        self.page.load(self.data["laundry"]["id"])
        self.assertEqual(self.task()["title"], "Meu relatório")
        self.assertEqual(self.page.title_entry.get_text(), "Lavar roupa")

    def test_list_click_opens_other_task_only(self):
        click = SimpleNamespace(button=1)
        self.page._on_list_clicked(self.data["laundry"]["id"], click)
        self.page._on_list_clicked(self.task_id, click)
        self.assertEqual(self.events, [("open", self.data["laundry"]["id"])])


class HistoryTest(EditorTest):
    def test_sessions_and_distractions(self):
        self.controller.focus(self.task_id, self.data["numbers"]["id"])
        self.controller.toggle_timer()
        self.tick(300)
        self.controller.tracker.add_distraction("ligar para o banco")
        self.controller.skip_phase()                                                           # interrompe o foco
        self.page.load(self.task_id)
        texts = labels(self.page.history_box)
        self.assertTrue(any("Levantar números · 5m  ⚠ interrompido" in t for t in texts), texts)
        self.assertIn("✎ ligar para o banco", texts)
        self.assertEqual(len(with_class(self.page.history_box, "text-danger")), 1)

    def test_empty_history(self):
        self.assertIn("Nenhuma sessão ainda", labels(self.page.history_box)[0])


class ExternalChangesTest(EditorTest):
    def test_external_change_reloads_when_not_typing(self):
        self.controller.rename_task(self.task_id, "Renomeada de fora")
        self.page.on_data("data")
        self.assertEqual(self.page.title_entry.get_text(), "Renomeada de fora")

    def test_own_changes_do_not_rebuild_the_fields(self):
        entry = self.page.title_entry
        entry.set_text("Digitando…")
        self.page._own = True
        self.page.on_data("data")
        self.page._own = False
        self.assertEqual(entry.get_text(), "Digitando…")

    def test_typing_inside_keeps_the_entry_but_refreshes_the_numbers(self):
        entry = self.page.title_entry
        entry.set_text("Digitando…")
        with mock.patch.object(self.page, "_typing_here", return_value=True):
            self.controller.adjust_real_time(self.task_id, 12)
            self.page.on_data("data")
        self.assertEqual(entry.get_text(), "Digitando…")
        self.assertEqual(self.page.real_value.get_text(), "12m")

    def test_task_deleted_elsewhere_goes_back(self):
        self.controller.delete_task(self.task_id)
        self.page.on_data("data")
        self.assertEqual(self.events, ["back"])


class WindowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)
        self.window = MainWindow(self.controller)
        self.addCleanup(self.window.destroy)

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def test_open_editor_and_come_back(self):
        self.window.open_task_editor(self.data["report"]["id"])
        self.assertEqual(self.window.stack.get_visible_child_name(), "task")
        self.assertEqual(self.window.sidebar.page, "today")
        self.assertEqual(self.window.editor.title_entry.get_text(), "Escrever relatório")
        self.window.editor.go_back()
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")

    def test_focus_from_editor_returns_to_today(self):
        self.window.open_task_editor(self.data["laundry"]["id"])
        self.window.editor._on_focus()
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")
        self.assertTrue(self.controller.timer.running)

    def test_switching_task_in_editor_list(self):
        self.window.open_task_editor(self.data["report"]["id"])
        self.window.editor._on_list_clicked(self.data["laundry"]["id"], SimpleNamespace(button=1))
        self.assertEqual(self.window.editor.task_id, self.data["laundry"]["id"])
        self.assertEqual(self.window.editor.title_entry.get_text(), "Lavar roupa")

    def test_unknown_task_does_not_open_editor(self):
        self.window.open_task_editor("nao-existe")
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")

    def test_new_task_button_and_group_default(self):
        with mock.patch.object(new_task, "run_new_task_dialog", return_value=None) as run:
            self.window.today.emit("new-task")
            run.assert_called_once_with(self.window, self.controller, group_id=None)
            self.window.sidebar._group_buttons[self.data["home"]["id"]].set_active(True)
            self.window.today.emit("new-task")
            self.assertEqual(run.call_args.kwargs["group_id"], self.data["home"]["id"])

    def test_double_click_and_menu_open_the_editor(self):
        task_list = self.window.today.task_list
        view = self.controller.today_view()
        task = next(t for t in view.visible_tasks if t.title == "Lavar roupa")
        task_list._on_task_click(task, SimpleNamespace(time=10_000))
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")                 # 1 clique: só foca
        self.assertEqual(self.controller.tracker.active_task_id, task.id)
        task_list._on_task_click(task, SimpleNamespace(time=10_250))                          # 2º clique em < 400 ms
        self.assertEqual(self.window.stack.get_visible_child_name(), "task")
        self.window.show_page("today")
        task_list._on_task_click(task, SimpleNamespace(time=11_000))
        task_list._on_task_click(task, SimpleNamespace(time=12_000))                          # lento: não é duplo
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")
        with mock.patch.object(Gtk.Menu, "popup_at_pointer"):
            menu = task_list._task_menu(task, SimpleNamespace(button=3))
        edit = next(i for i in menu.get_children() if isinstance(i, Gtk.MenuItem) and i.get_label() == "Editar…")
        edit.activate()
        self.assertEqual(self.window.stack.get_visible_child_name(), "task")

    def test_events_reach_the_open_editor(self):
        self.window.open_task_editor(self.data["report"]["id"])
        with mock.patch.object(self.window, "get_visible", return_value=True):
            self.controller.rename_task(self.data["report"]["id"], "Mudou por outro caminho")
            self.assertEqual(self.window.editor.title_entry.get_text(), "Mudou por outro caminho")
            self.controller.focus(self.data["report"]["id"], self.data["charts"]["id"])
            self.controller.toggle_timer()
            for _ in range(120):
                self.controller.timer.tick()
            self.assertEqual(self.window.editor.real_value.get_text(), "2m")

    def test_deleting_from_editor_returns_and_refreshes(self):
        self.window.open_task_editor(self.data["laundry"]["id"])
        with mock.patch.object(dialogs, "confirm", return_value=True):
            self.window.editor._on_delete()
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")
        self.assertNotIn("Lavar roupa", labels(self.window.today.task_list))


if __name__ == "__main__":
    unittest.main()
