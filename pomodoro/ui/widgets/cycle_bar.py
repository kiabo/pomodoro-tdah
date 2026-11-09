"""Barra do ciclo do pomodoro: um segmento por foco/pausa, proporcional à duração."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..chart_math import cycle_bar_layout, cycle_segments
from ..theme import COLORS, hex_to_rgb

SEGMENT_COLORS = {"work": COLORS["focus"], "short": COLORS["green"], "long": COLORS["primary"]}
SEGMENT_NAMES = {"work": "Foco", "short": "Pausa curta", "long": "Pausa longa"}
HEIGHT = 10


class CycleBar(Gtk.DrawingArea):
    def __init__(self, work_min=25, short_min=5, long_min=15, cycles=4):
        super().__init__()
        self._segments = []
        self.set_size_request(-1, HEIGHT)
        self.set_hexpand(True)
        self.set_has_tooltip(True)
        self.connect("draw", self._on_draw)
        self.connect("query-tooltip", self._on_tooltip)
        self.set_cycle(work_min, short_min, long_min, cycles)

    @property
    def segments(self):
        return list(self._segments)

    def set_cycle(self, work_min, short_min, long_min, cycles):
        self._segments = cycle_segments(work_min, short_min, long_min, cycles)
        self.queue_draw()

    def _on_draw(self, widget, cr):
        for item in cycle_bar_layout(self._segments, widget.get_allocated_width()):
            self._rounded(cr, item["x"], 0, item["w"], HEIGHT)
            cr.set_source_rgb(*hex_to_rgb(SEGMENT_COLORS[item["kind"]]))
            cr.fill()
        return False

    @staticmethod
    def _rounded(cr, x, y, w, h, r=3):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()

    def _on_tooltip(self, widget, x, _y, _keyboard, tooltip):
        for item in cycle_bar_layout(self._segments, widget.get_allocated_width()):
            if item["x"] <= x <= item["x"] + item["w"]:
                tooltip.set_text(f"{SEGMENT_NAMES[item['kind']]} · {item['minutes']} min")
                return True
        return False
