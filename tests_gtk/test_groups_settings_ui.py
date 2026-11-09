import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests_gtk._support import find, labels, make_controller, populate, pump, require_gtk, walk, with_class

require_gtk()

from gi.repository import Gtk  # noqa: E402

from pomodoro import settings as settings_store  # noqa: E402
from pomodoro.ui import dialogs  # noqa: E402
from pomodoro.ui.dialogs import new_task  # noqa: E402
from pomodoro.ui.main_window import MainWindow  # noqa: E402
from pomodoro.ui.pages import groups as groups_mod  # noqa: E402
from pomodoro.ui.pages.groups import GroupsPage, _GroupCardWidget, cycle_choice, effective_cycle  # noqa: E402
from pomodoro.ui.pages.settings_page import SettingsPage, focos_formatter, focos_parser  # noqa: E402
from pomodoro.ui.widgets import ColorPalette, CycleBar, TimeStepper  # noqa: E402


class SmallWidgetsTest(unittest.TestCase):
    def test_color_palette(self):
        palette = ColorPalette("#3DAA7D")
        seen = []
        palette.connect("changed", lambda _p, color: seen.append(color))
        self.assertEqual(palette.value, "#3DAA7D")
        palette._swatches["#E879A6"].set_active(True)
        self.assertEqual((palette.value, seen), ("#E879A6", ["#E879A6"]))
        self.assertEqual(sum(s.get_active() for s in palette._swatches.values()), 1)
        palette._swatches["#E879A6"].set_active(False)                  # clicar na atual não desmarca
        self.assertTrue(palette._swatches["#E879A6"].get_active())
        palette.set_value("#3daa7d")                                    # silencioso e sem diferença de caixa
        self.assertEqual((palette.value, seen), ("#3DAA7D", ["#E879A6"]))

    def test_palette_adds_unknown_colors(self):
        palette = ColorPalette("#123456")
        self.assertEqual(len(palette._swatches), 8)
        self.assertTrue(palette._swatches["#123456"].get_active())

    def test_cycle_bar(self):
        bar = CycleBar(25, 5, 15, 4)
        self.assertEqual(len(bar.segments), 8)
        bar.set_cycle(50, 10, 20, 2)
        self.assertEqual([(s["kind"], s["minutes"]) for s in bar.segments],
                         [("work", 50), ("short", 10), ("work", 50), ("long", 20)])

    def test_stepper_with_other_units(self):
        stepper = TimeStepper(4, step=1, minimum=1, maximum=12, formatter=focos_formatter, parser=focos_parser, small=True)
        seen = []
        stepper.connect("value-changed", lambda _s, value: seen.append(value))
        self.assertEqual(stepper._entry.get_text(), "4 focos")
        stepper._plus.clicked()
        self.assertEqual(stepper._entry.get_text(), "5 focos")
        stepper._entry.set_text("2 focos")
        stepper._entry.activate()
        stepper._entry.set_text("1")
        stepper._entry.activate()
        self.assertEqual((seen, stepper._entry.get_text()), ([5, 2, 1], "1 foco"))
        stepper._entry.set_text("lixo")
        stepper._entry.activate()
        self.assertEqual(stepper._entry.get_text(), "1 foco")
        self.assertTrue(stepper._entry.get_style_context().has_class("stepper-small"))

    def test_cycle_helpers(self):
        self.assertEqual(cycle_choice(None, None), "default")
        self.assertEqual(cycle_choice(50, 10), "long")
        self.assertEqual(cycle_choice(40, None), "custom")
        self.assertEqual(cycle_choice(50, 15), "custom")
        card = SimpleNamespace(work_min=None, short_break_min=8)
        self.assertEqual(effective_cycle(card, {"work_min": 25, "short_break_min": 5}), (25, 8))


from types import SimpleNamespace  # noqa: E402


class PageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)
        self.repo = self.controller.repo

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()


