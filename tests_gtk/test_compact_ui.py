import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from tests_gtk._support import click_event, find, labels, make_controller, populate, require_gtk

require_gtk()

from gi.repository import Gdk, Gtk  # noqa: E402

from pomodoro.timer import Phase  # noqa: E402
from pomodoro.ui import compact_window  # noqa: E402
from pomodoro.ui.compact_window import CompactWindow  # noqa: E402
from pomodoro.ui.main_window import MainWindow  # noqa: E402


class CompactTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)
        self.repo = self.controller.repo
        self.calls = []
        self.window = CompactWindow(
            self.controller, on_expand=lambda: self.calls.append("expand"),
            on_close=lambda: self.calls.append("close"), on_adjust=lambda task_id: self.calls.append(("adjust", task_id)))
        self.addCleanup(self.window.destroy)
        self.visible = mock.patch.object(self.window, "get_visible", return_value=True)
        self.visible.start()
        self.addCleanup(self.visible.stop)

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def tick(self, n):
        for _ in range(n):
            self.controller.timer.tick()

    def focus_report(self, sub="charts"):
        self.controller.focus(self.data["report"]["id"], self.data[sub]["id"] if sub else None)

    @property
    def card(self):
        return self.window.focus_card


class FocusCardTest(CompactTest):
    def test_idle_state(self):
        self.window.refresh()
        self.assertEqual(self.window.view_name(), "focus")
        self.assertEqual((self.card.eyebrow.get_text(), self.card.time.get_text(), self.card.title.get_text()),
                         ("PRONTO · 1 DE 4", "25:00", "Foco livre"))
        self.assertTrue(self.card.next.get_text().startswith("Próximo: pausa curta de 5 min às "))
        self.assertFalse(self.card.parent.get_visible())
        self.assertFalse(self.card.done.get_sensitive())
        self.assertEqual(self.card.play.get_label(), "▶")

    def test_running_with_a_subtask(self):
        self.focus_report()
        self.controller.toggle_timer()
        self.tick(180)
        self.assertEqual((self.card.eyebrow.get_text(), self.card.time.get_text()), ("FOCO · 1 DE 4", "22:00"))
        self.assertEqual((self.card.title.get_text(), self.card.parent.get_text()), ("Montar gráficos", "Escrever relatório"))
        self.assertTrue(self.card.parent.get_visible() and self.card.done.get_sensitive())
        self.assertEqual(self.card.play.get_label(), "❚❚")
        self.assertAlmostEqual(self.card.bar.get_fraction(), 180 / 1500)
        self.assertEqual(self.card.dot.color, "#F26B4E")

    def test_estimate_line_only_when_enabled_and_known(self):
        self.focus_report()
        self.controller.toggle_timer()
        self.tick(180)
        self.assertFalse(self.card.estimate.get_visible())                       # fora dos campos padrão
        self.controller.apply_settings({"compact_fields": ["remaining", "estimate_vs_real"]})
        self.assertEqual(self.card.estimate.get_text(), "Real 3m de 1h 30m previstos")
        self.assertTrue(self.card.estimate.get_visible())
        self.controller.focus(None)
        self.assertFalse(self.card.estimate.get_visible())

    def test_fields_visibility_follows_settings(self):
        self.focus_report()
        self.controller.apply_settings({"compact_fields": ["remaining"]})
        self.assertTrue(self.card.time.get_visible())
        for hidden in (self.card.title, self.card.parent, self.card.bar, self.card.next):
            self.assertFalse(hidden.get_visible())
        self.controller.apply_settings({"compact_fields": ["current_task", "progress", "next_break"]})
        self.assertFalse(self.card.time.get_visible())
        for shown in (self.card.title, self.card.bar, self.card.next):
            self.assertTrue(shown.get_visible())

    def test_overtime_shows_extra_time(self):
        self.focus_report()
        self.controller.toggle_timer()
        self.tick(25 * 60 + 70)
        self.assertEqual((self.card.eyebrow.get_text(), self.card.time.get_text()), ("TEMPO EXTRA · 1 DE 4", "+01:10"))
        self.assertEqual(self.card.bar.get_fraction(), 1.0)

    def test_buttons(self):
        self.focus_report()
        self.card.play.clicked()
        self.assertTrue(self.controller.timer.running)
        self.card.play.clicked()
        self.assertFalse(self.controller.timer.running)
        self.card.done.clicked()                                                 # conclui "Montar gráficos"
        self.assertEqual(self.repo.get_subtask(self.data["charts"]["id"])["done"], 1)
        self.card.skip.clicked()
        self.assertEqual((self.controller.timer.phase, self.window.view_name()), (Phase.SHORT_BREAK, "break"))

    def test_header_buttons_call_the_host(self):
        icons = [b for b in find(self.card, lambda w: isinstance(w, Gtk.Button)) if b.get_label() in ("⤢", "✕")]
        for button in icons:
            button.clicked()
        self.assertEqual(self.calls, ["expand", "close"])


