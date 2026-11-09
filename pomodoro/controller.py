"""Controlador do app: reúne dados, timer, rastreamento e ações do usuário. Sem GTK.

A interface chama os métodos daqui e se inscreve (subscribe) para saber quando redesenhar:
  "tick"      passou 1 segundo / o timer mudou de estado
  "phase"     uma fase (foco ou pausa) terminou ou foi trocada
  "data"      tarefas, subtarefas, grupos ou a tarefa em foco mudaram
  "settings"  as configurações mudaram
Notificações e som entram por injeção (notify, play_sound), assim os testes não dependem do sistema.
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db, export, groups as groups_model, settings as settings_store, today as today_model
from .repository import Repository
from .timer import PHASE_LABELS, Phase, PomodoroTimer
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
        # Estimador de tempo (Fase 8). Precisa de suggest_estimate(repo, title, group_id, user_estimate_min)
        # -> {"minutes": int, "note": str} | None e suggest_subtasks(repo, title, group_id) -> [(título, min)].
        self.estimator = None
        self.last_alert = None          # dados do último alerta de hiperfoco (para o modo compacto)
        self.last_pomodoro = None       # dados do último pomodoro concluído (para "como foi?")

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
        if name == "started" and self.timer.phase == Phase.WORK:
            self._emit("started")
        elif name == "phase_ended" and data["phase"] == Phase.WORK and data["completed"] \
                and data["reason"] in ("auto", "skip"):
            task_id = self.tracker.active_task_id
            task = self.repo.get_task(task_id) if task_id else None
            self.last_pomodoro = {
                "task_id": task_id, "subtask_id": self.tracker.active_subtask_id,
                "title": task["title"] if task else None, "seconds": data["seconds"],
                "number": self.pomodoros_today(),
            }
            self._emit("pomodoro-done")
        elif name == "warning":
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
            self.last_alert = {"task_id": data["task_id"], "title": title, "real_seconds": data["real_seconds"],
                               "estimate_seconds": data["estimate_seconds"]}
            self._emit("alert")

    def toggle_timer(self):
        self.timer.toggle()

    def skip_phase(self):
        self.timer.skip()

    def reset_phase(self):
        self.timer.reset_phase()

    def restart_session(self):
        self.timer.restart_all()

    def extend_phase(self, seconds):
        self.timer.extend(seconds)

    def bump_estimate(self, task_id, minutes):
        """Soma minutos ao previsto da tarefa (usa a soma das subtarefas se ela não tem previsão própria)."""
        task = self.repo.get_task(task_id)
        if task is None:
            raise KeyError(f"tarefa {task_id} não existe")
        base = task["estimate_min"] or self.repo.subtasks_estimate_sum(task_id) or 0
        self.update_task(task_id, estimate_min=base + minutes)

    def set_task_difficulty(self, task_id, difficulty):
        """Registra como foi a tarefa: easy, ok ou hard (alimenta a IA)."""
        self.repo.update_task(task_id, difficulty=difficulty)
        self._changed()

    def add_distraction(self, text):
        """Anota um pensamento solto durante o foco, ligado à sessão e à tarefa atuais."""
        did = self.tracker.add_distraction(text)
        self._changed()
        return did

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

    def today_view(self, query="", group_id=None, only_task_id=None):
        return today_model.build_today(self.repo, self.today(), query=query, group_id=group_id,
                                       only_task_id=only_task_id)

    def focus_context(self, view=None):
        """Dados da tarefa/subtarefa em foco para o painel do timer e a barra lateral.

        view: o TodayView completo (sem filtros), usado para saber o que vem depois no foco.
        """
        task_id, subtask_id = self.tracker.active_task_id, self.tracker.active_subtask_id
        context = {"task_id": task_id, "task_title": None, "subtask_title": None,
                   "estimate_min": None, "next_title": None, "next_estimate_min": None}
        task = self.repo.get_task(task_id) if task_id else None
        if task:
            context["task_title"] = task["title"]
            context["estimate_min"] = (task["estimate_min"] if task["estimate_min"] is not None
                                       else self.repo.subtasks_estimate_sum(task_id))
            sub = self.repo.get_subtask(subtask_id) if subtask_id else None
            context["subtask_title"] = sub["title"] if sub else None
        if view is not None:
            context["next_title"], context["next_estimate_min"] = today_model.next_focus_item(
                view, task_id, subtask_id)
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

    # ---- grupos -----------------------------------------------------------

    def group_cards(self, include_archived=False):
        return groups_model.build_group_cards(self.repo, self.today(), include_archived=include_archived)

    def group_task_count(self, group_id):
        return len(self.repo.list_tasks(group_id=group_id))

    def create_group(self, name, color, work_min=None, short_break_min=None, require_estimate=False):
        group = self.repo.create_group(name, color=color, work_min=work_min, short_break_min=short_break_min,
                                       require_estimate=require_estimate)
        self._changed()
        return group

    def update_group(self, group_id, **fields):
        """Edita o grupo. Se ele é o da tarefa em foco, o timer passa a usar o ciclo novo."""
        group = self.repo.update_group(group_id, **fields)
        self.tracker.reapply_overrides()
        self._changed()
        return group

    def archive_group(self, group_id, archived=True):
        self.repo.archive_group(group_id, archived)
        active = self.tracker.active_task_id
        task = self.repo.get_task(active) if active else None
        if archived and task and task["group_id"] == group_id:
            self.tracker.set_active(None)
        self._changed()

    def delete_group(self, group_id):
        """Apaga o grupo e todas as tarefas dele."""
        active = self.tracker.active_task_id
        task = self.repo.get_task(active) if active else None
        if task and task["group_id"] == group_id:
            self.tracker.set_active(None)
        self.repo.delete_group(group_id)
        self._changed()

    # ---- dados e sons -----------------------------------------------------

    def export_data(self, path):
        """Grava todas as tarefas, subtarefas e sessões em JSON. Devolve o nº de registros."""
        return export.write_export(self.conn, path, now=self._now)

    def test_sound(self, sound):
        self._play_sound(sound)

    # ---- edição completa de uma tarefa ------------------------------------

    def task_detail(self, task_id):
        """Tudo da tela Editar tarefa: dados, subtarefas com tempo real, sessões e distrações."""
        repo = self.repo
        task = repo.get_task(task_id)
        if task is None:
            return None
        subs = repo.list_subtasks(task_id)
        titles = {sub["id"]: sub["title"] for sub in subs}
        sessions = repo.list_sessions(task_id=task_id, kinds=("work", "manual"))
        for session in sessions:
            session["subtask_title"] = titles.get(session["subtask_id"])
        return {
            "task": task,
            "group": repo.get_group(task["group_id"]),
            "subtasks": [{"id": s["id"], "title": s["title"], "estimate_min": s["estimate_min"],
                          "done": bool(s["done"]), "real_seconds": repo.real_seconds_subtask(s["id"])}
                         for s in subs],
            "real_seconds": repo.real_seconds(task_id),
            "pomodoros": sum(1 for s in sessions if s["kind"] == "work" and s["completed_phase"]),
            "estimate_sum": repo.subtasks_estimate_sum(task_id),
            "sessions": sessions,
            "distractions": repo.list_distractions(task_id=task_id),
        }

    def update_task(self, task_id, **fields):
        """Edita campos da tarefa. estimate_min 0/None tira a previsão; group_id move de grupo."""
        task = self.repo.get_task(task_id)
        if task is None:
            raise KeyError(f"tarefa {task_id} não existe")
        if "estimate_min" in fields:
            fields["estimate_min"] = fields["estimate_min"] or None
        new_group = fields.pop("group_id", None)
        target = self.repo.get_group(new_group or task["group_id"])
        estimate = fields.get("estimate_min", task["estimate_min"])
        if target["require_estimate"] and estimate is None:
            raise ValueError("este grupo exige a previsão de tempo")
        if fields:
            self.repo.update_task(task_id, **fields)
        if new_group and new_group != task["group_id"]:
            self.repo.move_task(task_id, new_group)
        if "estimate_min" in fields:
            self.tracker.invalidate()
        if new_group:
            self.tracker.reapply_overrides()
        self._changed()

    def update_subtask(self, subtask_id, **fields):
        if "estimate_min" in fields:
            fields["estimate_min"] = fields["estimate_min"] or None
        self.repo.update_subtask(subtask_id, **fields)
        if "estimate_min" in fields:
            self.tracker.invalidate()
        self._changed()

    def reorder_subtasks(self, task_id, ids):
        self.repo.reorder_subtasks(task_id, ids)
        self._changed()

    def adjust_real_time(self, task_id, minutes, subtask_id=None):
        """Corrige o tempo real (+/- minutos), sem inventar uma sessão de foco."""
        if not minutes:
            return
        if self.repo.real_seconds(task_id) + minutes * 60 < 0:
            raise ValueError("o tempo real não pode ficar negativo")
        self.repo.add_manual_adjustment(task_id, int(minutes * 60), subtask_id=subtask_id)
        self.tracker.invalidate()
        self._changed()

    def duplicate_task(self, task_id, day=...):
        """Copia a tarefa com as subtarefas (sem o tempo). Por padrão, para amanhã."""
        if day is ...:
            day = self.today() + timedelta(days=1)
        copy = self.repo.duplicate_task(task_id, scheduled_for=day)
        self._changed()
        return copy

    def create_task_full(self, title, group_id=None, day=..., estimate_min=None, repeat_rule=None,
                         energy=None, notes="", subtasks=(), focus=False):
        """Cria a tarefa com tudo do modal "Nova tarefa". day=... é hoje; day=None é sem data.

        subtasks: [(título, minutos ou None)]. Valida tudo antes de gravar. focus=True já
        coloca a tarefa em foco e inicia o timer.
        """
        subtasks = [(str(t).strip(), m) for t, m in subtasks]
        if any(not t for t, _m in subtasks):
            raise ValueError("toda subtarefa precisa de um título")
        group_id = group_id or self.repo.default_group_id()
        task = self.repo.create_task(
            group_id, title, estimate_min=estimate_min or None,
            scheduled_for=self.today() if day is ... else day,
            notes=notes, repeat_rule=repeat_rule, energy=energy,
        )
        try:
            for sub_title, minutes in subtasks:
                self.repo.add_subtask(task["id"], sub_title, minutes or None)
        except (ValueError, KeyError):
            self.repo.delete_task(task["id"])
            raise
        if focus:
            self.tracker.set_active(task["id"])
            if self.timer.phase == Phase.WORK and not self.timer.running:
                self.timer.start()
        self._changed()
        return task

    def focus_and_start(self, task_id, subtask_id=None):
        """"Focar nesta tarefa": põe em foco e inicia o timer se ele estiver parado no foco."""
        self.tracker.set_active(task_id, subtask_id)
        if self.timer.phase == Phase.WORK and not self.timer.running:
            self.timer.start()
        self._changed()

    # ---- sugestões da IA (Fase 8) -----------------------------------------

    def suggest_estimate(self, title, group_id=None, user_estimate_min=None):
        """{"minutes", "note"} sugerido pela IA para o que está sendo criado, ou None."""
        if self.estimator is None or not (title or "").strip():
            return None
        return self.estimator.suggest_estimate(
            self.repo, title=title, group_id=group_id, user_estimate_min=user_estimate_min)

    def suggest_subtasks(self, title, group_id=None):
        """[(título, minutos)] sugeridos pela IA para quebrar a tarefa; [] sem IA."""
        if self.estimator is None or not (title or "").strip():
            return []
        return list(self.estimator.suggest_subtasks(self.repo, title=title, group_id=group_id))

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
