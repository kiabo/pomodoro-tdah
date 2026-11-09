import tempfile
import unittest
from unittest import mock

from tests_gtk._support import (click_event, find, labels, make_controller, populate, pump, require_gtk,
                                walk, with_class)

require_gtk()

from gi.repository import Gdk, Gtk  # noqa: E402

from pomodoro.timer import Phase  # noqa: E402
from pomodoro.ui import dialogs  # noqa: E402
from pomodoro.ui.dialogs import new_task  # noqa: E402
from pomodoro.ui.main_window import MainWindow  # noqa: E402
from pomodoro.ui.pages.today import TodayPage  # noqa: E402
from pomodoro.ui.sidebar import Sidebar, capacity_text  # noqa: E402
from pomodoro.ui.task_list import TaskList, real_cell, summary_text  # noqa: E402
from pomodoro.ui.timer_panel import TimerPanel  # noqa: E402


class UiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.data = populate(self.controller)

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def tick(self, n):
        for _ in range(n):
            self.controller.timer.tick()


class RealCellTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(real_cell(15 * 60, 20, True, False, False), ("15m", "↓5m", "under"))
        self.assertEqual(real_cell(62 * 60, 50, True, False, False), ("1h 02m", "↑12m", "over"))
        self.assertEqual(real_cell(20 * 60, 20, True, False, False), ("20m", "", "plain"))
        self.assertEqual(real_cell(50 * 60, 90, False, True, True), ("50m ⏵", "", "active"))
        self.assertEqual(real_cell(50 * 60, 90, False, True, False), ("50m", "", "active"))
        self.assertEqual(real_cell(0, 90, False, False, False), ("—", "", "plain"))

    def test_summary_text(self):
        self.assertEqual(summary_text(190, 3900), "prev 3h 10m · real 1h 05m")
        self.assertEqual(summary_text(40, 0), "prev 40m")
        self.assertEqual(summary_text(0, 0), "")


