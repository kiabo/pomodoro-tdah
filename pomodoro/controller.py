"""Controlador do app: reúne dados, timer, rastreamento e ações do usuário. Sem GTK.

A interface chama os métodos daqui e se inscreve (subscribe) para saber quando redesenhar:
  "tick"      passou 1 segundo / o timer mudou de estado
  "phase"     uma fase (foco ou pausa) terminou ou foi trocada
  "data"      tarefas, subtarefas, grupos ou a tarefa em foco mudaram
  "settings"  as configurações mudaram
Notificações e som entram por injeção (notify, play_sound), assim os testes não dependem do sistema.
"""

import logging
from datetime import date, datetime
from pathlib import Path

from . import db, settings as settings_store, today as today_model
from .repository import Repository
from .timer import PHASE_LABELS, PomodoroTimer
from .tracking import Tracker

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, data_dir=None, settings=None, scheduler=None, notify=None, play_sound=None,
                 now=datetime.now, today=date.today):
        self.data_dir = Path(data_dir or settings_store.data_dir())
        self.settings = settings if settings is not None else settings_store.load_settings(self.data_dir)
        self.conn = db.open_database(self.data_dir)
        self._now = now
        self._today = today
        self.repo = Repository(self.conn, now=now)
        self._notify = notify or (lambda message: None)
        self._play_sound = play_sound or (lambda sound: None)
        self._subscribers = []

        self.timer = PomodoroTimer(self.settings, self._on_tick, self._on_phase_change, scheduler=scheduler)
        self.tracker = Tracker(self.repo, self.timer, lambda: self.settings, on_alert=self._on_alert)
        self.tracker.recover_orphans()
        self.timer.add_listener(self.tracker.handle)
        self.timer.add_listener(self._on_timer_event)

    # ---- inscrições -----------------------------------------------------

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def _emit(self, kind):
        for callback in list(self._subscribers):
            try:
                callback(kind)
            except Exception:  # uma tela com defeito não pode derrubar o timer
                log.exception("erro ao tratar o evento %r", kind)

    def _changed(self):
        self._emit("data")

    # ---- timer e rastreamento -------------------------------------------

    def _on_tick(self):
        self._emit("tick")

    def _on_phase_change(self, auto):
        self._notify(f"Hora de: {PHASE_LABELS[self.timer.phase]}")
        self._play_sound(self.settings.get("end_sound", "complete"))
        self._emit("phase")

    def _on_timer_event(self, name, **data):
        if name == "warning":
            minutes = max(data["remaining"] // 60, 1)
            self._notify(f"Faltam {minutes} min para o fim do foco")
        elif name == "overtime":
            self._notify("O tempo do foco acabou. Termine o que está fazendo ou faça uma pausa.")
            self._play_sound(self.settings.get("end_sound", "complete"))

    def _on_alert(self, name, **data):
        if name == "hyperfocus":
            task = self.repo.get_task(data["task_id"])
            title = task["title"] if task else "a tarefa atual"
            real_min = round(data["real_seconds"] / 60)
            est_min = round(data["estimate_seconds"] / 60)
            self._notify(f"Passou do previsto em “{title}”: {real_min} min de {est_min} min. "
                         "Vale conferir se ainda é a prioridade.")
            self._emit("alert")

    def toggle_timer(self):
        self.timer.toggle()

    def skip_phase(self):
        self.timer.skip()

    def reset_phase(self):
        self.timer.reset_phase()

    def restart_session(self):
        self.timer.restart_all()

    def focus(self, task_id, subtask_id=None):
        """Escolhe a tarefa (e subtarefa) em foco. task_id None limpa."""
        self.tracker.set_active(task_id, subtask_id)
        self._changed()

    def complete_current(self):
        """Conclui a subtarefa em foco (passando para a próxima pendente) ou, sem subtarefa, a tarefa."""
        task_id, subtask_id = self.tracker.active_task_id, self.tracker.active_subtask_id
        if subtask_id:
            self.repo.set_subtask_done(subtask_id, True)
            pending = [s for s in self.repo.list_subtasks(task_id) if not s["done"]]
            self.tracker.set_active(task_id, pending[0]["id"] if pending else None)
            result = "subtask"
        elif task_id:
            self.repo.set_task_status(task_id, "done")
            self.tracker.set_active(None)
            result = "task"
        else:
            return None
        self._changed()
        return result

    # ---- tarefas --------------------------------------------------------

    def today(self):
        return self._today()

    def today_view(self, query="", group_id=None):
        return today_model.build_today(self.repo, self.today(), query=query, group_id=group_id)

    def focus_context(self, view=None):
        """Dados da tarefa/subtarefa em foco para o painel do timer e a barra lateral.

        view: o TodayView completo (sem filtros), usado para saber o que vem depois no foco.
        """
        task_id, subtask_id = self.tracker.active_task_id, self.tracker.active_subtask_id
        context = {"task_id": task_id, "task_title": None, "subtask_title": None,
                   "estimate_min": None, "next_title": None}
        task = self.repo.get_task(task_id) if task_id else None
        if task:
            context["task_title"] = task["title"]
            context["estimate_min"] = (task["estimate_min"] if task["estimate_min"] is not None
                                       else self.repo.subtasks_estimate_sum(task_id))
            sub = self.repo.get_subtask(subtask_id) if subtask_id else None
            context["subtask_title"] = sub["title"] if sub else None
        if view is not None:
            context["next_title"] = today_model.next_focus(view, task_id, subtask_id)
        return context

    def pomodoros_today(self):
        day = self.today().isoformat()
        return self.repo.count_work_sessions(since=day, until=today_model.next_day(day))

    def add_task(self, title, estimate_min=None, group_id=None, day=None):
        """Cria a tarefa (por padrão para hoje, no grupo padrão). Levanta ValueError se inválida."""
        task = self.repo.create_task(
            group_id or self.repo.default_group_id(), title, estimate_min=estimate_min,
            scheduled_for=day or self.today(),
        )
        self._changed()
        return task

    def rename_task(self, task_id, title):
        self.repo.update_task(task_id, title=title)
        self._changed()

    def delete_task(self, task_id):
        if self.tracker.active_task_id == task_id:
            self.tracker.set_active(None)
        self.repo.delete_task(task_id)
        self._changed()

    def set_task_done(self, task_id, done):
        self.repo.set_task_status(task_id, "done" if done else "todo")
        self._changed()

    def add_subtask(self, task_id, title, estimate_min=None):
        sub = self.repo.add_subtask(task_id, title, estimate_min)
        self.tracker.invalidate()
        self._changed()
        return sub

    def rename_subtask(self, subtask_id, title):
        self.repo.update_subtask(subtask_id, title=title)
        self._changed()

    def delete_subtask(self, subtask_id):
        sub = self.repo.get_subtask(subtask_id)
        if sub and self.tracker.active_subtask_id == subtask_id:
            self.tracker.set_active(sub["task_id"])
        self.repo.delete_subtask(subtask_id)
        self.tracker.invalidate()
        self._changed()

    def set_subtask_done(self, subtask_id, done):
        self.repo.set_subtask_done(subtask_id, done)
        self._changed()

    # ---- configurações --------------------------------------------------

    def apply_settings(self, changes):
        """Mescla `changes` nas configurações (valores inválidos são descartados) e salva."""
        self.settings = settings_store.sanitize({**self.settings, **changes})
        settings_store.save_settings(self.settings, self.data_dir)
        self.timer.update_settings(self.settings)
        self._emit("settings")

    # ---- ciclo de vida --------------------------------------------------

    def shutdown(self):
        self.tracker.shutdown()
        settings_store.save_settings(self.settings, self.data_dir)
        self.conn.close()
