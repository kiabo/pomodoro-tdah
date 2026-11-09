import tempfile
import unittest
from datetime import date
from unittest import mock

from tests_gtk._support import make_controller, populate, require_gtk, with_class

require_gtk()

from gi.repository import Gdk, Gtk  # noqa: E402

from pomodoro.ui.dialogs.new_task import NewTaskDialog, run_new_task_dialog  # noqa: E402


class FakeEstimator:
    def suggest_estimate(self, repo, title, group_id, user_estimate_min, **_kwargs):
        if user_estimate_min == 45:
            return {"minutes": 80, "note": f"Para “{title}”"}
        return None

    def suggest_subtasks(self, repo, title, group_id):
        return [("Definir tópicos", 20), ("Criar slides", 40)]


class DialogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)
        self.dialog = NewTaskDialog(None, self.controller)
        self.addCleanup(self.dialog.destroy)
        self.responses = []
        self.dialog.connect("response", lambda _d, response: self.responses.append(response))

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def type_title(self, text):
        self.dialog.title_entry.set_text(text)


class DefaultsTest(DialogTest):
    def test_initial_state(self):
        d = self.dialog
        self.assertEqual(d.group_id, self.controller.repo.default_group_id())
        self.assertEqual((d.date_picker.date, d.repeat_select.value), (date(2026, 11, 9), None))
        self.assertIsNone(d.estimate_min)
        self.assertEqual(d.pomodoro_label.get_text(), "")
        self.assertFalse(d.ai_card.get_visible())
        self.assertFalse(d.error_label.get_visible())
        self.assertFalse(d.focus_check.get_active())

    def test_preselected_group_and_day(self):
        dialog = NewTaskDialog(None, self.controller, group_id=self.data["home"]["id"], day=None)
        self.addCleanup(dialog.destroy)
        self.assertEqual((dialog.group_id, dialog.date_picker.date), (self.data["home"]["id"], None))
        unknown = NewTaskDialog(None, self.controller, group_id="nao-existe")
        self.addCleanup(unknown.destroy)
        self.assertEqual(unknown.group_id, self.controller.repo.default_group_id())


class TimeTest(DialogTest):
    def test_chip_sets_estimate_and_pomodoros(self):
        self.dialog.chips._buttons[45].set_active(True)
        self.assertEqual(self.dialog.estimate_min, 45)
        self.assertEqual(self.dialog.pomodoro_label.get_text(), "≈ 2 pomodoros de 25 min")
        self.dialog.chips._buttons[15].set_active(True)
        self.assertEqual(self.dialog.pomodoro_label.get_text(), "≈ 1 pomodoro de 25 min")

    def test_typing_clears_the_chips_and_chip_clears_the_text(self):
        d = self.dialog
        d.chips._buttons[45].set_active(True)
        d.time_entry.set_text("1h20")
        self.assertEqual((d.chips.value, d.estimate_min), (None, 80))
        self.assertEqual(d.pomodoro_label.get_text(), "≈ 4 pomodoros de 25 min")
        d.chips._buttons[60].set_active(True)
        self.assertEqual((d.time_entry.get_text(), d.estimate_min), ("", 60))

    def test_invalid_text(self):
        d = self.dialog
        d.time_entry.set_text("xyz")
        self.assertFalse(d.estimate_text_valid)
        self.assertIsNone(d.estimate_min)
        self.assertTrue(d.time_entry.get_style_context().has_class("entry-error"))
        d.time_entry.set_text("30")
        self.assertFalse(d.time_entry.get_style_context().has_class("entry-error"))

    def test_set_estimate_picks_chip_or_text(self):
        self.dialog.set_estimate(90)
        self.assertEqual((self.dialog.chips.value, self.dialog.time_entry.get_text()), (90, ""))
        self.dialog.set_estimate(80)
        self.assertEqual((self.dialog.chips.value, self.dialog.time_entry.get_text(), self.dialog.estimate_min),
                         (None, "1h 20m", 80))
        self.dialog.set_estimate(None)
        self.assertIsNone(self.dialog.estimate_min)

    def test_group_that_requires_estimate(self):
        strict = self.controller.repo.create_group("Rígido", require_estimate=True)
        dialog = NewTaskDialog(None, self.controller, group_id=strict["id"])
        self.addCleanup(dialog.destroy)
        self.assertTrue(dialog.require_label.get_visible())
        dialog.set_estimate(30)
        self.assertFalse(dialog.require_label.get_visible())


