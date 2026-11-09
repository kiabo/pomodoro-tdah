"""Anel de progresso do timer: trilho + arco, com o tempo e uma legenda no centro."""

import math

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..chart_math import ring_arc
from ..theme import COLORS, hex_to_rgb, style


class ProgressRing(Gtk.Overlay):
    def __init__(self, size=200, thickness=10, color=COLORS["focus"], dark=True):
        super().__init__()
        style(self, "progress-ring")
        if dark:
            style(self, "on-dark")
        self._thickness = thickness
        self._fraction = 0.0
        self._color = hex_to_rgb(color)
        self._track = hex_to_rgb(COLORS["dark_track"] if dark else COLORS["chip"])
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)

        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self.add(self._area)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        center.set_valign(Gtk.Align.CENTER)
        center.set_halign(Gtk.Align.CENTER)
        self.time_label = style(Gtk.Label(label="25:00"), "ring-time")
        self.caption_label = style(Gtk.Label(label=""), "ring-caption")
        center.pack_start(self.time_label, False, False, 0)
        center.pack_start(self.caption_label, False, False, 0)
        self.add_overlay(center)
        self.set_overlay_pass_through(center, True)

    @property
    def fraction(self):
        return self._fraction

    def set_fraction(self, fraction):
        self._fraction = min(max(float(fraction), 0.0), 1.0)
        self._area.queue_draw()

    def set_color(self, color):
        self._color = hex_to_rgb(color)
        self._area.queue_draw()

    def set_time(self, text):
        self.time_label.set_text(text)

    def set_caption(self, text):
        self.caption_label.set_text(text)

    def _on_draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        cx, cy = width / 2, height / 2
        radius = (min(width, height) - self._thickness) / 2
        cr.set_line_width(self._thickness)
        cr.set_source_rgb(*self._track)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if self._fraction > 0:
            start, end = ring_arc(self._fraction)
            cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND
            cr.set_source_rgb(*self._color)
            cr.arc(cx, cy, radius, start, end)
            cr.stroke()
        return False
