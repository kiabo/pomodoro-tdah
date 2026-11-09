"""Cola do app com o sistema: ícone na bandeja, notificações, som e a janela principal."""

import signal
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, AyatanaAppIndicator3 as AppIndicator3, Notify

from .controller import Controller
from .timer import PHASE_LABELS, Phase
from .ui.format import format_clock
from .ui.main_window import MainWindow
from .ui.theme import load_theme

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"

PHASE_ICON = {
    Phase.WORK: "pomodoro-work",
    Phase.SHORT_BREAK: "pomodoro-break",
    Phase.LONG_BREAK: "pomodoro-break-long",
}


class PomodoroApp:
    def __init__(self, start_hidden=False):
        Notify.init("Pomodoro")
        load_theme()
        self.controller = Controller(notify=self._notify, play_sound=self._play_sound)
        self.controller.subscribe(self._on_controller_event)

        self.indicator = AppIndicator3.Indicator.new(
            "pomodoro-indicator",
            "pomodoro-idle",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(str(ICON_DIR))
        self.indicator.set_icon_full("pomodoro-idle", "Pomodoro")
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.window = MainWindow(self.controller)
        self._build_menu()
        self._update_indicator()
        if not start_hidden:
            self.window.present_today()

    # ---- ícone da bandeja -----------------------------------------------

    def _build_menu(self):
        menu = Gtk.Menu()

        def add(text, callback):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda *_: callback())
            menu.append(item)
            return item

        add("Abrir o Foco", self.window.present_today)
        menu.append(Gtk.SeparatorMenuItem())
        self.toggle_item = add("Iniciar", self.controller.toggle_timer)
        add("Pular fase", self.controller.skip_phase)
        add("Zerar o relógio", self.controller.reset_phase)
        add("Reiniciar a sessão inteira…", self.window.confirm_restart)
        menu.append(Gtk.SeparatorMenuItem())
        add("Sair", self.quit)
        menu.show_all()
        self.indicator.set_menu(menu)

    def _on_controller_event(self, kind):
        if kind in ("tick", "phase", "settings"):
            self._update_indicator()

    def _update_indicator(self):
        timer = self.controller.timer
        self.indicator.set_label(format_clock(timer.remaining), "+88:88")
        if timer.running:
            icon = PHASE_ICON[timer.phase]
        else:
            icon = "pomodoro-paused" if timer.started else "pomodoro-idle"
        self.indicator.set_icon_full(icon, PHASE_LABELS[timer.phase])
        self.toggle_item.set_label("Pausar" if timer.running else ("Retomar" if timer.started else "Iniciar"))

    # ---- sistema ----------------------------------------------------------

    def _notify(self, message):
        if not self.controller.settings.get("system_notifications", True):
            return
        try:
            Notify.Notification.new("Pomodoro", message, None).show()
        except Exception:
            pass

    def _play_sound(self, sound):
        if not sound:
            return
        try:
            subprocess.Popen(
                ["canberra-gtk-play", "-i", sound],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    # ---- ciclo de vida ----------------------------------------------------

    def quit(self, *_args):
        self.controller.shutdown()
        Gtk.main_quit()

    def run(self):
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        Gtk.main()