class DateAndRepeatTest(DialogTest):
    def test_repeat_follows_the_chosen_day(self):
        d = self.dialog
        self.assertEqual([r for r, _t in d.repeat_select.items], [None, "daily", "weekdays", "weekly:0", "monthly:9"])
        d.repeat_select.set_value("weekly:0")
        d.date_picker.set_date(date(2026, 11, 12), emit=True)             # quinta, dia 12
        self.assertEqual(d.repeat_select.value, "weekly:3")
        d.repeat_select.set_value("monthly:12")
        d.date_picker.set_date(date(2026, 11, 20), emit=True)
        self.assertEqual(d.repeat_select.value, "monthly:20")
        d.repeat_select.set_value("daily")
        d.date_picker.set_date(date(2026, 11, 21), emit=True)
        self.assertEqual(d.repeat_select.value, "daily")                   # regras fixas não mudam
        d.date_picker.set_date(None, emit=True)                           # sem data: opções do dia de hoje
        self.assertEqual(d.repeat_select.value, "daily")


class SubtasksTest(DialogTest):
    def test_rows_and_sum_warning(self):
        d = self.dialog
        d.set_estimate(45)
        a = d.add_subtask_row(title="Definir tópicos", minutes=20, focus=False)
        d.add_subtask_row(title="Criar slides", minutes=40, focus=False)
        self.assertEqual(d.sum_label.get_text(), "Soma 1h · diferente do previsto (45m)  ⚠")
        self.assertTrue(d.sum_label.get_style_context().has_class("text-danger"))
        d.remove_subtask_row(a)
        self.assertEqual(d.sum_label.get_text(), "Soma 40m · diferente do previsto (45m)  ⚠")
        d.set_estimate(40)
        self.assertEqual(d.sum_label.get_text(), "Soma 40m")
        self.assertTrue(d.sum_label.get_style_context().has_class("muted"))
        d.remove_subtask_row(d._rows[0])
        self.assertEqual(d.sum_label.get_text(), "")

    def test_enter_adds_the_next_row_after_the_current(self):
        d = self.dialog
        first = d.add_subtask_row(title="Um", focus=False)
        d.add_subtask_row(title="Três", focus=False)
        first.title_entry.activate()
        self.assertEqual(len(d._rows), 3)
        self.assertEqual(d._rows.index(first), 0)
        self.assertEqual(d._rows[1].title_entry.get_text(), "")
        self.assertEqual(d.sub_box.get_children()[1], d._rows[1])

    def test_blank_rows_are_ignored_and_bad_time_is_flagged(self):
        d = self.dialog
        d.add_subtask_row(title="Com título", minutes=15, focus=False)
        d.add_subtask_row(focus=False)
        bad = d.add_subtask_row(title="Tempo ruim", focus=False)
        bad.time_entry.set_text("xx")
        values = d.subtask_values()
        self.assertEqual([(t, m, ok) for t, m, ok in values], [("Com título", 15, True), ("Tempo ruim", None, False)])


class AiTest(DialogTest):
    def test_no_estimator_no_card_and_no_subtask_link(self):
        self.controller.estimator = None
        self.type_title("Preparar apresentação")
        self.dialog.set_estimate(45)
        self.dialog._refresh_suggestion()
        self.assertFalse(self.dialog.ai_card.get_visible())
        self.assertFalse(self.dialog.ai_subs_link.get_visible())

    def test_suggestion_use_and_keep(self):
        self.controller.estimator = FakeEstimator()
        d = self.dialog
        self.type_title("Preparar apresentação")
        d.set_estimate(45)
        d._refresh_suggestion()
        self.assertTrue(d.ai_card.get_visible())
        self.assertEqual((d.ai_title.get_text(), d.ai_use.get_label(), d.ai_keep.get_label()),
                         ("✦ A IA sugere 1h 20m", "Usar 1h 20m", "Manter 45m"))
        self.assertEqual(d.ai_note.get_text(), "Para “Preparar apresentação”")
        d.ai_use.clicked()
        self.assertEqual(d.estimate_min, 80)
        d._refresh_suggestion()
        self.assertFalse(d.ai_card.get_visible())                         # já está no valor sugerido
        d.set_estimate(45)
        d._refresh_suggestion()
        d.ai_keep.clicked()
        self.assertFalse(d.ai_card.get_visible())
        d._refresh_suggestion()
        self.assertFalse(d.ai_card.get_visible())                         # dispensada: não volta para o mesmo caso

    def test_ai_subtasks(self):
        self.controller.estimator = FakeEstimator()
        d = self.dialog
        d.add_subtask_row(title="Antiga", focus=False)
        self.type_title("Preparar apresentação")
        d._refresh_suggestion()
        self.assertTrue(d.ai_subs_link.get_visible())
        d.ai_subs_link.clicked()
        self.assertEqual([(t, m) for t, m, _ok in d.subtask_values()], [("Definir tópicos", 20), ("Criar slides", 40)])

    def test_suggestion_is_scheduled_not_immediate(self):
        self.controller.estimator = FakeEstimator()
        self.type_title("Qualquer")
        self.assertIsNotNone(self.dialog._suggestion_source)