class GroupsPageTest(PageTest):
    def setUp(self):
        super().setUp()
        self.page = GroupsPage(self.controller)
        self.addCleanup(self.page.destroy)
        self.panel = self.page.panel
        self.signals = []
        self.page.connect("add-recurring", lambda _p, group_id: self.signals.append(group_id))

    def card_names(self):
        return [c.card.name for c in find(self.page.flow, lambda w: isinstance(w, _GroupCardWidget))]

    def test_cards_texts_and_first_selected(self):
        texts = labels(self.page.flow)
        self.assertIn("2 tarefas hoje · 2 na semana · pomodoro 25/5", texts)
        self.assertIn("1 tarefa hoje · 1 na semana · pomodoro 25/5", texts)
        self.assertIn("Criar novo grupo", texts)
        self.assertEqual(self.card_names(), ["Trabalho", "Casa"])      # o grupo padrão virou "Trabalho"
        self.assertEqual(self.page.selected, self.page.panel.card.id)
        self.assertEqual(len(with_class(self.page.flow, "card-selected")), 1)

    def test_selecting_loads_the_panel(self):
        self.page.select(self.data["work"]["id"])
        self.assertEqual((self.panel.mode, self.panel.name_entry.get_text(), self.panel.palette.value),
                         ("edit", "Trabalho", "#5B5BD6"))
        self.assertEqual(self.panel.cycle.value, "default")
        self.assertFalse(self.panel.custom_revealer.get_reveal_child())
        self.assertTrue(self.panel.delete_button.get_visible())
        self.assertEqual(self.panel.archive_button.get_label(), "Arquivar")

    def test_edit_and_save(self):
        self.page.select(self.data["work"]["id"])
        self.panel.name_entry.set_text("Trabalho 2026")
        self.panel.palette.set_value("#E879A6", emit=True)
        self.panel.cycle.set_value("long", emit=True)
        self.panel.require_toggle.set_active(True)
        self.assertTrue(self.panel.is_dirty())
        self.assertTrue(self.panel.save())
        group = self.repo.get_group(self.data["work"]["id"])
        self.assertEqual((group["name"], group["color"], group["work_min"], group["short_break_min"],
                          group["require_estimate"]), ("Trabalho 2026", "#E879A6", 50, 10, 1))
        self.assertEqual(self.panel.notice_label.get_text(), "Grupo salvo.")
        self.assertFalse(self.panel.is_dirty())
        self.assertIn("Trabalho 2026", self.card_names())
        self.assertIn("2 tarefas hoje · 2 na semana · pomodoro 50/10", labels(self.page.flow))

    def test_custom_cycle_reveals_steppers(self):
        self.page.select(self.data["home"]["id"])
        self.panel.cycle.set_value("custom", emit=True)
        self.assertTrue(self.panel.custom_revealer.get_reveal_child())
        self.panel.custom_work.set_minutes(40)
        self.panel.custom_short.set_minutes(8)
        self.panel.save()
        group = self.repo.get_group(self.data["home"]["id"])
        self.assertEqual((group["work_min"], group["short_break_min"]), (40, 8))
        self.page.select(self.data["home"]["id"])
        self.assertEqual((self.panel.cycle.value, self.panel.custom_work.minutes), ("custom", 40))

    def test_create_new_group(self):
        self.page.select("new")
        self.assertEqual((self.panel.mode, self.panel.title_label.get_text(), self.panel.save_button.get_label()),
                         ("new", "Novo grupo", "Criar grupo"))
        self.assertFalse(self.panel.delete_button.get_visible())
        self.assertFalse(self.panel.add_recurring_button.get_visible())
        self.panel.name_entry.set_text("Finanças")
        self.panel.palette.set_value("#38B2C9", emit=True)
        self.assertTrue(self.panel.save())
        created = next(g for g in self.repo.list_groups() if g["name"] == "Finanças")
        self.assertEqual(created["color"], "#38B2C9")
        self.assertEqual((self.page.selected, self.panel.mode), (created["id"], "edit"))
        self.assertIn("Finanças", self.card_names())

    def test_validation(self):
        self.page.select("new")
        self.assertFalse(self.panel.save())
        self.assertEqual(self.panel.notice_label.get_text(), "Dê um nome ao grupo.")
        self.assertTrue(self.panel.notice_label.get_visible())

    def test_discarding_unsaved_changes_asks_first(self):
        self.page.select(self.data["work"]["id"])
        self.panel.name_entry.set_text("Mudei")
        with mock.patch.object(dialogs, "confirm", return_value=False) as confirm:
            self.assertFalse(self.page.select(self.data["home"]["id"]))
        confirm.assert_called_once()
        self.assertEqual((self.page.selected, self.panel.name_entry.get_text()), (self.data["work"]["id"], "Mudei"))
        with mock.patch.object(dialogs, "confirm", return_value=True):
            self.assertTrue(self.page.select(self.data["home"]["id"]))
        self.assertEqual(self.panel.name_entry.get_text(), "Casa")
        self.assertEqual(self.repo.get_group(self.data["work"]["id"])["name"], "Trabalho")

    def test_no_prompt_when_nothing_changed(self):
        self.page.select(self.data["work"]["id"])
        with mock.patch.object(dialogs, "confirm") as confirm:
            self.page.select(self.data["home"]["id"])
        confirm.assert_not_called()

    def test_refresh_keeps_unsaved_edits(self):
        self.page.select(self.data["work"]["id"])
        self.panel.name_entry.set_text("Em edição")
        self.controller.add_task("Nova", group_id=self.data["work"]["id"])      # evento de dados de fora
        self.page.on_data("data")
        self.assertEqual(self.panel.name_entry.get_text(), "Em edição")
        self.assertIn("3 tarefas hoje · 3 na semana · pomodoro 25/5", labels(self.page.flow))

    def test_archive_and_restore(self):
        self.page.select(self.data["home"]["id"])
        self.panel.archive_button.clicked()
        self.assertNotIn("Casa", self.card_names())
        self.assertIsNone(self.page.selected)
        self.assertEqual(self.panel.mode, "empty")
        self.assertTrue(self.page.archived_toggle.get_visible())
        self.assertEqual(self.page.archived_toggle.get_label(), "Ver arquivados (1)")
        self.page.archived_toggle.clicked()
        self.assertIn("Casa", self.card_names())
        self.assertIn("arquivado", labels(self.page.flow))
        self.assertEqual(self.page.archived_toggle.get_label(), "Ocultar arquivados")
        self.page.select(self.data["home"]["id"])
        self.assertEqual(self.panel.archive_button.get_label(), "Restaurar")
        self.panel.archive_button.clicked()
        self.assertEqual(self.repo.get_group(self.data["home"]["id"])["archived"], 0)
        self.assertFalse(self.page.archived_toggle.get_visible())

    def test_delete_with_confirmation_and_task_count(self):
        self.page.select(self.data["work"]["id"])
        with mock.patch.object(dialogs, "confirm", return_value=False):
            self.panel.delete_button.clicked()
        self.assertIsNotNone(self.repo.get_group(self.data["work"]["id"]))
        with mock.patch.object(dialogs, "confirm", return_value=True) as confirm:
            self.panel.delete_button.clicked()
        self.assertEqual(confirm.call_args.args[1], "Excluir o grupo “Trabalho”?")
        self.assertIn("As 2 tarefas deste grupo", confirm.call_args.args[2])
        self.assertIsNone(self.repo.get_group(self.data["work"]["id"]))
        self.assertNotIn("Trabalho", self.card_names())
        self.assertEqual(self.panel.mode, "empty")

    def test_close_button_and_card_menu(self):
        self.page.select(self.data["work"]["id"])
        self.panel.emit("closed")
        self.assertEqual((self.page.selected, self.panel.mode), (None, "empty"))
        card = next(c for c in find(self.page.flow, lambda w: isinstance(w, _GroupCardWidget))
                    if c.card.id == self.data["home"]["id"])
        button = find(card, lambda w: isinstance(w, Gtk.MenuButton))[0]
        items = {i.get_label(): i for i in button.get_popup().get_children()}
        self.assertEqual(list(items), ["Editar", "Arquivar", "Excluir…"])
        items["Editar"].activate()
        self.assertEqual(self.page.selected, self.data["home"]["id"])

    def test_click_on_card_and_create_card(self):
        from tests_gtk._support import click_event
        cards = find(self.page.flow, lambda w: isinstance(w, _GroupCardWidget))
        target = next(c for c in cards if c.card.id == self.data["home"]["id"])
        target.emit("button-press-event", click_event(1))
        self.assertEqual(self.page.selected, self.data["home"]["id"])
        boxes = [w for w in find(self.page.flow, lambda w: isinstance(w, Gtk.EventBox)) if not isinstance(w, _GroupCardWidget)
                 and "Criar novo grupo" in labels(w)]
        boxes[-1].emit("button-press-event", click_event(1))
        self.assertEqual((self.page.selected, self.panel.mode), ("new", "new"))

    def test_recurring_list_and_button(self):
        self.controller.create_task_full("Responder e-mails", group_id=self.data["work"]["id"], day="2026-11-10",
                                         estimate_min=20, repeat_rule="weekdays")
        self.page.refresh()
        self.page.select(self.data["work"]["id"])
        texts = labels(self.panel.recurring_box)
        self.assertIn("↻  Responder e-mails", texts)
        self.assertIn("dias úteis · 20m", texts)
        self.panel.add_recurring_button.clicked()
        self.assertEqual(self.signals, [self.data["work"]["id"]])

    def test_insight_and_precision_texts(self):
        for index, real in enumerate((39, 33, 36)):
            task = self.controller.add_task(f"Antiga {index}", 30, self.data["home"]["id"])
            session = self.repo.start_session("work", task_id=task["id"])
            self.repo.end_session(session, real * 60)
            self.controller.set_task_done(task["id"], True)
        self.page.refresh()
        texts = labels(self.page.flow)
        self.assertIn("✦ Você subestima tarefas deste grupo em ~20%", texts)
        self.assertIn("Sem dados suficientes ainda para a IA", texts)
        self.assertTrue(any(t.startswith("Precisão ") and t.endswith("%") for t in texts))

    def test_group_panel_changes_reach_the_focused_timer(self):
        self.controller.focus(self.data["report"]["id"])
        self.page.select(self.data["work"]["id"])
        self.panel.cycle.set_value("long", emit=True)
        self.panel.save()
        self.assertEqual(self.controller.timer.remaining, 50 * 60)