class ExpandedTest(CompactTest):
    def test_subtasks_and_focus_by_click(self):
        self.focus_report()
        self.card.set_expanded(True)
        texts = labels(self.card.subtasks_box)
        self.assertEqual(texts, ["☐  Levantar números", "▸  Montar gráficos  · agora"])
        row = find(self.card.subtasks_box, lambda w: isinstance(w, Gtk.EventBox) and "☐  Levantar números" in labels(w))[0]
        row.emit("button-press-event", click_event(1))
        self.assertEqual(self.controller.tracker.active_subtask_id, self.data["numbers"]["id"])
        self.assertIn("▸  Levantar números  · agora", labels(self.card.subtasks_box))        # refeito pelo evento

    def test_done_subtasks_are_marked(self):
        self.controller.set_subtask_done(self.data["numbers"]["id"], True)
        self.focus_report("charts")
        self.card.set_expanded(True)
        self.assertIn("☑  Levantar números", labels(self.card.subtasks_box))

    def test_no_task_means_only_the_capture(self):
        self.card.set_expanded(True)
        self.assertFalse(self.card.subtasks_box.get_visible())

    def test_capture_distraction(self):
        self.focus_report()
        self.controller.toggle_timer()
        self.tick(10)
        self.card.set_expanded(True)
        self.card.capture.set_text("  ligar para o banco ")
        self.card.capture.activate()
        items = self.repo.list_distractions(task_id=self.data["report"]["id"])
        self.assertEqual([i["text"] for i in items], ["ligar para o banco"])
        self.assertEqual(self.card.capture.get_text(), "")
        self.assertEqual(self.card.feedback.get_text(), "✓ Anotado — volte ao foco")
        self.assertTrue(self.card.feedback.get_visible())
        self.card.capture.activate()                                                  # vazio: nada
        self.assertEqual(len(self.repo.list_distractions()), 1)

    def test_escape_collapses_and_clears(self):
        self.card.set_expanded(True)
        self.card.capture.set_text("meio digitado")
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        self.assertTrue(self.card._on_capture_key(self.card.capture, event))
        self.assertFalse(self.card.expanded)
        self.assertEqual(self.card.capture.get_text(), "")

    def test_hover_opens_only_on_the_focus_card_and_not_while_typing(self):
        self.window._apply_hover(True)
        self.assertTrue(self.card.expanded)
        with mock.patch.object(self.card.capture, "has_focus", return_value=True):
            self.window._apply_hover(False)
        self.assertTrue(self.card.expanded)                                           # digitando: continua aberto
        self.window._apply_hover(False)
        self.assertFalse(self.card.expanded)
        self.controller.skip_phase()
        self.window._apply_hover(True)
        self.assertFalse(self.card.expanded)                                          # na pausa não abre

    def test_enter_and_leave_events(self):
        inside = SimpleNamespace(detail=Gdk.NotifyType.ANCESTOR)
        child = SimpleNamespace(detail=Gdk.NotifyType.INFERIOR)
        self.window._on_enter(None, inside)
        self.assertEqual(self.window.frame.get_opacity(), 1.0)
        self.assertIsNotNone(self.window._hover_source)
        self.window._on_leave(None, child)                                            # indo para um filho: ignora
        self.assertEqual(self.window.frame.get_opacity(), 1.0)
        self.window._on_leave(None, inside)
        self.assertAlmostEqual(self.window.frame.get_opacity(), 0.7, places=2)


