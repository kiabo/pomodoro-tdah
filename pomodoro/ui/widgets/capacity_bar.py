"""Barra da capacidade do dia: o que você previu (índigo) e o que a IA acha que vai faltar (âmbar)."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..chart_math import capacity_widths
from ..theme import COLORS, hex_to_rgb

HEIGHT = 10


class CapacityBar(Gtk.DrawingArea):
    def __init__(self, planned_fraction=0.0, ai_fraction=0.0):
        super().__init__()
        self.planned_fraction = planned_fraction
        self.ai_fraction = ai_fraction
        self.set_size_request(-1, HEIGHT)
        self.set_hexpand(True)
        self.connect("draw", self._on_draw)

    def set_fractions(self, planned_fraction, ai_fraction):
        self.planned_fraction = planned_fraction
        self.ai_fraction = ai_fraction
        self.queue_draw()

    def _on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        planned, extra = capacity_widths(width, self.planned_fraction, self.ai_fraction)
        cr.new_sub_path()                      # tudo é recortado pelo trilho arredondado
        r = HEIGHT / 2
        cr.arc(r, r, r, 1.5708, 4.7124)
        cr.arc(width - r, r, r, -1.5708, 1.5708)
        cr.close_path()
        cr.clip()
        for x, w, color in ((0, width, COLORS["chip"]), (0, planned, COLORS["primary"]),
                            (planned, extra, COLORS["amber"])):
            if w > 0:
                cr.rectangle(x, 0, w, HEIGHT)
                cr.set_source_rgb(*hex_to_rgb(color))
                cr.fill()
        return False
