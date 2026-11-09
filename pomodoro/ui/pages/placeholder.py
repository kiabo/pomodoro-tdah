"""Páginas que ainda não têm a tela completa, e o painel básico de configurações."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..layout import expand, hbox, label, vbox
from ..theme import style
from ..widgets import TimeStepper


class PlaceholderPage(Gtk.Box):
    def __init__(self, eyebrow, title, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(32)
        self.pack_start(vbox(label(eyebrow, "eyebrow"), label(title, "title-xl"), spacing=2), False, False, 0)
        card = vbox(label(message, "text2", wrap=True), classes=("card-dashed",))
        self.pack_start(card, False, False, 0)


class BasicSettingsPage(Gtk.Box):
    """Ajuste dos tempos do ciclo. A tela completa de configurações chega na Fase 6."""

    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.controller = controller
        self.set_border_width(32)
        self.pack_start(vbox(label("PREFERÊNCIAS", "eyebrow"), label("Configurações", "title-xl"), spacing=2),
                        False, False, 0)
        settings = controller.settings
        card = vbox(label("Ciclo do Pomodoro", "card-title"), spacing=14, classes=("card", "card-lg"))
        for key, text, lo, hi in (("work_min", "Foco", 1, 180), ("short_break_min", "Pausa curta", 1, 60),
                                  ("long_break_min", "Pausa longa", 1, 120)):
            stepper = TimeStepper(settings[key], step=1, minimum=lo, maximum=hi)
            stepper.connect("value-changed", lambda _s, value, k=key: controller.apply_settings({k: value}))
            card.pack_start(hbox(expand(label(text)), stepper, spacing=12), False, False, 0)
        cycles = Gtk.SpinButton.new_with_range(1, 12, 1)
        cycles.set_value(settings["cycles_before_long_break"])
        style(cycles, "input")
        cycles.connect("value-changed", lambda w: controller.apply_settings(
            {"cycles_before_long_break": w.get_value_as_int()}))
        card.pack_start(hbox(expand(label("Turnos até a pausa longa")), cycles, spacing=12), False, False, 0)
        card.set_size_request(460, -1)
        card.set_halign(Gtk.Align.START)
        self.pack_start(card, False, False, 0)
        self.pack_start(label("As demais opções (apoio para TDAH, modo compacto, sons, IA) chegam na Fase 6.",
                              "small", "muted"), False, False, 0)
