"""Barra lateral: marca, mini-timer, navegação, grupos e a nota de capacidade do dia."""

from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk

from ..stats import capacity_level
from ..timer import Phase
from .format import format_clock, format_minutes, interval_text, phase_eyebrow
from .layout import FixedWidthBox, button, expand, hbox, label, vbox
from .theme import COLORS, style
from .widgets import GroupDot, make_bar, set_bar_fraction

NAV_ITEMS = [
    ("today", "Hoje"),
    ("plan", "Revisar e planejar amanhã"),
    ("groups", "Grupos"),
    ("analysis", "✦ Análise da IA"),
    ("settings", "Configurações"),
]
WIDTH = 260


def capacity_text(planned_min, free_min):
    level, over = capacity_level(planned_min, free_min)
    if level == "empty":
        return "Nada planejado para hoje ainda. Despeje o que precisa ser feito."
    head = f"Hoje: {format_minutes(planned_min)} previstas para {format_minutes(free_min)} livres."
    if level == "ok":
        return f"{head} Dá tempo, com folga para pausas."
    if level == "tight":
        return f"{head} Dá tempo, mas sem muita folga."
    return f"{head} Passa {format_minutes(over)} do tempo livre. Vale adiar algo para amanhã."


class Sidebar(FixedWidthBox):
    """Emite "navigate"(página) e "group-selected"(id do grupo ou None)."""

    __gsignals__ = {
        "navigate": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "group-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, controller):
        super().__init__(WIDTH, orientation=Gtk.Orientation.VERTICAL, spacing=18)
        style(self, "sidebar")
        self.controller = controller
        self._page = "today"
        self._group = None
        self._updating = False
        self._focus_title = None
        self._nav_buttons = {}
        self._nav_counts = {}
        self._nav_dots = {}

        brand = hbox(GroupDot(COLORS["focus"], size=22, radius=11), label("Foco", "title-md"), spacing=10)
        self.pack_start(brand, False, False, 0)
        self.pack_start(self._build_mini_timer(), False, False, 0)
        self.pack_start(self._build_nav(), False, False, 0)
        self.pack_start(self._build_groups(), False, False, 0)
        self.pack_end(self._build_tip(), False, False, 0)

    # ---- montagem -------------------------------------------------------

    def _build_mini_timer(self):
        self.mini_eyebrow = label("", "eyebrow", "text-amber-bright")
        self.mini_time = label("25:00", "title-lg", "text-on-dark")
        self.mini_task = label("", "small", "text-on-dark", ellipsize=True)
        self.mini_bar = make_bar(0, "focus", dark=True, thin=True)
        self.mini_next = label("", "caption", "text-dark-muted", ellipsize=True)
        return vbox(self.mini_eyebrow, self.mini_time, self.mini_task, self.mini_bar, self.mini_next,
                    spacing=6, classes=("card-mini",))

    def _build_nav(self):
        box = vbox(spacing=2)
        for page, text in NAV_ITEMS:
            count = label("", "caption", "muted")
            self._nav_counts[page] = count
            dot = GroupDot(COLORS["primary"] if page == self._page else COLORS["line_dashed"], size=8, radius=4)
            self._nav_dots[page] = dot
            content = hbox(dot, expand(label(text)), count, spacing=10)
            item = style(Gtk.ToggleButton(), "nav-item")
            item.add(content)
            item.set_active(page == self._page)
            item.connect("toggled", self._on_nav_toggled, page)
            self._nav_buttons[page] = item
            box.pack_start(item, False, False, 0)
        return box

    def _build_groups(self):
        header = hbox(expand(label("GRUPOS", "eyebrow")),
                      button("＋", "btn-ghost", tooltip="Criar ou editar grupos",
                             on_click=lambda: self.set_page("groups", emit=True)), spacing=4)
        header.set_margin_start(10)
        self._group_box = vbox(spacing=2)
        self._group_buttons = {}
        return vbox(header, self._group_box, spacing=6)

    def _build_tip(self):
        self.tip_label = label("", "caption", "text-amber-dark", wrap=True)
        return vbox(self.tip_label, classes=("card", "card-ai"))

    # ---- navegação ------------------------------------------------------

    def _on_nav_toggled(self, widget, page):
        if self._updating:
            return
        if widget.get_active():
            self.set_page(page, emit=True)
        else:
            self._updating = True
            widget.set_active(True)        # não deixa a navegação sem item ativo
            self._updating = False

    def set_page(self, page, emit=False):
        if page not in self._nav_buttons:
            raise ValueError(f"página desconhecida: {page}")
        self._updating = True
        for name, item in self._nav_buttons.items():
            item.set_active(name == page)
            self._nav_dots[name].set_color(COLORS["primary"] if name == page else COLORS["line_dashed"])
        self._updating = False
        changed = page != self._page
        self._page = page
        if emit and changed:
            self.emit("navigate", page)

    @property
    def page(self):
        return self._page

    @property
    def group_filter(self):
        return self._group

    def _on_group_toggled(self, widget, group_id):
        if self._updating:
            return
        self._group = group_id if widget.get_active() else None
        self._sync_group_buttons()
        self.set_page("today", emit=True)
        self.emit("group-selected", self._group)

    def _sync_group_buttons(self):
        self._updating = True
        for group_id, item in self._group_buttons.items():
            item.set_active(group_id == self._group)
        self._updating = False

    # ---- dados ----------------------------------------------------------

    def set_data(self, view, free_min):
        """Contagens, lista de grupos e nota de capacidade (quando os dados mudam)."""
        self._nav_counts["today"].set_text(str(view.task_count) if view.task_count else "")
        for child in self._group_box.get_children():
            self._group_box.remove(child)
            child.destroy()
        self._group_buttons = {}
        ids = [g["id"] for g in view.all_groups]
        if self._group not in ids:
            self._group = None
        for group in view.all_groups:
            count = view.group_counts.get(group["id"], 0)
            content = hbox(GroupDot(group["color"]), expand(label(group["name"], ellipsize=True)),
                           label(str(count) if count else "", "caption", "muted"), spacing=10)
            item = style(Gtk.ToggleButton(), "nav-item")
            item.add(content)
            item.set_active(group["id"] == self._group)
            item.set_tooltip_text("Mostrar só este grupo")
            item.connect("toggled", self._on_group_toggled, group["id"])
            self._group_buttons[group["id"]] = item
            self._group_box.pack_start(item, False, False, 0)
        self._group_box.show_all()
        self.tip_label.set_text("✦ " + capacity_text(view.planned_min, free_min))

    def set_focus_title(self, title):
        self._focus_title = title
        self.refresh_timer()

    def refresh_timer(self):
        timer = self.controller.timer
        settings = self.controller.settings
        self.mini_eyebrow.set_text(phase_eyebrow(
            timer.phase, timer.running, timer.started, timer.cycle,
            settings["cycles_before_long_break"], overtime=timer.in_overtime, compact=True,
        ))
        self.mini_time.set_text(format_clock(timer.remaining))
        if timer.phase == Phase.WORK:
            self.mini_task.set_text(self._focus_title or "Foco livre")
        else:
            self.mini_task.set_text("Pausa")
        total = max(timer.phase_total, 1)
        set_bar_fraction(self.mini_bar, 1.0 if timer.in_overtime else (total - timer.remaining) / total)
        nxt = timer.next_intervals(now=datetime.now(), count=1)[0]
        self.mini_next.set_text(interval_text(nxt))