class TaskListTest(UiTest):
    def make_list(self, **kwargs):
        task_list = TaskList(self.controller)
        view = self.controller.today_view()
        task_list.render(view, self.controller.tracker.active_task_id,
                         self.controller.tracker.active_subtask_id, **kwargs)
        return task_list

    def test_structure_and_texts(self):
        task_list = self.make_list()
        texts = labels(task_list)
        for expected in ("Trabalho", "Casa", "2 tarefas", "1 tarefa", "Responder e-mails",
                         "Escrever relatório", "Lavar roupa", "prev 1h 50m · real 15m"):
            self.assertIn(expected, texts)
        self.assertEqual(len(task_list.get_children()), 2 + 3)          # 2 cabeçalhos + 3 tarefas
        self.assertIn("Concluída", texts)
        self.assertNotIn("Levantar números", texts)                     # subtarefas começam fechadas

    def test_done_row_shows_time_delta(self):
        task_list = self.make_list()
        real_texts = [t for t in labels(task_list) if "15m" in t]
        self.assertTrue(any("↓5m" in t for t in real_texts), real_texts)

    def test_checkbox_completes_task(self):
        task_list = self.make_list()
        checks = with_class(task_list, "check")
        laundry_check = next(c for c in checks if not c.get_active())
        laundry_check.set_active(True)
        statuses = {t["title"]: t["status"] for t in self.controller.repo.list_tasks()}
        self.assertEqual(statuses["Responder e-mails"], "done")
        self.assertEqual(sum(1 for s in statuses.values() if s == "done"), 2)

    def test_clicking_a_row_focuses_it(self):
        task_list = self.make_list()
        boxes = [c for c in task_list.get_children() if isinstance(c, Gtk.EventBox)]
        boxes[-1].emit("button-press-event", click_event(1))             # Lavar roupa
        self.assertEqual(self.controller.tracker.active_task_id, self.data["laundry"]["id"])

    def test_active_task_expands_with_subtasks_and_focus_style(self):
        self.controller.focus(self.data["report"]["id"], self.data["charts"]["id"])
        task_list = self.make_list()
        texts = labels(task_list)
        self.assertIn("Levantar números", texts)
        self.assertIn("Montar gráficos", texts)
        self.assertIn("＋ Subtarefa", texts)
        self.assertIn("Em foco", texts)
        self.assertEqual(len(with_class(task_list, "task-row-focus")), 1)
        self.assertEqual(len(with_class(task_list, "task-row-done")), 1)

    def test_arrow_toggles_subtasks(self):
        task_list = self.make_list()
        arrow = next(b for b in find(task_list, lambda w: isinstance(w, Gtk.Button)) if b.get_label() == "▸")
        arrow.clicked()
        self.assertIn("Levantar números", labels(task_list))
        arrow = next(b for b in find(task_list, lambda w: isinstance(w, Gtk.Button)) if b.get_label() == "▾")
        arrow.clicked()
        self.assertNotIn("Levantar números", labels(task_list))

    def test_collapsing_the_active_task_is_remembered(self):
        self.controller.focus(self.data["report"]["id"])
        task_list = self.make_list()
        arrow = next(b for b in find(task_list, lambda w: isinstance(w, Gtk.Button)) if b.get_label() == "▾")
        arrow.clicked()
        self.assertNotIn("Levantar números", labels(task_list))

    def test_inline_add_subtask(self):
        self.controller.focus(self.data["laundry"]["id"])
        task_list = self.make_list()
        link = next(b for b in find(task_list, lambda w: isinstance(w, Gtk.Button)) if b.get_label() == "＋ Subtarefa")
        link.clicked()
        pump()
        entries = find(task_list, lambda w: isinstance(w, Gtk.Entry))
        self.assertEqual(len(entries), 2)
        entries[0].set_text("Separar as cores")
        entries[1].set_text("10")
        entries[0].activate()
        subs = self.controller.repo.list_subtasks(self.data["laundry"]["id"])
        self.assertEqual([(s["title"], s["estimate_min"]) for s in subs], [("Separar as cores", 10)])

    def test_subtask_checkbox_and_click(self):
        self.controller.focus(self.data["report"]["id"])
        task_list = self.make_list()
        squares = with_class(task_list, "check-square")
        squares[0].set_active(True)
        self.assertEqual(self.controller.repo.get_subtask(self.data["numbers"]["id"])["done"], 1)
        rows = find(task_list, lambda w: isinstance(w, Gtk.EventBox) and "Montar gráficos" in labels(w)
                    and "Escrever relatório" not in labels(w))
        rows[-1].emit("button-press-event", click_event(1))
        self.assertEqual(self.controller.tracker.active_subtask_id, self.data["charts"]["id"])

    def test_context_menu_actions(self):
        task_list = self.make_list()
        view = self.controller.today_view()
        task = next(t for t in view.visible_tasks if t.title == "Lavar roupa")
        with mock.patch.object(Gtk.Menu, "popup_at_pointer"):
            menu = task_list._task_menu(task, click_event(3))
        items = {i.get_label(): i for i in menu.get_children() if isinstance(i, Gtk.MenuItem) and i.get_label()}
        self.assertEqual(list(items), ["Editar…", "Focar nesta tarefa", "Concluir", "Adicionar subtarefa",
                                       "Renomear…", "Excluir…"])
        items["Concluir"].activate()
        self.assertEqual(self.controller.repo.get_task(task.id)["status"], "done")
        with mock.patch.object(dialogs, "ask_text", return_value="Lavar a roupa branca"):
            items["Renomear…"].activate()
        self.assertEqual(self.controller.repo.get_task(task.id)["title"], "Lavar a roupa branca")
        with mock.patch.object(dialogs, "confirm", return_value=False):
            items["Excluir…"].activate()
        self.assertIsNotNone(self.controller.repo.get_task(task.id))
        with mock.patch.object(dialogs, "confirm", return_value=True):
            items["Excluir…"].activate()
        self.assertIsNone(self.controller.repo.get_task(task.id))

    def test_subtask_menu(self):
        self.controller.focus(self.data["report"]["id"])
        task_list = self.make_list()
        view = self.controller.today_view()
        task = next(t for t in view.visible_tasks if t.title == "Escrever relatório")
        with mock.patch.object(Gtk.Menu, "popup_at_pointer"):
            menu = task_list._subtask_menu(task, task.subtasks[0], click_event(3))
        items = {i.get_label(): i for i in menu.get_children() if isinstance(i, Gtk.MenuItem) and i.get_label()}
        items["Focar nesta subtarefa"].activate()
        self.assertEqual(self.controller.tracker.active_subtask_id, task.subtasks[0].id)
        with mock.patch.object(dialogs, "confirm", return_value=True):
            items["Excluir…"].activate()
        self.assertEqual(len(self.controller.repo.list_subtasks(task.id)), 1)

    def test_empty_states(self):
        task_list = TaskList(self.controller)
        empty = self.controller.today_view(query="zzz")
        task_list.render(empty, None, None, filtered=True)
        self.assertEqual(labels(task_list), ["Nenhuma tarefa encontrada."])
        task_list.render(empty, None, None, filtered=False)
        self.assertIn("Nada por aqui ainda", labels(task_list)[0])

    def test_live_update_follows_the_running_focus(self):
        self.controller.focus(self.data["report"]["id"], self.data["charts"]["id"])
        task_list = self.make_list()
        self.controller.toggle_timer()
        self.tick(180)
        task_list.update_live()
        texts = labels(task_list)
        self.assertEqual(sum(1 for t in texts if t == "3m ⏵"), 2)                       # tarefa e subtarefa
        self.assertEqual(round(task_list.live_total_seconds()), 15 * 60 + 180)
        self.assertIn("prev 1h 50m · real 18m", texts)


