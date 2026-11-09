"""Lista suspensa no estilo do design (campo branco com ▾) e escolha de data com calendário."""

from datetime import date, timedelta

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk

from ..format import describe_day
from ..layout import expand, hbox, label, vbox
from ..theme import style


class _DropdownButton(Gtk.MenuButton):
    """Botão que mostra um texto com ▾ e abre um popover."""

    def __init__(self, width=None):
        super().__init__()
        style(self, "select")
        self._text = label("", ellipsize=True)
        self.add(hbox(expand(self._text), label("▾", "muted", "small"), spacing=8))
        self.set_use_popover(True)
        self.popover = Gtk.Popover()
        self.set_popover(self.popover)
        if width:
            self.set_size_request(width, -1)
        self.show_all()

    def set_text(self, text):
        self._text.set_text(text)

    def get_text(self):
        return self._text.get_text()


class Select(_DropdownButton):
    """Seleciona um valor de uma lista [(valor, texto)]. Emite "changed"(valor)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, items, value=None, width=None):
        super().__init__(width)
        self._items = []
        self._value = None
        self._buttons = {}
        self._updating = False
        self.set_items(items, value)

    @property
    def value(self):
        return self._value

    @property
    def items(self):
        return list(self._items)

    def set_items(self, items, value=None):
        self._items = list(items)
        box = vbox(spacing=2)
        box.set_border_width(6)
        self._buttons = {}
        for item_value, text in self._items:
            button = style(Gtk.ToggleButton(label=text), "select-item")
            button.get_child().set_xalign(0.0)
            button.connect("toggled", self._on_item_toggled, item_value)
            self._buttons[item_value] = button
            box.pack_start(button, False, True, 0)
        box.show_all()
        old = self.popover.get_child()
        if old is not None:
            self.popover.remove(old)
        self.popover.add(box)
        if value is None and self._items:
            value = self._items[0][0]
        self.set_value(value)

    def set_value(self, value, emit=False):
        if value not in self._buttons:
            raise ValueError(f"valor fora das opções: {value!r}")
        changed = value != self._value
        self._value = value
        self._updating = True
        try:
            for item_value, button in self._buttons.items():
                button.set_active(item_value == value)
        finally:
            self._updating = False
        self.set_text(dict(self._items)[value])
        if changed and emit:
            self.emit("changed", value)

    def _on_item_toggled(self, button, item_value):
        if self._updating:
            return
        self.popover.popdown()
        if button.get_active():
            self.set_value(item_value, emit=True)
        else:
            self._updating = True               # clicar no item atual não pode deixá-lo desmarcado
            button.set_active(True)
            self._updating = False


class DatePicker(_DropdownButton):
    """Escolha de data: atalhos (Hoje, Amanhã, Sem data) e calendário. Emite "changed"(date ou None)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, day=None, today=date.today, allow_none=True, width=None):
        super().__init__(width)
        self._today = today
        self._day = None
        self._ignore_calendar = False
        self._calendar = Gtk.Calendar()
        self._calendar.connect("day-selected", self._on_calendar_selected)
        self._calendar.connect("month-changed", self._on_month_changed)

        shortcuts = hbox(spacing=6)
        for text, callback in (("Hoje", lambda: self.set_date(self._today(), emit=True)),
                               ("Amanhã", lambda: self.set_date(self._tomorrow(), emit=True))):
            shortcuts.pack_start(self._shortcut(text, callback), False, False, 0)
        if allow_none:
            shortcuts.pack_start(self._shortcut("Sem data", lambda: self.set_date(None, emit=True)), False, False, 0)
        content = vbox(shortcuts, self._calendar, spacing=8)
        content.set_border_width(10)
        content.show_all()
        self.popover.add(content)
        self.set_date(day)

    def _tomorrow(self):
        return self._today() + timedelta(days=1)

    def _shortcut(self, text, callback):
        button = style(Gtk.Button(label=text), "btn", "btn-secondary")
        button.connect("clicked", lambda *_: (callback(), self.popover.popdown()))
        return button

    @property
    def date(self):
        return self._day

    def set_date(self, day, emit=False):
        changed = day != self._day
        self._day = day
        self.set_text(describe_day(day, self._today()))
        if day is not None:
            self._ignore_calendar = True
            self._calendar.select_month(day.month - 1, day.year)
            self._calendar.select_day(day.day)
            self._ignore_calendar = False
        if changed and emit:
            self.emit("changed", day)

    def _on_month_changed(self, _calendar):
        # Navegar entre meses também dispara "day-selected": não conta como escolha.
        self._ignore_calendar = True
        GLib.idle_add(self._stop_ignoring)

    def _stop_ignoring(self):
        self._ignore_calendar = False
        return False

    def _on_calendar_selected(self, calendar):
        if self._ignore_calendar:
            return
        year, month, day = calendar.get_date()
        self.set_date(date(year, month + 1, day), emit=True)
        self.popover.popdown()