class BreakAndMiniTest(CompactTest):
    def test_break_card(self):
        self.focus_report("numbers")
        self.controller.skip_phase()
        self.assertEqual(self.window.view_name(), "break")
        card = self.window.break_card
        self.assertEqual((card.eyebrow.get_text(), card.time.get_text()), ("PAUSA CURTA · PRONTA", "05:00"))
        self.assertEqual(card.next.get_text(), "A seguir: Montar gráficos · 30m")
        card.plus.clicked()
        self.assertEqual(card.time.get_text(), "06:00")
        card.skip.clicked()
        self.assertEqual((self.window.view_name(), self.controller.timer.phase), ("focus", Phase.WORK))

    def test_break_card_without_anything_next(self):
        for task in self.repo.list_tasks():
            self.repo.set_task_status(task["id"], "done")
        self.controller.skip_phase()
        self.assertEqual(self.window.break_card.next.get_text(), "A seguir: foco livre")

    def test_mini_pill(self):
        self.focus_report()
        self.window.toggle_mini()
        self.assertEqual(self.window.view_name(), "mini")
        pill = self.window.mini_pill
        self.assertEqual((pill.time.get_text(), pill.title.get_text(), pill.toggle.get_label()),
                         ("25:00", "Montar gráficos", "▶"))
        pill.toggle.clicked()
        self.tick(60)
        self.assertEqual((pill.time.get_text(), pill.toggle.get_label()), ("24:00", "❚❚"))
        self.assertTrue(pill.box.get_style_context().has_class("compact-dark"))
        self.controller.skip_phase()
        self.assertEqual(pill.title.get_text(), "Pausa curta")
        self.assertTrue(pill.box.get_style_context().has_class("compact-break"))
        self.assertEqual(pill.dot.color, "#6EE7B7")
        self.window.toggle_mini()
        self.assertEqual(self.window.view_name(), "break")

    def test_window_interactions(self):
        press = lambda button, time: SimpleNamespace(button=button, time=time, x_root=10, y_root=20)  # noqa: E731
        with mock.patch.object(self.window, "begin_move_drag") as drag:
            self.assertTrue(self.window._on_press(None, press(1, 10_000)))
            drag.assert_called_once_with(1, 10, 20, 10_000)
            self.assertFalse(self.window.mini)
            self.assertTrue(self.window._on_press(None, press(1, 10_200)))            # duplo clique
            drag.assert_called_once()
            self.assertTrue(self.window.mini)
            self.window._on_press(None, press(1, 12_000))                             # devagar: é arrastar de novo
            self.assertEqual(drag.call_count, 2)
            self.assertFalse(self.window._on_press(None, press(2, 13_000)))

    def test_context_menu(self):
        with mock.patch.object(Gtk.Menu, "popup_at_pointer"):
            menu = self.window._popup_menu(SimpleNamespace(button=3))
        items = {i.get_label(): i for i in menu.get_children() if isinstance(i, Gtk.MenuItem) and i.get_label()}
        self.assertEqual(list(items), ["Mini (pílula)", "Voltar ao app", "Sempre por cima", "Esconder (continua na bandeja)"])
        items["Mini (pílula)"].activate()
        self.assertTrue(self.window.mini)
        items["Voltar ao app"].activate()
        items["Esconder (continua na bandeja)"].activate()
        self.assertEqual(self.calls, ["expand", "close"])
        self.assertTrue(items["Sempre por cima"].get_active())
        items["Sempre por cima"].set_active(False)
        self.assertFalse(self.controller.settings["compact_always_on_top"])
        with mock.patch.object(Gtk.Menu, "popup_at_pointer"):
            again = self.window._popup_menu(SimpleNamespace(button=3))
        self.assertIn("Expandir", [i.get_label() for i in again.get_children() if isinstance(i, Gtk.MenuItem)])

    def test_close_without_callback_just_hides(self):
        window = CompactWindow(self.controller)
        self.addCleanup(window.destroy)
        with mock.patch.object(window, "hide") as hide:
            window.close_compact()
        hide.assert_called_once()