class TimerPanelTest(UiTest):
    def make_panel(self):
        panel = TimerPanel(self.controller)
        ctx = self.controller.focus_context(self.controller.today_view())
        panel.set_context(ctx["task_id"], ctx["task_title"], ctx["subtask_title"], ctx["estimate_min"], ctx["next_title"])
        return panel

    def test_idle_state_without_task(self):
        panel = self.make_panel()
        self.assertEqual(panel.phase_label.get_text(), "PRONTO PARA FOCAR · POMODORO 1 DE 4")
        self.assertEqual((panel.ring.time_label.get_text(), panel.ring.caption_label.get_text()), ("25:00", "de 25:00"))
        self.assertEqual(panel.title_label.get_text(), "Escolha uma tarefa para focar")
        self.assertFalse(panel.done_button.get_sensitive())
        self.assertFalse(panel.progress_card.get_visible())
        self.assertEqual(panel.ring.fraction, 0.0)

    def test_running_with_subtask(self):
        self.controller.focus(self.data["report"]["id"], self.data["charts"]["id"])
        panel = self.make_panel()
        self.controller.toggle_timer()
        self.tick(5 * 60)
        panel.refresh()
        self.assertEqual(panel.phase_label.get_text(), "EM FOCO · POMODORO 1 DE 4")
        self.assertEqual((panel.title_label.get_text(), panel.subtitle_label.get_text()),
                         ("Montar gráficos", "Escrever relatório"))
        self.assertEqual(panel.ring.time_label.get_text(), "20:00")
        self.assertAlmostEqual(panel.ring.fraction, 0.2)
        self.assertEqual(panel.play_button.get_label(), "❚❚")
        self.assertTrue(panel.done_button.get_sensitive())
        self.assertEqual(panel.done_button.get_tooltip_text(), "Concluir subtarefa")
        self.assertEqual(panel.progress_numbers.get_text(), "Real 5m / Prev 1h 30m")
        self.assertIn("Faltam ~1h 25m", panel.progress_text.get_text())

    def test_buttons_drive_the_controller(self):
        panel = self.make_panel()
        panel.play_button.clicked()
        self.assertTrue(self.controller.timer.running)
        self.tick(30)
        panel.stop_button.clicked()
        self.assertEqual((self.controller.timer.running, self.controller.timer.remaining), (False, 25 * 60))
        panel.skip_button.clicked()
        panel.refresh()
        self.assertEqual(self.controller.timer.phase, Phase.SHORT_BREAK)
        self.assertEqual(panel.title_label.get_text(), "Hora de respirar")
        self.assertEqual(panel.ring.time_label.get_text(), "05:00")
        self.assertFalse(panel.done_button.get_sensitive())

    def test_done_button_completes_focus(self):
        self.controller.focus(self.data["report"]["id"], self.data["numbers"]["id"])
        panel = self.make_panel()
        panel.done_button.clicked()
        self.assertEqual(self.controller.repo.get_subtask(self.data["numbers"]["id"])["done"], 1)
        self.assertEqual(self.controller.tracker.active_subtask_id, self.data["charts"]["id"])

    def test_overtime_look(self):
        self.controller.focus(self.data["report"]["id"])
        panel = self.make_panel()
        self.controller.toggle_timer()
        self.tick(25 * 60 + 90)
        panel.refresh()
        self.assertEqual(panel.ring.time_label.get_text(), "+01:30")
        self.assertEqual(panel.ring.caption_label.get_text(), "tempo extra")
        self.assertEqual(panel.ring.fraction, 1.0)
        self.assertTrue(panel.phase_label.get_text().startswith("TEMPO EXTRA"))

    def test_intervals_card(self):
        self.controller.focus(self.data["report"]["id"], self.data["numbers"]["id"])
        panel = self.make_panel()
        rows = [(t.get_text(), w.get_text()) for _d, t, w in panel._interval_rows]
        self.assertEqual(rows[0][0], "Pausa curta · 5 min")
        self.assertEqual(rows[1][0], "Foco · Montar gráficos")
        self.assertEqual(rows[2][0], "Pausa curta · 5 min")          # a longa só vem depois do 4º foco
        self.assertTrue(all(len(w) == 5 and w[2] == ":" for _t, w in rows))

    def test_over_estimate_progress(self):
        self.controller.repo.update_task(self.data["laundry"]["id"], estimate_min=10)
        self.controller.focus(self.data["laundry"]["id"])
        panel = self.make_panel()
        self.controller.repo.add_manual_adjustment(self.data["laundry"]["id"], 25 * 60)
        panel.refresh()
        self.assertEqual(panel.progress_text.get_text(), "Passou 15m do previsto.")
        self.assertTrue(panel.progress_bar.get_style_context().has_class("bar-focus"))


