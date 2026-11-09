import signal
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, AyatanaAppIndicator3 as AppIndicator3, Notify

from . import storage
from .timer import PomodoroTimer, Phase, PHASE_LABELS
from .window import MainWindow

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"

PHASE_ICON = {
    Phase.WORK: "pomodoro-work",
    Phase.SHORT_BREAK: "pomodoro-break",
    Phase.LONG_BREAK: "pomodoro-break-long",
}


class PomodoroApp:
    def __init__(self):
        Notify.init("Pomodoro")

        self.settings = storage.load_settings()
        self.tasks = storage.load_tasks()
        self.active_task_id = None

        self.timer = PomodoroTimer(self.settings, self.on_tick, self.on_phase_change)

        self.indicator = AppIndicator3.Indicator.new(
            "pomodoro-indicator",
            "pomodoro-idle",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(str(ICON_DIR))
        self.indicator.set_icon_full("pomodoro-idle", "Pomodoro")
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.window = MainWindow(self)
        self._build_menu()
        self.on_tick()

    # ---- indicator menu -------------------------------------------------

    def _build_menu(self):
        menu = Gtk.Menu()

        show_item = Gtk.MenuItem(label="Mostrar painel")
        show_item.connect("activate", lambda *_: self.window.toggle())
        menu.append(show_item)

        menu.append(Gtk.SeparatorMenuItem())

        self.toggle_item = Gtk.MenuItem(label="Iniciar")
        self.toggle_item.connect("activate", lambda *_: self.timer.toggle())
        menu.append(self.toggle_item)

        skip_item = Gtk.MenuItem(label="Pular fase")
        skip_item.connect("activate", lambda *_: self.timer.skip())
        menu.append(skip_item)

        reset_item = Gtk.MenuItem(label="Resetar relógio")
        reset_item.connect("activate", lambda *_: self.timer.reset_phase())
        menu.append(reset_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Sair")
        quit_item.connect("activate", lambda *_: self.quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    # ---- timer callbacks --------------------------------------------------

    def on_tick(self):
        mm, ss = divmod(max(self.timer.remaining, 0), 60)
        self.indicator.set_label(f"{mm:02d}:{ss:02d}", "88:88")

        if self.timer.running:
            icon = PHASE_ICON[self.timer.phase]
        else:
            icon = "pomodoro-paused" if self.timer.remaining < self.timer._phase_duration(self.timer.phase) else "pomodoro-idle"
        self.indicator.set_icon_full(icon, PHASE_LABELS[self.timer.phase])

        self.toggle_item.set_label("Pausar" if self.timer.running else "Retomar")
        self.window.refresh_timer()

    def on_phase_change(self, auto):
        label = PHASE_LABELS[self.timer.phase]
        try:
            Notify.Notification.new("Pomodoro", f"Hora de: {label}", None).show()
        except Exception:
            pass
        self._play_beep()
        self.window.refresh_timer()

    def _play_beep(self):
        try:
            subprocess.Popen(
                ["canberra-gtk-play", "-i", "complete"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    # ---- task CRUD ----------------------------------------------------

    def add_task(self, title):
        self.tasks.append({"id": storage.new_task_id(), "title": title, "done": False})
        storage.save_tasks(self.tasks)
        self.window.refresh_tasks()

    def edit_task(self, task_id, new_title):
        for task in self.tasks:
            if task["id"] == task_id:
                task["title"] = new_title
                break
        storage.save_tasks(self.tasks)
        self.window.refresh_tasks()

    def delete_task(self, task_id):
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if self.active_task_id == task_id:
            self.active_task_id = None
        storage.save_tasks(self.tasks)
        self.window.refresh_tasks()

    def toggle_task_done(self, task_id):
        for task in self.tasks:
            if task["id"] == task_id:
                task["done"] = not task.get("done", False)
                break
        storage.save_tasks(self.tasks)
        self.window.refresh_tasks()

    def set_active_task(self, task_id):
        self.active_task_id = task_id
        self.window.refresh_tasks()
        self.window.refresh_timer()

    # ---- settings -------------------------------------------------------

    def apply_settings(self, new_settings):
        self.settings = new_settings
        storage.save_settings(self.settings)
        self.timer.update_settings(self.settings)

    # ---- lifecycle ------------------------------------------------------

    def quit(self, *_args):
        storage.save_tasks(self.tasks)
        storage.save_settings(self.settings)
        Gtk.main_quit()

    def run(self):
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        Gtk.main()
