"""Tela "Hoje" (D1): indicadores do dia, adição rápida, lista de tarefas e painel do timer."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from ..format import format_date_eyebrow, format_minutes
from ..layout import button, expand, hbox, label, vbox
from ..task_list import COL_EST, COL_REAL, COL_STATUS, TaskList
from ..theme import style
from ..timer_panel import WIDTH as PANEL_WIDTH, TimerPanel
from ..widgets import QuickEntry


class TodayPage(Gtk.Box):
    """Emite "query-changed"(texto) quando a busca muda."""

    __gsignals__ = {"query-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.controller = controller
        self.new_task_group = None
        self._view = None
        self.set_border_width(0)
        self.set_margin_top(28)
        self.set_margin_bottom(20)
        self.set_margin_start(32)
        self.set_margin_end(32)

        self.pack_start(self._build_header(), False, False, 0)
        self.pack_start(self._build_kpis(), False, False, 0)
        self.pack_start(self._build_content(), True, True, 0)

    # ---- montagem -------------------------------------------------------

    def _build_header(self):
        self.date_label = label("", "eyebrow")
        self.title_label = label("Hoje", "title-xl")
        titles = vbox(self.date_label, self.title_label, spacing=2)
        self.search = style(Gtk.Entry(), "input")
        self.search.set_placeholder_text("Buscar tarefa…   Ctrl K")
        self.search.set_size_request(300, -1)
        self.search.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "edit-find-symbolic")
        self.search.connect("changed", lambda e: self.emit("query-changed", e.get_text()))
        self.search.connect("key-press-event", self._on_search_key)
        new = button("＋  Nova tarefa", "btn-primary", tooltip="Adicionar uma tarefa (Ctrl N)",
                     on_click=self.focus_quick_add)
        return hbox(expand(titles), self.search, new, spacing=10)

    def _build_kpis(self):
        row = hbox(spacing=14, valign=Gtk.Align.START)
        row.set_homogeneous(True)
        self.kpi_planned = self._add_kpi(row, "Previsto para hoje")
        self.kpi_real = self._add_kpi(row, "Tempo real até agora", "text-green")
        self.kpi_pomodoros = self._add_kpi(row, "Pomodoros", "text-focus")
        self.kpi_accuracy = self._add_kpi(row, "✦ Precisão das previsões", "text-amber-dark", ai=True)
        return row

    @staticmethod
    def _add_kpi(row, title, value_class=None, ai=False):
        value = label("—", "stat-value", *( (value_class,) if value_class else () ))
        title_label = label(title, "small", "text-amber" if ai else "muted")
        card = vbox(title_label, value, spacing=2, classes=("card", "card-ai") if ai else ("card",))
        row.pack_start(card, True, True, 0)
        return value

    def _build_content(self):
        self.quick_add = QuickEntry("Despeje aqui o que veio à cabeça…", time_placeholder="tempo (Tab)")
        self.quick_add.title_entry.set_tooltip_text("Enter adiciona a tarefa · Tab vai para o tempo previsto")
        self.quick_add.connect("submitted", self._on_quick_submit)
        add_box = hbox(label("＋", "text-primary", "bold"), expand(self.quick_add), spacing=10,
                       classes=("card-dashed",))

        header = hbox(expand(label("TAREFA", "eyebrow")), label("PREVISTO", "eyebrow", width=COL_EST),
                      label("REAL", "eyebrow", width=COL_REAL), label("STATUS", "eyebrow", width=COL_STATUS),
                      spacing=12)
        header.set_margin_start(48)
        header.set_margin_end(15)

        self.task_list = TaskList(self.controller)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_overlay_scrolling(True)
        self.scroll.add(self.task_list)
        left = vbox(add_box, header, spacing=8)
        left.pack_start(self.scroll, True, True, 0)

        self.panel = TimerPanel(self.controller)
        panel_scroll = Gtk.ScrolledWindow()
        panel_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel_scroll.set_size_request(PANEL_WIDTH + 10, -1)
        panel_scroll.add(self.panel)

        row = hbox(valign=Gtk.Align.FILL, spacing=20)
        row.pack_start(left, True, True, 0)
        row.pack_start(panel_scroll, False, False, 0)
        return row

    # ---- ações ----------------------------------------------------------

    @property
    def query(self):
        return self.search.get_text().strip()

    def focus_quick_add(self):
        self.quick_add.grab_title()

    def focus_search(self):
        self.search.grab_focus()

    def _on_search_key(self, entry, event):
        if event.keyval == Gdk.KEY_Escape and entry.get_text():
            entry.set_text("")
            return True
        return False

    def _on_quick_submit(self, entry, title, minutes):
        try:
            self.controller.add_task(title, minutes, group_id=self.new_task_group)
        except ValueError as error:
            entry.show_error(str(error), on_time=minutes is None)
            if minutes is None:
                entry.time_entry.grab_focus()
            return
        entry.clear()

    # ---- atualização ----------------------------------------------------

    def refresh(self, view, context, filtered=False, group_name=None):
        """Refaz a tela com os dados novos (view = o que aparece; totais são do dia inteiro)."""
        self._view = view
        adjustment = self.scroll.get_vadjustment()
        position = adjustment.get_value()
        self.date_label.set_text(format_date_eyebrow(self.controller.today()))
        self.title_label.set_text(f"Hoje · {group_name}" if group_name else "Hoje")
        self.kpi_planned.set_text(format_minutes(view.planned_min) if view.planned_min else "—")
        self._refresh_pomodoros(view)
        self.kpi_accuracy.set_text(f"{round(view.accuracy * 100)}%" if view.accuracy is not None else "—")
        self.task_list.render(view, context["task_id"], self.controller.tracker.active_subtask_id, filtered)
        self.panel.set_context(context["task_id"], context["task_title"], context["subtask_title"],
                               context["estimate_min"], context["next_title"])
        self.refresh_live()
        GLib.idle_add(lambda: adjustment.set_value(position) and False)

    def _refresh_pomodoros(self, view):
        done = self.controller.pomodoros_today()
        target = -(-view.planned_min // self.controller.settings["work_min"]) if view.planned_min else 0
        self.kpi_pomodoros.set_text(f"{done} de {target}" if target else str(done))

    def refresh_live(self):
        """A cada segundo: tempo real ao vivo e painel do timer, sem refazer a lista."""
        if self._view is None:
            return
        self.task_list.update_live()
        total = self.task_list.live_total_seconds()
        self.kpi_real.set_text(format_minutes(round(total / 60)))
        self.panel.refresh()