class SidebarTest(UiTest):
    def test_capacity_texts(self):
        self.assertIn("Nada planejado", capacity_text(0, 360))
        self.assertEqual(capacity_text(200, 360), "Hoje: 3h 20m previstas para 6h livres. Dá tempo, com folga para pausas.")
        self.assertTrue(capacity_text(340, 360).endswith("Dá tempo, mas sem muita folga."))
        self.assertTrue(capacity_text(420, 360).endswith("Passa 1h do tempo livre. Vale adiar algo para amanhã."))

    def test_data_navigation_and_group_filter(self):
        sidebar = Sidebar(self.controller)
        sidebar.set_data(self.controller.today_view(), 360)
        events = []
        sidebar.connect("navigate", lambda _s, page: events.append(("nav", page)))
        sidebar.connect("group-selected", lambda _s, group: events.append(("group", group)))
        texts = labels(sidebar)
        self.assertIn("Trabalho", texts)
        self.assertIn("Casa", texts)
        self.assertIn("3", texts)                                       # 3 tarefas hoje
        sidebar._nav_buttons["groups"].set_active(True)
        self.assertEqual((sidebar.page, events[-1]), ("groups", ("nav", "groups")))
        sidebar._group_buttons[self.data["home"]["id"]].set_active(True)
        self.assertEqual(sidebar.group_filter, self.data["home"]["id"])
        self.assertEqual(events[-2:], [("nav", "today"), ("group", self.data["home"]["id"])])
        sidebar._group_buttons[self.data["home"]["id"]].set_active(False)
        self.assertIsNone(sidebar.group_filter)

    def test_active_nav_cannot_be_deselected(self):
        sidebar = Sidebar(self.controller)
        sidebar._nav_buttons["today"].set_active(False)
        self.assertTrue(sidebar._nav_buttons["today"].get_active())
        with self.assertRaises(ValueError):
            sidebar.set_page("nao-existe")

    def test_mini_timer(self):
        sidebar = Sidebar(self.controller)
        sidebar.set_focus_title("Montar gráficos")
        self.controller.toggle_timer()
        self.tick(60)
        sidebar.refresh_timer()
        self.assertEqual(sidebar.mini_time.get_text(), "24:00")
        self.assertEqual(sidebar.mini_task.get_text(), "Montar gráficos")
        self.assertEqual(sidebar.mini_eyebrow.get_text(), "EM FOCO · POMODORO 1/4")
        self.assertTrue(sidebar.mini_next.get_text().startswith("Pausa curta de 5 min às "))


