"""Gráfico de barras previsto × real por dia (tela de análise da IA)."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, PangoCairo

from ..chart_math import bar_layout
from ..format import format_minutes
from ..theme import COLORS, hex_to_rgb, style

BAR_RGB = {
    "planned": hex_to_rgb(COLORS["primary_soft"]),
    "real_ok": hex_to_rgb(COLORS["primary"]),
    "real_over": hex_to_rgb(COLORS["focus"]),
}
TOP_RADIUS = 4


class BarChart(Gtk.DrawingArea):
    def __init__(self, days=None, height=200):
        super().__init__()
        style(self, "chart")
        self._days = []
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self.set_has_tooltip(True)
        self.connect("draw", self._on_draw)
        self.connect("query-tooltip", self._on_tooltip)
        self.set_days(days or [])

    @property
    def days(self):
        return list(self._days)

    def set_days(self, days):
        """days: [{"label": "Seg", "planned": min, "real": min}, ...]"""
        for day in days:
            if not {"label", "planned", "real"} <= set(day):
                raise ValueError("cada dia precisa de label, planned e real")
        self._days = [dict(d) for d in days]
        self.queue_draw()

    def _layout(self):
        return bar_layout(self._days, self.get_allocated_width(), self.get_allocated_height())

    def _on_draw(self, widget, cr):
        context = widget.get_style_context()
        text_rgba = context.get_color(Gtk.StateFlags.NORMAL)
        font = context.get_property("font", Gtk.StateFlags.NORMAL)
        for day in self._layout():
            for bar in day["bars"]:
                if bar["h"] <= 0:
                    continue
                self._top_rounded_rect(cr, bar["x"], bar["y"], bar["w"], bar["h"])
                cr.set_source_rgb(*BAR_RGB[bar["kind"]])
                cr.fill()
            layout = widget.create_pango_layout(day["label"])
            layout.set_font_description(font)
            text_w, text_h = layout.get_pixel_size()
            cr.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            cr.move_to(day["label_x"] - text_w / 2, widget.get_allocated_height() - text_h - 2)
            PangoCairo.show_layout(cr, layout)
        return False

    @staticmethod
    def _top_rounded_rect(cr, x, y, w, h):
        r = min(TOP_RADIUS, w / 2, h)
        cr.new_sub_path()
        cr.move_to(x, y + h)
        cr.line_to(x, y + r)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.arc(x + w - r, y + r, r, 4.7124, 0)
        cr.line_to(x + w, y + h)
        cr.close_path()

    def _on_tooltip(self, _widget, x, _y, _keyboard, tooltip):
        for day, data in zip(self._layout(), self._days):
            if day["pair_x0"] - 4 <= x <= day["pair_x1"] + 4:
                tooltip.set_text(
                    f"{data['label']}: previsto {format_minutes(data['planned'])} · "
                    f"real {format_minutes(data['real'])}"
                )
                return True
        return False