class AlertTest(CompactTest):
    def trigger_alert(self):
        self.repo.update_task(self.data["report"]["id"], estimate_min=1)
        self.controller.focus(self.data["report"]["id"])
        self.controller.toggle_timer()
        self.tick(90)

    def test_alert_card_and_priority(self):
        self.trigger_alert()
        self.assertEqual(self.window.view_name(), "alert")
        self.assertEqual(self.window.stack.get_visible_child_name(), "alert")
        self.assertEqual(self.window.alert_card.text.get_text(),
                         "Você está há 2m em “Escrever relatório” (previsto 1m). "
                         "Tudo bem continuar — só confira se ainda é a prioridade.")
        self.window.toggle_mini()
        self.assertEqual(self.window.view_name(), "alert")                            # o alerta vence a pílula
        self.assertEqual(self.window.frame.get_opacity(), 1.0)

    def test_plus_15_minutes(self):
        self.trigger_alert()
        self.window.alert_card.get_children()[-1].get_children()[1].clicked()
        self.assertEqual(self.repo.get_task(self.data["report"]["id"])["estimate_min"], 16)
        self.assertEqual(self.window.view_name(), "focus")
        self.assertIsNone(self.window.alert)

    def test_take_a_break(self):
        self.trigger_alert()
        self.window.alert_card.get_children()[-1].get_children()[0].clicked()
        self.assertEqual((self.controller.timer.phase, self.window.view_name()), (Phase.SHORT_BREAK, "break"))

    def test_adjust_opens_the_task(self):
        self.trigger_alert()
        self.window.alert_card.get_children()[-1].get_children()[2].clicked()
        self.assertEqual(self.calls, [("adjust", self.data["report"]["id"])])
        self.assertIsNone(self.window.alert)

    def test_dismiss_and_phase_change_clear_the_alert(self):
        self.trigger_alert()
        self.window.dismiss_alert()
        self.assertEqual(self.window.view_name(), "focus")
        self.controller.last_alert = {"task_id": None, "title": "x", "real_seconds": 60, "estimate_seconds": 30}
        self.window.alert = dict(self.controller.last_alert)
        self.controller.skip_phase()
        self.assertIsNone(self.window.alert)

    def test_alert_ignored_while_hidden(self):
        self.visible.stop()
        self.trigger_alert()
        self.assertIsNone(self.window.alert)
        self.visible.start()