class SettingsPageTest(PageTest):
    def setUp(self):
        super().setUp()
        self.sounds = []
        self.controller._play_sound = self.sounds.append
        self.page = SettingsPage(self.controller)
        self.addCleanup(self.page.destroy)

    def settings(self):
        return self.controller.settings

    def steppers(self, tab):
        return find(self.page.stack.get_child_by_name(tab), lambda w: isinstance(w, TimeStepper))

    def test_tabs_switch_the_content(self):
        for name in ("compact", "sound", "ai", "focus"):
            self.page.tabs.set_value(name, emit=True)
            self.assertEqual(self.page.stack.get_visible_child_name(), name)

    def test_cycle_steppers_apply_and_redraw_the_summary(self):
        work, short, long_, cycles, free = self.steppers("focus")
        self.assertEqual(self.page.cycle_text.get_text(),
                         "Ciclo completo: 2h 10m · 4 focos de 25 min, 3 pausas curtas e 1 longa")
        work.set_minutes(50, emit=True)
        short.set_minutes(10, emit=True)
        long_.set_minutes(30, emit=True)
        cycles._entry.set_text("2 focos")
        cycles._entry.activate()
        self.assertEqual((self.settings()["work_min"], self.settings()["short_break_min"],
                          self.settings()["long_break_min"], self.settings()["cycles_before_long_break"]),
                         (50, 10, 30, 2))
        self.assertEqual(self.page.cycle_text.get_text(),
                         "Ciclo completo: 2h 20m · 2 focos de 50 min, 1 pausa curta e 1 longa")
        self.assertEqual(len(self.page.cycle_bar.segments), 4)
        self.assertEqual(self.controller.timer.remaining, 50 * 60)

    def test_toggles_persist(self):
        self.page.toggles["auto_start_work"].set_active(True)
        self.page.toggles["count_overtime"].set_active(False)
        self.page.toggles["one_thing_at_a_time"].set_active(True)
        self.assertTrue(self.settings()["auto_start_work"])
        self.assertFalse(self.settings()["count_overtime"])
        saved = settings_store.load_settings(self.controller.data_dir)
        self.assertTrue(saved["one_thing_at_a_time"])
        self.assertFalse(saved["count_overtime"])

    def test_tdah_options(self):
        warn_switch, hyper_switch = self.page.warn_toggle, self.page.hyper_toggle
        self.assertFalse(warn_switch.get_active())                    # o controlador de teste começa sem aviso
        warn_switch.set_active(True)
        self.assertEqual(self.settings()["warn_before_end_min"], 2)
        warn_switch.set_active(False)
        self.assertEqual(self.settings()["warn_before_end_min"], 0)
        self.page.threshold.set_value(200, emit=True)
        self.assertEqual(self.settings()["hyperfocus_threshold_pct"], 200)
        hyper_switch.set_active(False)
        self.assertFalse(self.settings()["hyperfocus_alert"])
        self.assertFalse(self.page.threshold.get_sensitive())
        hyper_switch.set_active(True)
        self.assertTrue(self.page.threshold.get_sensitive())

    def test_threshold_snaps_to_the_nearest_option(self):
        self.assertEqual(SettingsPage._closest_threshold(150), 150)
        self.assertEqual(SettingsPage._closest_threshold(300), 200)
        self.assertEqual(SettingsPage._closest_threshold(110), 125)

    def test_day_card(self):
        free = self.steppers("focus")[-1]
        free.set_minutes(300, emit=True)
        self.assertEqual(self.settings()["free_minutes_per_day"], 300)
        reminder = self.page.reminder
        reminder.set_text("07:30")
        reminder.activate()
        self.assertEqual(self.settings()["end_of_day_reminder"], "07:30")
        reminder.set_text("25:99")
        reminder.activate()
        self.assertEqual((self.settings()["end_of_day_reminder"], reminder.get_text()), ("07:30", "07:30"))
        self.assertTrue(reminder.get_style_context().has_class("entry-error"))
        reminder.set_text("")
        reminder.activate()
        self.assertEqual(self.settings()["end_of_day_reminder"], "")
        self.assertFalse(reminder.get_style_context().has_class("entry-error"))

    def test_compact_options_and_preview(self):
        self.page.tabs.set_value("compact", emit=True)
        preview = self.page.compact_preview
        self.assertTrue(preview.time.get_visible() and not preview.estimate.get_visible())
        self.page.field_chips["estimate_vs_real"].set_active(True)
        self.assertEqual(self.settings()["compact_fields"],
                         ["remaining", "current_task", "next_break", "progress", "estimate_vs_real"])
        self.assertTrue(preview.estimate.get_visible())
        self.page.field_chips["current_task"].set_active(False)
        self.assertNotIn("current_task", self.settings()["compact_fields"])
        self.assertFalse(preview.task.get_visible())
        for field in ("remaining", "next_break", "progress", "estimate_vs_real"):
            self.page.field_chips[field].set_active(False)
        self.assertEqual(self.settings()["compact_fields"], ["estimate_vs_real"])          # o último não sai
        self.assertTrue(self.page.field_chips["estimate_vs_real"].get_active())
        self.page.opacity_scale.set_value(50)
        self.assertEqual((self.settings()["compact_idle_opacity"], self.page.opacity_label.get_text()), (0.5, "50%"))
        self.assertAlmostEqual(preview.get_opacity(), 0.5, places=2)
        self.page.toggles["compact_always_on_top"].set_active(False)
        self.assertFalse(self.settings()["compact_always_on_top"])

    def test_sound_options(self):
        self.page.end_sound.set_value("bell", emit=True)
        self.assertEqual(self.settings()["end_sound"], "bell")
        play = [b for b in find(self.page.stack.get_child_by_name("sound"), lambda w: isinstance(w, Gtk.Button))
                if b.get_label() == "▶"][0]
        play.clicked()
        self.assertEqual(self.sounds, ["bell"])
        self.page.end_sound.set_value("", emit=True)
        self.assertEqual(self.settings()["end_sound"], "")
        self.page.toggles["system_notifications"].set_active(False)
        self.assertFalse(self.settings()["system_notifications"])
        disabled = [w for w in find(self.page.stack.get_child_by_name("sound"), lambda w: isinstance(w, Gtk.Switch))
                    if not w.get_sensitive()]
        self.assertEqual(len(disabled), 1)

    def test_unknown_saved_sound_is_still_listed(self):
        self.controller.apply_settings({"end_sound": "meu-som"})
        page = SettingsPage(self.controller)
        self.addCleanup(page.destroy)
        self.assertEqual((page.end_sound.value, page.end_sound.get_text()), ("meu-som", "meu-som"))

    def test_ai_tab(self):
        self.assertFalse(self.page.key_entry.get_sensitive())
        self.assertFalse(self.page.key_entry.get_visibility())
        self.page._on_cloud_toggled(True)
        self.assertTrue(self.page.key_entry.get_sensitive())
        self.assertTrue(self.settings()["ai_cloud_enabled"])
        self.page.key_entry.set_text("  sk-ant-teste ")
        self.page.key_entry.activate()
        self.assertEqual(self.settings()["anthropic_api_key"], "sk-ant-teste")
        self.page.toggles["ai_enabled"].set_active(False)
        self.assertFalse(self.settings()["ai_enabled"])

    def test_export(self):
        path = Path(self._tmp.name) / "saida.json"
        self.assertTrue(self.page.export_to(path))
        self.assertTrue(path.exists())
        self.assertIn("registros exportados", self.page.export_status.get_text())
        self.assertNotIn("sk-ant", path.read_text())
        self.assertFalse(self.page.export_to(Path(self._tmp.name) / "nao-existe" / "x.json"))
        self.assertIn("Não foi possível salvar", self.page.export_status.get_text())