class TodayPageTest(UiTest):
    def make_page(self):
        page = TodayPage(self.controller)
        self.refresh(page)
        return page

    def refresh(self, page, **kwargs):
        view = self.controller.today_view(**kwargs)
        page.refresh(view, self.controller.focus_context(view))

    def test_kpis(self):
        page = self.make_page()
        self.assertEqual(page.kpi_planned.get_text(), "2h 20m")
        self.assertEqual(page.kpi_real.get_text(), "15m")
        self.assertEqual(page.kpi_pomodoros.get_text(), "1 de 6")
        self.assertEqual(page.kpi_accuracy.get_text(), "75%")
        self.assertIn("SEGUNDA, 9 DE NOVEMBRO", labels(page))

    def test_quick_add_with_time(self):
        page = self.make_page()
        entry = page.quick_add
        entry.title_entry.set_text("Marcar dentista")
        entry.time_entry.set_text("1h15")
        entry.title_entry.activate()
        task = next(t for t in self.controller.repo.list_tasks() if t["title"] == "Marcar dentista")
        self.assertEqual((task["estimate_min"], task["scheduled_for"]), (75, "2026-11-09"))
        self.assertEqual((entry.title_entry.get_text(), entry.time_entry.get_text()), ("", ""))

    def test_quick_add_without_time_and_bad_time(self):
        page = self.make_page()
        entry = page.quick_add
        entry.title_entry.set_text("Sem tempo")
        entry.title_entry.activate()
        self.assertTrue(any(t["title"] == "Sem tempo" for t in self.controller.repo.list_tasks()))
        entry.title_entry.set_text("Tempo ruim")
        entry.time_entry.set_text("xyz")
        entry.title_entry.activate()
        self.assertFalse(any(t["title"] == "Tempo ruim" for t in self.controller.repo.list_tasks()))
        self.assertTrue(entry.time_entry.get_style_context().has_class("entry-error"))
        entry.time_entry.set_text("30")                                   # editar limpa o erro
        self.assertFalse(entry.time_entry.get_style_context().has_class("entry-error"))

    def test_quick_add_respects_group_that_requires_estimate(self):
        group = self.controller.repo.create_group("Rígido", require_estimate=True)
        page = self.make_page()
        page.new_task_group = group["id"]
        page.quick_add.title_entry.set_text("Sem previsão")
        page.quick_add.title_entry.activate()
        self.assertFalse(any(t["title"] == "Sem previsão" for t in self.controller.repo.list_tasks()))
        self.assertTrue(page.quick_add.time_entry.get_style_context().has_class("entry-error"))
        self.assertIn("exige a previsão", page.quick_add.time_entry.get_tooltip_text())

    def test_search_emits_and_empty_title_is_ignored(self):
        page = self.make_page()
        seen = []
        page.connect("query-changed", lambda _p, text: seen.append(text))
        page.search.set_text("rel")
        self.assertEqual((seen, page.query), (["rel"], "rel"))
        page.quick_add.title_entry.set_text("   ")
        page.quick_add.title_entry.activate()
        self.assertEqual(len(self.controller.repo.list_tasks()), 3)

    def test_group_title_and_filtered_view(self):
        page = TodayPage(self.controller)
        view = self.controller.today_view(group_id=self.data["home"]["id"])
        page.refresh(view, self.controller.focus_context(view), filtered=True, group_name="Casa")
        self.assertEqual(page.title_label.get_text(), "Hoje · Casa")
        self.assertEqual(page.kpi_planned.get_text(), "2h 20m")          # totais do dia inteiro
        self.assertNotIn("Responder e-mails", labels(page.task_list))

    def test_live_kpi(self):
        page = self.make_page()
        self.controller.focus(self.data["laundry"]["id"])
        self.refresh(page)
        self.controller.toggle_timer()
        self.tick(10 * 60)
        page.refresh_live()
        self.assertEqual(page.kpi_real.get_text(), "25m")


