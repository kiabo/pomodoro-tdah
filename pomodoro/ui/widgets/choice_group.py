"""Grupo de escolha única: segmentado (Hoje | Amanhã | Data…) ou chips (15m 25m 45m …)."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GObject, Gtk

from ..theme import style

STYLES = ("segmented", "chips", "chips-pill")


class ChoiceGroup(Gtk.Box):
    """Botões exclusivos. Emite "changed" (com o valor) quando o usuário muda a escolha."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, items, value=None, style_name="segmented"):
        if style_name not in STYLES:
            raise ValueError(f"estilo desconhecido: {style_name}")
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0 if style_name == "segmented" else 8)
        if style_name == "segmented":
            style(self, "segmented")
            self.set_homogeneous(True)
        self._buttons = {}
        self._value = None
        self._updating = False
        for item_value, label in items:
            button = Gtk.ToggleButton(label=label)
            button.set_focus_on_click(True)
            if style_name != "segmented":
                style(button, "chip")
                if style_name == "chips-pill":
                    style(button, "chip-pill")
            button.connect("toggled", self._on_toggled, item_value)
            self.pack_start(button, style_name == "segmented", True, 0)
            self._buttons[item_value] = button
        if value is None and self._buttons:
            value = next(iter(self._buttons))
        self.set_value(value)

    @property
    def value(self):
        return self._value

    def set_value(self, value, emit=False):
        if value not in self._buttons:
            raise ValueError(f"valor fora das opções: {value!r}")
        changed = value != self._value
        self._updating = True
        try:
            for item_value, button in self._buttons.items():
                button.set_active(item_value == value)
        finally:
            self._updating = False
        self._value = value
        if changed and emit:
            self.emit("changed", value)

    def _on_toggled(self, button, item_value):
        if self._updating:
            return
        if button.get_active():
            self.set_value(item_value, emit=True)
        elif item_value == self._value:
            # Clicar na opção já escolhida não pode deixar o grupo sem seleção.
            self._updating = True
            button.set_active(True)
            self._updating = False