class SubmitTest(DialogTest):
    def test_empty_title_and_bad_time_show_errors(self):
        d = self.dialog
        self.assertFalse(d.submit())
        self.assertEqual(d.error_label.get_text(), "Dê um nome para a tarefa.")
        self.assertTrue(d.error_label.get_visible())
        self.type_title("Algo")
        d.time_entry.set_text("xyz")
        self.assertFalse(d.submit())
        self.assertIn("Não entendi o tempo previsto", d.error_label.get_text())
        d.time_entry.set_text("")
        sub = d.add_subtask_row(title="Passo", focus=False)
        sub.time_entry.set_text("??")
        self.assertFalse(d.submit())
        self.assertIn("subtarefa 1", d.error_label.get_text())
        self.assertEqual(self.responses, [])
        self.assertIsNone(d.created)

    def test_creates_everything(self):
        d = self.dialog
        self.type_title("  Preparar apresentação ")
        d.group_select.set_value(self.data["work"]["id"])
        d.date_picker.set_date(date(2026, 11, 12), emit=True)
        d.repeat_select.set_value("weekly:3")
        d.set_estimate(80)
        d.add_subtask_row(title="Definir tópicos", minutes=20, focus=False)
        d.add_subtask_row(title="Criar slides", minutes=60, focus=False)
        d.add_subtask_row(focus=False)                                      # linha vazia: ignorada
        self.assertTrue(d.submit())
        self.assertEqual(self.responses, [Gtk.ResponseType.OK])
        task = self.controller.repo.get_task(d.created["id"])
        self.assertEqual((task["title"], task["group_id"], task["scheduled_for"], task["repeat_rule"],
                          task["estimate_min"]),
                         ("Preparar apresentação", self.data["work"]["id"], "2026-11-12", "weekly:3", 80))
        subs = self.controller.repo.list_subtasks(task["id"])
        self.assertEqual([(s["title"], s["estimate_min"]) for s in subs], [("Definir tópicos", 20), ("Criar slides", 60)])
        self.assertFalse(self.controller.timer.running)

    def test_no_date_and_focus_option(self):
        d = self.dialog
        self.type_title("Começar já")
        d.date_picker.set_date(None, emit=True)
        d.focus_check.set_active(True)
        self.assertTrue(d.submit())
        task = self.controller.repo.get_task(d.created["id"])
        self.assertIsNone(task["scheduled_for"])
        self.assertEqual(self.controller.tracker.active_task_id, task["id"])
        self.assertTrue(self.controller.timer.running)

    def test_group_rule_error_is_shown_inline(self):
        strict = self.controller.repo.create_group("Rígido", require_estimate=True)
        d = self.dialog
        d.group_select.set_items([(strict["id"], "Rígido")], strict["id"])
        self.type_title("Sem previsão")
        self.assertFalse(d.submit())
        self.assertEqual(d.error_label.get_text(), "este grupo exige a previsão de tempo")
        self.assertEqual(self.responses, [])

    def test_ctrl_enter_submits(self):
        d = self.dialog
        self.type_title("Atalho")
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Return
        event.state = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(d._on_key(d, event))
        self.assertIsNotNone(d.created)
        event.state = 0
        event.keyval = Gdk.KEY_Return
        self.assertFalse(d._on_key(d, event))

    def test_run_helper_returns_created_task_or_none(self):
        def fake_run(self_):
            self_.title_entry.set_text("Pelo helper")
            self_.submit()

        with mock.patch.object(NewTaskDialog, "run", fake_run):
            created = run_new_task_dialog(None, self.controller)
        self.assertEqual(created["title"], "Pelo helper")
        with mock.patch.object(NewTaskDialog, "run", lambda self_: None):
            self.assertIsNone(run_new_task_dialog(None, self.controller))

    def test_primary_button_exists(self):
        primary = with_class(self.dialog.body, "btn-primary")
        self.assertEqual([b.get_label() for b in primary], ["Criar tarefa   Ctrl+Enter"])


if __name__ == "__main__":
    unittest.main()