class MainWindowTest(UiTest):
    def make_window(self):
        window = MainWindow(self.controller)
        self.addCleanup(window.destroy)
        return window

    def test_builds_without_showing(self):
        window = self.make_window()
        self.assertFalse(window.get_visible())
        self.assertIn("Escrever relatório", labels(window.today.task_list))
        self.assertEqual(window.stack.get_visible_child_name(), "today")
        self.assertFalse(window.compact_button.get_sensitive())

    def test_navigation_between_pages(self):
        window = self.make_window()
        window.sidebar._nav_buttons["settings"].set_active(True)
        self.assertEqual(window.stack.get_visible_child_name(), "settings")
        window.show_page("groups")
        self.assertEqual((window.stack.get_visible_child_name(), window.sidebar.page), ("groups", "groups"))

    def test_group_filter_and_search_refresh_the_list(self):
        window = self.make_window()
        window.sidebar._group_buttons[self.data["home"]["id"]].set_active(True)
        texts = labels(window.today.task_list)
        self.assertIn("Lavar roupa", texts)
        self.assertNotIn("Escrever relatório", texts)
        self.assertEqual(window.today.title_label.get_text(), "Hoje · Casa")
        window.sidebar._group_buttons[self.data["home"]["id"]].set_active(False)
        window.today.search.set_text("RELAT")
        texts = labels(window.today.task_list)
        self.assertIn("Escrever relatório", texts)
        self.assertNotIn("Lavar roupa", texts)

    def test_events_are_ignored_while_hidden_and_applied_when_shown(self):
        window = self.make_window()
        self.controller.add_task("Nova tarefa escondida", 10)
        self.assertNotIn("Nova tarefa escondida", labels(window.today.task_list))   # janela escondida: não redesenha
        window.refresh_all()                                                         # o que o evento "map" faz
        self.assertIn("Nova tarefa escondida", labels(window.today.task_list))

    def test_event_handling_when_visible(self):
        window = self.make_window()
        with mock.patch.object(window, "get_visible", return_value=True):
            self.controller.add_task("Apareceu", 5)
            self.assertIn("Apareceu", labels(window.today.task_list))
            self.controller.focus(self.data["laundry"]["id"])
            self.controller.toggle_timer()
            self.tick(60)
            self.assertEqual(window.sidebar.mini_time.get_text(), "24:00")

    def test_keyboard_shortcuts(self):
        window = self.make_window()
        window.show_page("groups")
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_k
        event.state = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(window._on_key_press(window, event))
        self.assertEqual(window.stack.get_visible_child_name(), "today")
        event.keyval = Gdk.KEY_n
        with mock.patch.object(new_task, "run_new_task_dialog", return_value=None) as run:
            self.assertTrue(window._on_key_press(window, event))
        run.assert_called_once()
        event.keyval = Gdk.KEY_a
        self.assertFalse(window._on_key_press(window, event))

    def test_basic_settings_page_applies_values(self):
        window = self.make_window()
        page = window.pages["settings"]
        steppers = [w for w in walk(page) if w.__class__.__name__ == "TimeStepper"]
        steppers[0].set_minutes(50, emit=True)
        self.assertEqual(self.controller.settings["work_min"], 50)
        self.assertEqual(self.controller.timer.remaining, 50 * 60)

    def test_confirm_restart(self):
        window = self.make_window()
        self.controller.timer.skip()
        with mock.patch.object(dialogs, "confirm", return_value=True):
            window.confirm_restart()
        self.assertEqual(self.controller.timer.phase, Phase.WORK)


if __name__ == "__main__":
    unittest.main()