class WindowIntegrationTest(PageTest):
    def setUp(self):
        super().setUp()
        self.window = MainWindow(self.controller)
        self.addCleanup(self.window.destroy)

    def test_pages_are_the_real_ones(self):
        self.assertIsInstance(self.window.pages["groups"], GroupsPage)
        self.assertIsInstance(self.window.pages["settings"], SettingsPage)

    def test_sidebar_plus_goes_to_groups_and_refreshes(self):
        self.controller.create_group("Nova", "#F2B33D")
        self.window.sidebar.set_page("groups", emit=True)
        self.assertEqual(self.window.stack.get_visible_child_name(), "groups")
        names = [c.card.name for c in find(self.window.groups.flow, lambda w: isinstance(w, _GroupCardWidget))]
        self.assertIn("Nova", names)

    def test_data_events_refresh_the_open_groups_page(self):
        self.window.show_page("groups")
        with mock.patch.object(self.window, "get_visible", return_value=True):
            self.controller.create_group("Ao vivo", "#F2B33D")
        names = [c.card.name for c in find(self.window.groups.flow, lambda w: isinstance(w, _GroupCardWidget))]
        self.assertIn("Ao vivo", names)

    def test_add_recurring_opens_the_new_task_modal_for_the_group(self):
        with mock.patch.object(new_task, "run_new_task_dialog", return_value=None) as run:
            self.window.groups.emit("add-recurring", self.data["work"]["id"])
        self.assertEqual(run.call_args.kwargs["group_id"], self.data["work"]["id"])

    def test_one_thing_at_a_time(self):
        self.controller.apply_settings({"one_thing_at_a_time": True})
        self.controller.focus(self.data["report"]["id"])
        self.window.refresh_tasks()
        self.assertIn("Lavar roupa", labels(self.window.today.task_list))
        self.assertFalse(self.window.today.one_thing_banner.get_visible())
        self.controller.toggle_timer()
        self.window.refresh_tasks()
        texts = labels(self.window.today.task_list)
        self.assertNotIn("Lavar roupa", texts)
        self.assertNotIn("Responder e-mails", texts)
        self.assertIn("Escrever relatório", texts)
        self.assertTrue(self.window.today.one_thing_banner.get_visible())
        self.assertEqual(self.window.sidebar._nav_counts["today"].get_text(), "3")        # contagens seguem do dia todo
        self.window.today.emit("show-all-tasks")
        self.assertIn("Lavar roupa", labels(self.window.today.task_list))
        self.assertFalse(self.window.today.one_thing_banner.get_visible())
        self.controller.toggle_timer()                                                    # pausar: a exceção acaba
        self.window.refresh_tasks()
        self.controller.toggle_timer()
        self.window.refresh_tasks()
        self.assertNotIn("Lavar roupa", labels(self.window.today.task_list))

    def test_one_thing_off_shows_everything_while_running(self):
        self.controller.focus(self.data["report"]["id"])
        self.controller.toggle_timer()
        self.window.refresh_tasks()
        self.assertIn("Lavar roupa", labels(self.window.today.task_list))

    def test_one_thing_not_applied_during_breaks(self):
        self.controller.apply_settings({"one_thing_at_a_time": True})
        self.controller.focus(self.data["report"]["id"])
        self.controller.timer.skip()
        self.controller.toggle_timer()
        self.window.refresh_tasks()
        self.assertIn("Lavar roupa", labels(self.window.today.task_list))


if __name__ == "__main__":
    unittest.main()
