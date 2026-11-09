"""Paleta de cores de grupo: bolinhas de escolha única (a escolhida ganha um anel)."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk

from ..theme import GROUP_COLORS, hex_to_rgb, style

SIZE = 30


class _Swatch(Gtk.ToggleButton):
    def __init__(self, color):
        super().__init__()
        style(self, "swatch")
        self.color = color
        self._area = Gtk.DrawingArea()
        self._area.set_size_request(SIZE, SIZE)
        self._area.connect("draw", self._on_draw)
        self.add(self._area)
        self.set_tooltip_text(color)
        self.connect("toggled", lambda *_: self._area.queue_draw())

    def _on_draw(self, _widget, cr):
        rgb = hex_to_rgb(self.color)
        cx = cy = SIZE / 2
        cr.set_source_rgb(*rgb)
        cr.arc(cx, cy, 10 if self.get_active() else 12, 0, 6.2832)
        cr.fill()
        if self.get_active():
            cr.set_line_width(2)
            cr.arc(cx, cy, 13.5, 0, 6.2832)
            cr.stroke()
        return False


class ColorPalette(Gtk.Box):
    """Emite "changed"(cor em #RRGGBB) quando o usuário escolhe outra."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, value=None, colors=GROUP_COLORS):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._colors = list(colors)
        self._swatches = {}
        self._value = None
        self._updating = False
        for color in self._colors:
            self._add(color)
        self.set_value(value or self._colors[0])

    def _add(self, color):
        swatch = _Swatch(color)
        swatch.set_focus_on_click(True)
        swatch.connect("toggled", self._on_toggled, color)
        self._swatches[color] = swatch
        self.pack_start(swatch, False, False, 0)
        swatch.show_all()

    @property
    def value(self):
        return self._value

    def set_value(self, color, emit=False):
        color = color.upper()
        if color not in self._swatches:        # cor fora da paleta (ex.: vinda de importação): vira mais uma bolinha
            self._add(color)
        changed = color != self._value
        self._updating = True
        for swatch_color, swatch in self._swatches.items():
            swatch.set_active(swatch_color == color)
        self._updating = False
        self._value = color
        if changed and emit:
            self.emit("changed", color)

    def _on_toggled(self, swatch, color):
        if self._updating:
            return
        if swatch.get_active():
            self.set_value(color, emit=True)
        else:
            self._updating = True               # clicar na cor atual não a desmarca
            swatch.set_active(True)
            self._updating = False
