"""Campo de adição rápida: [ o que precisa ser feito ]  [ tempo ]. Enter adiciona, Tab vai ao tempo."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GObject, Gtk

from ..format import parse_duration
from ..theme import style


class QuickEntry(Gtk.Box):
    """Emite "submitted"(título, minutos ou None) e "cancelled" (Esc)."""

    __gsignals__ = {
        "submitted": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        "cancelled": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, placeholder, time_placeholder="tempo", ghost=True):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        classes = ("input", "input-ghost") if ghost else ("input",)
        self.title_entry = style(Gtk.Entry(), *classes)
        self.title_entry.set_placeholder_text(placeholder)
        self.title_entry.set_hexpand(True)
        self.time_entry = style(Gtk.Entry(), *classes)
        self.time_entry.set_placeholder_text(time_placeholder)
        self.time_entry.set_width_chars(8)
        self.time_entry.set_max_width_chars(10)
        self.time_entry.set_tooltip_text("Tempo previsto: 45, 1h30, 1:30…")
        self.pack_start(self.title_entry, True, True, 0)
        self.pack_start(self.time_entry, False, False, 0)
        for entry in (self.title_entry, self.time_entry):
            entry.connect("activate", lambda *_: self.submit())
            entry.connect("key-press-event", self._on_key)
            entry.connect("changed", lambda e: e.get_style_context().remove_class("entry-error"))

    def grab_title(self):
        self.title_entry.grab_focus()

    def show_error(self, message, on_time=True):
        entry = self.time_entry if on_time else self.title_entry
        style(entry, "entry-error")
        entry.set_tooltip_text(message)

    def submit(self):
        title = self.title_entry.get_text().strip()
        if not title:
            return False
        time_text = self.time_entry.get_text().strip()
        minutes = None
        if time_text:
            minutes = parse_duration(time_text)
            if minutes is None:
                self.show_error("Não entendi o tempo. Use 45, 1h30 ou 1:30.")
                self.time_entry.grab_focus()
                return False
        self.emit("submitted", title, minutes)
        return True

    def clear(self):
        self.title_entry.set_text("")
        self.time_entry.set_text("")
        self.title_entry.grab_focus()

    def _on_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.emit("cancelled")
            return True
        return False