class RatingTest(CompactTest):
    def finish_pomodoro(self, sub="charts"):
        self.focus_report(sub)
        self.controller.toggle_timer()
        self.tick(25 * 60)
        self.controller.skip_phase()

    def test_rating_card(self):
        self.finish_pomodoro()
        self.assertEqual(self.window.view_name(), "rating")
        card = self.window.rating_card
        self.assertEqual(card.header.get_text(), "✓ POMODORO 2 CONCLUÍDO · +25 MIN NO REAL")        # o exemplo já tem 1 de hoje
        self.assertEqual(card.question.get_text(), "Como foi “Escrever relatório”?")
        self.assertTrue(card.choices_row.get_visible())
        self.assertEqual(card.primary.get_label(), "Continuar")                       # a pausa já começou sozinha
        self.assertEqual(self.window.frame.get_opacity(), 1.0)

    def test_choosing_saves_the_difficulty_once(self):
        self.finish_pomodoro()
        card = self.window.rating_card
        card.choices["hard"].set_active(True)
        self.assertEqual(self.repo.get_task(self.data["report"]["id"])["difficulty"], "hard")
        card.choices["easy"].set_active(True)
        self.assertEqual(self.repo.get_task(self.data["report"]["id"])["difficulty"], "easy")
        self.assertEqual(self.window.rating["difficulty"], "easy")
        self.assertEqual([k for k, c in card.choices.items() if c.get_active()], ["easy"])

    def test_continue_goes_to_the_break(self):
        self.finish_pomodoro()
        self.window.rating_card.primary.clicked()
        self.assertEqual((self.window.view_name(), self.controller.timer.phase), ("break", Phase.SHORT_BREAK))
        self.assertTrue(self.controller.timer.running)
        self.assertIsNone(self.window.rating)

    def test_manual_break_start(self):
        self.controller.apply_settings({"auto_start_breaks": False, "count_overtime": False})
        self.focus_report()
        self.controller.toggle_timer()
        self.tick(25 * 60)                                                              # o foco termina sozinho
        card = self.window.rating_card
        self.assertEqual(card.primary.get_label(), "Iniciar pausa de 5 min")
        self.assertFalse(self.controller.timer.running)
        card.primary.clicked()
        self.assertTrue(self.controller.timer.running)
        self.assertEqual(self.window.view_name(), "break")

    def test_free_focus_has_no_choices(self):
        self.controller.toggle_timer()
        self.tick(25 * 60)
        self.controller.skip_phase()
        card = self.window.rating_card
        self.assertEqual((self.window.view_name(), card.question.get_text()), ("rating", "Como foi este foco?"))
        self.assertFalse(card.choices_row.get_visible())

    def test_disabled_or_hidden_or_cut_short_means_no_rating(self):
        self.controller.apply_settings({"ask_difficulty": False})
        self.finish_pomodoro()
        self.assertNotEqual(self.window.view_name(), "rating")
        self.controller.apply_settings({"ask_difficulty": True})
        self.controller.skip_phase()
        self.controller.toggle_timer()
        self.tick(300)
        self.controller.skip_phase()                                                    # cortado antes do fim
        self.assertNotEqual(self.window.view_name(), "rating")

    def test_timeout_dismisses(self):
        self.finish_pomodoro()
        self.assertIsNotNone(self.window._rating_source)
        self.window._rating_timeout()
        self.assertEqual(self.window.view_name(), "break")
        self.assertIsNone(self.window.rating)


class PositionTest(CompactTest):
    def test_place_uses_saved_or_default_position(self):
        moves = []
        with mock.patch.object(self.window, "monitors", return_value=[(0, 0, 1920, 1080)]), \
                mock.patch.object(self.window, "get_size", return_value=(388, 180)), \
                mock.patch.object(self.window, "move", lambda x, y: moves.append((x, y))):
            self.window.place()
            self.controller.apply_settings({"compact_position": [100, 120]})
            self.window.place()
            self.controller.apply_settings({"compact_position": [9000, 120]})
            self.window.place()
        self.assertEqual(moves, [(1920 - 388 - 24, 24), (100, 120), (1920 - 388 - 24, 24)])

    def test_moving_saves_the_position_after_a_pause(self):
        self.window._last_position = (10, 10)
        with mock.patch.object(self.window, "get_position", return_value=(300, 400)):
            self.window._on_configure(None, None)
            self.assertIsNotNone(self.window._position_source)
            self.window._save_position()
        self.assertEqual(self.controller.settings["compact_position"], [300, 400])
        with mock.patch.object(self.window, "get_position", return_value=(300, 400)):
            before = self.window._position_source
            self.window._on_configure(None, None)
        self.assertEqual(self.window._position_source, before)                         # mesma posição: não regrava

    def test_settings_changes_refresh_the_card(self):
        self.controller.apply_settings({"compact_idle_opacity": 0.5})
        self.assertAlmostEqual(self.window.frame.get_opacity(), 0.5, places=2)


class MainWindowButtonTest(unittest.TestCase):
    def test_compact_button_calls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = make_controller(tmp)
            calls = []
            window = MainWindow(controller, on_compact=lambda: calls.append("compact"))
            self.addCleanup(window.destroy)
            self.assertTrue(window.compact_button.get_sensitive())
            window.compact_button.clicked()
            self.assertEqual(calls, ["compact"])
            controller.shutdown()


if __name__ == "__main__":
    unittest.main()
