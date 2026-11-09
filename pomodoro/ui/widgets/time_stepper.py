"""Seletor de tempo em minutos: [−]  1h 30m  [+], com digitação livre ('1h30', '45', '1:30')."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GObject, Gtk

from ..format import format_minutes, parse_duration
from ..theme import style


class TimeStepper(Gtk.Box):
    """Emite "value-changed" (minutos) quando o usuário muda o valor."""

    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, minutes=0, step=5, minimum=0, maximum=24 * 60):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._step = step
        self._min = minimum
        self._max = maximum
        self._minutes = None

        self._minus = style(Gtk.Button(label="−"), "btn", "btn-step")
        self._plus = style(Gtk.Button(label="+"), "btn", "btn-step")
        self._entry = style(Gtk.Entry(), "stepper-entry")
        self._entry.set_width_chars(7)
        self._entry.set_max_width_chars(9)
        self._entry.set_alignment(0.5)
        self._entry.set_has_frame(False)
        self._minus.set_tooltip_text("Menos")
        self._plus.set_tooltip_text("Mais")
        self._entry.set_tooltip_text("Digite um tempo: 45, 1h30, 1:30…")

        self._minus.connect("clicked", lambda *_: self._bump(-1))
        self._plus.connect("clicked", lambda *_: self._bump(+1))
        self._entry.connect("activate", lambda *_: self._commit_text())
        self._entry.connect("focus-out-event", self._on_focus_out)
        self._entry.connect("key-press-event", self._on_key)

        self.pack_start(self._minus, False, False, 0)
        self.pack_start(self._entry, True, True, 0)
        self.pack_start(self._plus, False, False, 0)
        self.set_minutes(minutes)

    @property
    def minutes(self):
        return self._minutes

    def _clamp(self, minutes):
        return min(max(int(minutes), self._min), self._max)

    def set_minutes(self, minutes, emit=False):
        minutes = self._clamp(minutes)
        changed = minutes != self._minutes
        self._minutes = minutes
        self._entry.set_text(format_minutes(minutes))
        self._minus.set_sensitive(minutes > self._min)
        self._plus.set_sensitive(minutes < self._max)
        if changed and emit:
            self.emit("value-changed", minutes)

    def _bump(self, direction):
        self.set_minutes(self._minutes + direction * self._step, emit=True)

    def _commit_text(self):
        parsed = parse_duration(self._entry.get_text())
        if parsed is None:
            self._entry.set_text(format_minutes(self._minutes))  # texto inválido: volta ao valor atual
        else:
            self.set_minutes(parsed, emit=True)
            self._entry.set_text(format_minutes(self._minutes))

    def _on_focus_out(self, *_args):
        self._commit_text()
        return False

    def _on_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Up:
            self._bump(+1)
            return True
        if event.keyval == Gdk.KEY_Down:
            self._bump(-1)
            return True
        return False
