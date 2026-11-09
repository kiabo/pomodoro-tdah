import signal
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, AyatanaAppIndicator3 as AppIndicator3, Notify

from . import db, settings as settings_store
from .repository import Repository
from .timer import PomodoroTimer, Phase, PHASE_LABELS
from .tracking import Tracker
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

        self.data_dir = settings_store.data_dir()
        self.settings = settings_store.load_settings(self.data_dir)
        self.db = db.open_database(self.data_dir)
        self.repo = Repository(self.db)

        self.timer = PomodoroTimer(self.settings, self.on_tick, self.on_phase_change)
        self.tracker = Tracker(self.repo, self.timer, lambda: self.settings, on_alert=self.on_alert)
        self.tracker.recover_orphans()
        self.timer.add_listener(self.tracker.handle)
        self.timer.add_listener(self.on_timer_event)

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
        self._notify(f"Hora de: {label}")
        self._play_beep()
        self.window.refresh_timer()

    def on_timer_event(self, name, **data):
        if name == "warning":
            minutes = max(data["remaining"] // 60, 1)
            self._notify(f"Faltam {minutes} min para o fim do foco")
        elif name == "overtime":
            self._notify("O tempo do foco acabou. Termine o que está fazendo ou faça uma pausa.")
            self._play_beep()

    def on_alert(self, name, **data):
        if name == "hyperfocus":
            task = self.repo.get_task(data["task_id"])
            title = task["title"] if task else "a tarefa atual"
            real_min = round(data["real_seconds"] / 60)
            est_min = round(data["estimate_seconds"] / 60)
            self._notify(f"Passou do previsto em \u201c{title}\u201d: {real_min} min de {est_min} min. "
                         "Vale conferir se ainda é a prioridade.")

    def _notify(self, message):
        if not self.settings.get("system_notifications", True):
            return
        try:
            Notify.Notification.new("Pomodoro", message, None).show()
        except Exception:
            pass

    @property
    def active_task_id(self):
        return self.tracker.active_task_id

    def _play_beep(self):
        sound = self.settings.get("end_sound", "complete")
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

    # ---- task CRUD ----------------------------------------------------
    # Ponte para a janela antiga (lista plana). Será substituída pela UI nova (Fase 4+).

    @property
    def tasks(self):
        return [
            {"id": t["id"], "title": t["title"], "done": t["status"] == "done"}
            for group in self.repo.list_groups()
            for t in self.repo.list_tasks(group_id=group["id"], statuses=("todo", "doing", "done"))
        ]

    def add_task(self, title):
        self.repo.create_task(self.repo.default_group_id(), title)
        self.window.refresh_tasks()

    def edit_task(self, task_id, new_title):
        self.repo.update_task(task_id, title=new_title)
        self.window.refresh_tasks()

    def delete_task(self, task_id):
        if self.active_task_id == task_id:
            self.tracker.set_active(None)
        self.repo.delete_task(task_id)
        self.window.refresh_tasks()

    def toggle_task_done(self, task_id):
        task = self.repo.get_task(task_id)
        if task is not None:
            self.repo.set_task_status(task_id, "todo" if task["status"] == "done" else "done")
        self.window.refresh_tasks()

    def set_active_task(self, task_id):
        self.tracker.set_active(task_id)
        self.window.refresh_tasks()
        self.window.refresh_timer()

    # ---- settings -------------------------------------------------------

    def apply_settings(self, new_settings):
        # Mescla: a janela antiga só envia as 4 chaves do ciclo.
        self.settings = settings_store.sanitize({**self.settings, **new_settings})
        settings_store.save_settings(self.settings, self.data_dir)
        self.timer.update_settings(self.settings)

    # ---- lifecycle ------------------------------------------------------

    def quit(self, *_args):
        self.tracker.shutdown()
        settings_store.save_settings(self.settings, self.data_dir)
        self.db.close()
        Gtk.main_quit()

    def run(self):
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        Gtk.main()
