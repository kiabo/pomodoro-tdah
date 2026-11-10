"""Widgets pequenos: interruptor, barra fina, ponto de cor do grupo e pílula de status."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..theme import hex_to_rgb, style

BAR_COLORS = ("primary", "green", "mint", "focus", "amber", "pink")


def make_toggle(active=False, on_toggled=None, tooltip=None):
    """Interruptor de 38x22 (Gtk.Switch estilizado). on_toggled recebe o novo valor (bool)."""
    switch = style(Gtk.Switch(), "toggle")
    switch.set_valign(Gtk.Align.CENTER)
    switch.set_active(active)
    if tooltip:
        switch.set_tooltip_text(tooltip)
        switch.get_accessible().set_name(tooltip)
    if on_toggled:
        switch.connect("notify::active", lambda w, _p: on_toggled(w.get_active()))
    return switch


def make_bar(fraction=0.0, color="primary", dark=False, thin=False, amber_track=False):
    """Barra de progresso fina. color: um de BAR_COLORS; dark usa o trilho escuro."""
    if color not in BAR_COLORS:
        raise ValueError(f"cor de barra desconhecida: {color}")
    bar = style(Gtk.ProgressBar(), "bar", f"bar-{color}")
    if dark:
        style(bar, "bar-dark")
    if thin:
        style(bar, "bar-thin")
    if amber_track:
        style(bar, "bar-amber-track")
    set_bar_fraction(bar, fraction)
    return bar


def set_bar_fraction(bar, fraction):
    bar.set_fraction(min(max(float(fraction), 0.0), 1.0))


class GroupDot(Gtk.DrawingArea):
    """Quadradinho arredondado com a cor do grupo."""

    def __init__(self, color="#5B5BD6", size=10, radius=3):
        super().__init__()
        self._size = size
        self._radius = radius
        self._rgb = hex_to_rgb(color)
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self._on_draw)

    @property
    def color(self):
        return "#%02X%02X%02X" % tuple(round(c * 255) for c in self._rgb)

    def set_color(self, color):
        self._rgb = hex_to_rgb(color)
        self.queue_draw()

    def _on_draw(self, _widget, cr):
        s, r = self._size, min(self._radius, self._size / 2)
        cr.new_sub_path()
        cr.arc(s - r, r, r, -1.5708, 0)
        cr.arc(s - r, s - r, r, 0, 1.5708)
        cr.arc(r, s - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgb(*self._rgb)
        cr.fill()
        return False


STATUS_LABELS = {
    "todo": "A fazer",
    "doing": "Em foco",
    "done": "Concluída",
    "discarded": "Descartada",
}


class StatusPill(Gtk.Label):
    """Pílula com o status da tarefa (todo, doing, done, discarded) nas cores do design."""

    def __init__(self, status="todo"):
        super().__init__()
        style(self, "pill")
        self.set_halign(Gtk.Align.START)
        self._status = None
        self.set_status(status)

    @property
    def status(self):
        return self._status

    def set_status(self, status):
        if status not in STATUS_LABELS:
            raise ValueError(f"status desconhecido: {status}")
        context = self.get_style_context()
        if self._status:
            context.remove_class(f"pill-{self._status}")
        context.add_class(f"pill-{status}")
        self._status = status
        text = ("● " if status == "doing" else "") + STATUS_LABELS[status]
        self.set_text(text)
