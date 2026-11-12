"""Controlador do app: reúne dados, timer, rastreamento e ações do usuário. Sem GTK.

A interface chama os métodos daqui e se inscreve (subscribe) para saber quando redesenhar:
  "tick"      passou 1 segundo / o timer mudou de estado
  "phase"     uma fase (foco ou pausa) terminou ou foi trocada
  "data"      tarefas, subtarefas, grupos ou a tarefa em foco mudaram
  "settings"  as configurações mudaram
  "day"       virou o dia (pendências levadas, recorrentes criadas)
  "reminder"  chegou a hora de revisar o dia e planejar amanhã
Notificações e som entram por injeção (notify, play_sound), assim os testes não dependem do sistema.
"""

import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .ai import analysis as ai_analysis, summary as ai_summary
from .ai.claude_client import AIUnavailable, ClaudeClient
from .ai.estimator import Estimator
from .jira import importer as jira_importer, push as jira_push
from .jira.client import JiraClient, JiraError, jql_for
from . import db, export, groups as groups_model, planning, settings as settings_store, today as today_model
from .repository import Repository
from .timer import PHASE_LABELS, Phase, PomodoroTimer
from .tracking import Tracker

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, data_dir=None, settings=None, scheduler=None, notify=None, play_sound=None,
                 now=datetime.now, today=date.today, run_async=None, claude_factory=None, jira_factory=None):
        self.data_dir = Path(data_dir or settings_store.data_dir())
        self.settings = settings if settings is not None else settings_store.load_settings(self.data_dir)
        self.conn = db.open_database(self.data_dir)
        self._now = now
        self._today = today
        self.repo = Repository(self.conn, now=now)
        self._notify = notify or (lambda message: None)
        self._play_sound = play_sound or (lambda sound: None)
        self._subscribers = []
        # Estimador de tempo: suggest_estimate(repo, title, group_id, user_estimate_min)
        # -> {"minutes": int, "note": str} | None e suggest_subtasks(repo, title, group_id) -> [(título, min)].
        self.estimator = Estimator()
        self._run_async = run_async or _run_in_thread
        self._claude_factory = claude_factory or ClaudeClient
        self._jira_factory = jira_factory or JiraClient
        self.last_alert = None          # dados do último alerta de hiperfoco (para o modo compacto)
        self.last_pomodoro = None       # dados do último pomodoro concluído (para "como foi?")
        self.jira_sync_status = None    # resultado da última atualização automática do Jira (para a tela)
        self._jira_syncing = False
        self._jira_last_attempt = None
        self._jira_notified_new = set()

        self.timer = PomodoroTimer(self.settings, self._on_tick, self._on_phase_change, scheduler=scheduler)
        self.tracker = Tracker(self.repo, self.timer, lambda: self.settings, on_alert=self._on_alert)
        self.tracker.recover_orphans()
        self.timer.add_listener(self.tracker.handle)
        self.timer.add_listener(self._on_timer_event)

        # Virada do dia: ao abrir o app já aplica o que ficou pendente e as recorrentes que venceram.
        self._current_day = self._today()
        planning.start_of_day(self.repo, self._current_day, carry=self.settings["carry_over_unfinished"])
        self._reminded_day = self._current_day if self._reminder_due() else None   # não avisa logo ao abrir

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

    # ---- relógio do dia ---------------------------------------------------

    def _reminder_due(self):
        """Já passou do horário do lembrete de fim do dia (e ele está ligado)?"""
        at = self.settings.get("end_of_day_reminder") or ""
        return bool(at) and self._now().strftime("%H:%M") >= at

    def poll_clock(self):
        """Chamado de tempos em tempos pelo app: vira o dia e dispara o lembrete de fim do dia."""
        today = self._today()
        if today != self._current_day:
            self._current_day = today
            planning.start_of_day(self.repo, today, carry=self.settings["carry_over_unfinished"])
            self.tracker.invalidate()
            self._emit("day")
            self._changed()
        self._maybe_auto_sync_jira()
        if self._reminded_day != today and self._reminder_due():
            self._reminded_day = today
            review = self.repo.get_day_review(today.isoformat()) or {}
            if not review.get("confirmed_at"):
                self._notify("Fim do dia: que tal revisar o que ficou e planejar amanhã?")
                self._emit("reminder")

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
            planning.spawn_recurring(self.repo, self.today())
            self.tracker.set_active(None)
            result = "task"
        else:
            return None
        self._changed()
        if result == "task":
            self._offer_jira_status(task_id)
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
            link = self.repo.jira_link(task_id)
            context["jira_key"] = link["issue_key"] if link else None
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
        if done:
            planning.spawn_recurring(self.repo, self.today())      # a próxima ocorrência já fica agendada
        self._changed()
        if done:
            self._offer_jira_status(task_id)

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

    # ---- revisar o dia e planejar amanhã ------------------------------------

    def plan_day(self):
        """O dia que está sendo revisado (hoje) e o seguinte, como datas."""
        today = self.today()
        return today, planning.tomorrow(today)

    def day_review(self):
        """Resumo de hoje e as pendências que esperam um destino."""
        return planning.review_day(self.repo, self.today())

    def default_destinations(self, leftovers):
        return planning.default_destinations(leftovers, self.today(), carry=self.settings["carry_over_unfinished"])

    def break_suggestion(self, leftovers):
        """(task_id, texto) quando uma tarefa adiada merece ser quebrada em passos; senão None."""
        return planning.break_suggestion(leftovers) if self.ai_enabled else None

    def set_day_mood(self, mood):
        self.repo.save_day_review(self.today().isoformat(), mood=mood)

    def tomorrow_plan(self):
        """Lista de amanhã com a previsão da IA e a capacidade do dia: {"day", "items", "capacity", "free_min"}."""
        _, day = self.plan_day()
        estimator = self.estimator if self.ai_enabled else None
        items = planning.plan_items(self.repo, day, estimator=estimator)
        free = planning.free_minutes_for(self.repo, day, self.settings["free_minutes_per_day"])
        return {"day": day, "items": items, "free_min": free, "capacity": planning.capacity(items, free)}

    def set_tomorrow_free_minutes(self, minutes):
        _, day = self.plan_day()
        self.repo.save_day_review(day.isoformat(), free_minutes=minutes)

    def add_to_tomorrow(self, title, estimate_min=None, group_id=None):
        _, day = self.plan_day()
        return self.add_task(title, estimate_min, group_id, day=day)

    def reorder_plan(self, ordered_ids):
        planning.reorder_within_groups(self.repo, ordered_ids)
        self._changed()

    def confirm_plan(self, destinations):
        """Aplica o destino de cada pendência e confirma o plano de amanhã.

        destinations: {task_id: "AAAA-MM-DD" | planning.DISCARD | None}. Devolve o resumo
        {"moved", "discarded", "skipped"}. Nada é gravado se algum destino for inválido.
        """
        today, day = self.plan_day()
        result = planning.apply_destinations(self.repo, today, destinations)
        planning.spawn_recurring(self.repo, today)
        planning.confirm_plan(self.repo, today)                      # fecha a revisão de hoje
        planning.confirm_plan(self.repo, day)                         # e marca o plano de amanhã
        self.tracker.invalidate()
        self._changed()
        return result

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
                          "jira_key": s["jira_key"], "done": bool(s["done"]), "real_seconds": repo.real_seconds_subtask(s["id"])}
                         for s in subs],
            "real_seconds": repo.real_seconds(task_id),
            "pomodoros": sum(1 for s in sessions if s["kind"] == "work" and s["completed_phase"]),
            "estimate_sum": repo.subtasks_estimate_sum(task_id),
            "sessions": sessions,
            "distractions": repo.list_distractions(task_id=task_id),
            "jira": repo.jira_link(task_id),
            "jira_logged_seconds": repo.jira_logged_seconds(task_id),
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

    # ---- IA ---------------------------------------------------------------

    @property
    def ai_enabled(self):
        return bool(self.settings.get("ai_enabled", True)) and self.estimator is not None

    def cloud_ready(self):
        """A IA na nuvem está ligada e há uma chave configurada."""
        return self.ai_enabled and bool(self.settings.get("ai_cloud_enabled")) \
            and bool(settings_store.api_key(self.settings))

    def _claude(self):
        return self._claude_factory(settings_store.api_key(self.settings), self.settings.get("ai_model"))

    def suggest_estimate(self, title, group_id=None, user_estimate_min=None, task_id=None):
        """{"minutes", "note", ...} sugerido pela IA local para o que está sendo criado, ou None."""
        if not self.ai_enabled or not (title or "").strip():
            return None
        return self.estimator.suggest_estimate(
            self.repo, title=title, group_id=group_id, user_estimate_min=user_estimate_min, task_id=task_id)

    def suggest_subtasks(self, title, group_id=None):
        """[(título, minutos)] reaproveitados de tarefas parecidas já concluídas; [] sem base."""
        if not self.ai_enabled or not (title or "").strip():
            return []
        return list(self.estimator.suggest_subtasks(self.repo, title=title, group_id=group_id))

    def suggest_subtasks_async(self, title, group_id, done):
        """done(lista, erro): usa tarefas parecidas do histórico; sem elas, o Claude (se estiver ligado)."""
        local = self.suggest_subtasks(title, group_id)
        if local or not self.cloud_ready() or not (title or "").strip():
            done(local, None)
            return
        self.cloud_subtasks(title, lambda result, error: done(result or [], error))

    def analysis(self, period="week"):
        return ai_analysis.build_analysis(self.repo, self._today(), period, self.estimator)

    def apply_ai_predictions(self, predictions):
        """Grava a estimativa da IA como a previsão das tarefas. Retorna quantas mudaram."""
        changed = 0
        for item in predictions:
            task = self.repo.get_task(item.task_id)
            if task and task["status"] in ("todo", "doing") and item.ai_min and task["estimate_min"] != item.ai_min:
                self.repo.update_task(task["id"], estimate_min=item.ai_min, ai_estimate_min=item.ai_min)
                changed += 1
        if changed:
            self.tracker.invalidate()
            self._changed()
        return changed

    def _cloud_call(self, work, done):
        """Roda `work(client)` fora da tela. done(resultado, erro) volta no laço principal; nunca usa o SQLite."""
        if not self.cloud_ready():
            done(None, "Ligue a IA na nuvem e informe a chave em Configurações → IA e dados.")
            return
        client = self._claude()

        def job():
            try:
                return work(client), None
            except AIUnavailable as error:
                return None, str(error)
            except Exception:
                log.exception("erro inesperado na IA em nuvem")
                return None, "Não foi possível falar com o Claude agora."
        self._run_async(job, lambda outcome: done(*outcome))

    def cloud_subtasks(self, title, done):
        context = ai_summary.build_summary(self.repo, limit=20)
        self._cloud_call(lambda client: client.subtasks(title, context), done)

    def cloud_insights(self, done):
        context = ai_summary.build_summary(self.repo)
        self._cloud_call(lambda client: client.insights(context), done)

    def cloud_answer(self, question, done):
        context = ai_summary.build_summary(self.repo)
        self._cloud_call(lambda client: client.answer(question, context), done)

    def test_ai_connection(self, done):
        self._cloud_call(lambda client: client.test_connection(), done)

    # ---- Jira (somente leitura) ---------------------------------------------

    def jira_configured(self):
        s = self.settings
        return bool(s["jira_url"].strip() and s["jira_email"].strip() and settings_store.jira_token(s))

    def _jira(self):
        s = self.settings
        return self._jira_factory(s["jira_url"], s["jira_email"], settings_store.jira_token(s))

    def _jira_call(self, work, done):
        """Roda `work(client)` fora da tela. done(resultado, erro) volta no laço principal; nunca usa o SQLite."""
        if not self.jira_configured():
            done(None, "Informe o endereço, o e-mail e o token do Jira em Configurações → Jira.")
            return
        client = self._jira()

        def job():
            try:
                return work(client), None
            except JiraError as error:
                return None, str(error)
            except Exception:
                log.exception("erro inesperado no Jira")
                return None, "Não foi possível falar com o Jira agora."
        self._run_async(job, lambda outcome: done(*outcome))

    def test_jira_connection(self, done):
        self._jira_call(lambda client: client.test_connection(), done)

    def jira_preview(self, done):
        """Busca as minhas issues e compara com o que já existe. done(itens, erro). Não grava nada."""
        jql = jql_for(self.settings["jira_scope"], self.settings["jira_jql"])

        def search(client):
            issues = client.search(jql)
            return issues, client.truncated

        def fetched(outcome, error):
            if error:
                done(None, error)
                return
            issues, truncated = outcome
            items = jira_importer.Plan(jira_importer.plan_import(
                self.repo, issues, self.settings["jira_project_groups"], self.settings["jira_epic_groups"]))
            items.complete = not truncated
            done(items, None)
        self._jira_call(search, fetched)

    def jira_import(self, items, group_choices=None):
        """Grava os itens marcados da pré-visualização. group_choices: {chave do projeto: id do grupo}
        (vale só para tarefas sem épico: as de épico vão para o grupo dele)."""
        choices = {k: v for k, v in (group_choices or {}).items() if v}
        for item in items:
            if (item.action == jira_importer.NEW and item.kind == jira_importer.TASK and not item.epic
                    and choices.get(item.issue["project_key"])):
                item.group_id = choices[item.issue["project_key"]]
        # Só marca "fora do resultado" se a busca leu tudo; numa leitura cortada, faltar não quer dizer sumir.
        keys = [i.issue["key"] for i in items] if getattr(items, "complete", True) else None
        result = jira_importer.apply_import(self.repo, items, all_keys=keys,
                                            epic_groups=self.settings["jira_epic_groups"])
        changes = {"jira_epic_groups": result["epic_groups"]}
        if choices:
            changes["jira_project_groups"] = {**self.settings["jira_project_groups"], **choices}
        self.apply_settings(changes)
        self.tracker.invalidate()
        self._changed()
        return result

    def _maybe_auto_sync_jira(self):
        minutes = self.settings["jira_auto_sync_min"]
        if not minutes or self._jira_syncing or not self.jira_configured():
            return
        last = self._jira_last_attempt
        if last is None or self._now() - last >= timedelta(minutes=minutes):
            self.jira_auto_sync()

    def jira_auto_sync(self):
        """Atualiza o espelho do Jira (só leitura): refaz o que já foi importado e avisa de issues novas.

        Não cria tarefas nem escreve no Jira. Issues novas só entram quando o usuário importa na tela.
        """
        if self._jira_syncing:
            return
        self._jira_syncing = True
        self._jira_last_attempt = self._now()

        def finished(items, error):
            self._jira_syncing = False
            if error:
                self.jira_sync_status = {"at": self._now(), "ok": False, "message": error}
                self._emit("jira-sync")
                return
            new = [i for i in items if i.action == jira_importer.NEW]
            for item in items:
                if item.action in (jira_importer.NEW, jira_importer.GROUP):
                    item.selected = False                  # criar tarefa, subtarefa ou grupo é decisão do usuário
            keys = [i.issue["key"] for i in items] if items.complete else None
            result = jira_importer.apply_import(self.repo, items, all_keys=keys,
                                                epic_groups=self.settings["jira_epic_groups"])
            self.jira_sync_status = {"at": self._now(), "ok": True, "updated": result["updated"], "new": len(new),
                                     "message": ""}
            fresh = {i.issue["key"] for i in new} - self._jira_notified_new
            if fresh:
                self._jira_notified_new |= fresh
                self._notify(f"{len(fresh)} issue(s) nova(s) no Jira. Importe em Configurações → Jira.")
            if result["updated"]:
                self.tracker.invalidate()
                self._changed()
            self._emit("jira-sync")
        self.jira_preview(finished)

    def jira_resolve_conflict(self, task_id, field, use_jira):
        """Resolve uma divergência de título ou previsão: usar o valor do Jira ou manter o do usuário."""
        link = self.repo.jira_link(task_id)
        if link is None or field not in ("title", "estimate"):
            raise ValueError("Nada para resolver.")
        if use_jira:
            if field == "title" and link["remote_title"]:
                self.repo.update_task(task_id, title=link["remote_title"])
            elif field == "estimate":
                self.repo.update_task(task_id, estimate_min=link["remote_estimate_min"])
        remaining = [f for f in (link["conflicts"] or "").split(",") if f and f != field]
        self.repo.save_jira_link(task_id, link["issue_key"], conflicts=",".join(remaining))
        self.tracker.invalidate()
        self._changed()

    def jira_link(self, task_id):
        return self.repo.jira_link(task_id)

    # ---- Jira: enviar o que o usuário confirmar ------------------------------
    # Fluxo: jira_prepare_* monta a pré-visualização -> a janela mostra -> o usuário confirma
    # (preview["confirmed"] = True) -> jira_push envia exatamente aquilo. Nada vai ao Jira sem isso.

    def _linked(self, task_id):
        task, link = self.repo.get_task(task_id), self.repo.jira_link(task_id)
        if task is None or link is None:
            raise ValueError("Esta tarefa não está ligada a uma issue do Jira.")
        return task, link

    def jira_prepare_comment(self, task_id):
        task, link = self._linked(task_id)
        return jira_push.comment_preview(task, link)

    def jira_prepare_fields(self, task_id):
        task, link = self._linked(task_id)
        return jira_push.fields_preview(task, link)

    def jira_prepare_status(self, task_id, done):
        """Busca no Jira as mudanças de status possíveis. done(pré-visualização, erro)."""
        try:
            task, link = self._linked(task_id)
        except ValueError as error:
            done(None, str(error))
            return

        def fetched(transitions, error):
            if error:
                done(None, error)
                return
            try:
                done(jira_push.status_preview(task, link, transitions), None)
            except ValueError as problem:
                done(None, str(problem))
        self._jira_call(lambda client: client.transitions(link["issue_key"]), fetched)

    def jira_menu_info(self, task_id):
        """O que o menu "Enviar ao Jira" mostra de cada ação (selos e o que está disponível). Só lê o banco."""
        task, link = self._linked(task_id)
        try:
            unlogged = sum(d["seconds"] for d in self.jira_prepare_worklog(task_id)["days"])
        except ValueError:
            unlogged = 0
        try:
            differences = len(jira_push.fields_preview(task, link)["changes"])
        except ValueError:
            differences = 0
        return {"has_notes": bool((task["notes"] or "").strip()), "unlogged_seconds": unlogged,
                "field_differences": differences,
                "local_subtasks": len([s for s in self.repo.list_subtasks(task_id) if not s["jira_key"]])}

    def jira_prepare_worklog(self, task_id):
        task, link = self._linked(task_id)
        return jira_push.worklog_preview(task, link, self.repo.unlogged_sessions(task_id))

    def jira_prepare_subtasks(self, task_id, done):
        """Busca os tipos de sub-tarefa do projeto. done(pré-visualização, erro)."""
        try:
            task, link = self._linked(task_id)
            if not link["project_key"]:
                raise ValueError("Importe de novo a issue para o app saber o projeto dela.")
            if not [s for s in self.repo.list_subtasks(task_id) if not s["jira_key"]]:
                raise ValueError("Todas as subtarefas já estão no Jira, ou não há subtarefas.")
        except ValueError as error:
            done(None, str(error))
            return

        def fetched(types, error):
            if error:
                done(None, error)
                return
            done(jira_push.subtasks_preview(task, link, self.repo.list_subtasks(task_id), types), None)
        self._jira_call(lambda client: client.subtask_types(link["project_key"]), fetched)

    def jira_prepare_pull_subtasks(self, task_id, done):
        """Lê as sub-tarefas que já existem na issue e separa as que ainda não estão aqui. done(lista, erro)."""
        try:
            _task, link = self._linked(task_id)
        except ValueError as error:
            done(None, str(error))
            return
        known = {s["jira_key"] for s in self.repo.list_subtasks(task_id) if s["jira_key"]}

        def fetched(found, error):
            if error:
                done(None, error)
                return
            new = [f for f in found if f["key"] not in known]
            done(new, None if new else "Não há sub-tarefas novas no Jira para trazer.")
        self._jira_call(lambda client: client.subtasks_of(link["issue_key"]), fetched)

    def jira_pull_subtasks(self, task_id, found):
        """Cria subtarefas locais (já ligadas à sub-tarefa do Jira) para as escolhidas. Só lê do Jira."""
        for item in found:
            sub = self.repo.add_subtask(task_id, item["title"])
            self.repo.set_subtask_jira_key(sub["id"], item["key"])
            if item["done"]:
                self.repo.set_subtask_done(sub["id"], True)
        self.tracker.invalidate()
        self._changed()
        return len(found)

    def jira_push(self, preview, done):
        """Envia a pré-visualização confirmada. done(mensagem, erro). Registra o envio só se der certo."""
        try:
            jira_push.validate(preview)
        except ValueError as error:
            done(None, str(error))
            return

        def finished(result, error):
            if error:
                done(None, error)
                return
            self._after_push(preview, result)
            if result.get("error"):
                sent = len(result.get("worklogs") or result.get("created") or [])
                done(None, f"Enviei {sent} de {result['planned']} para {preview['issue_key']}; "
                           f"o resto não foi. {result['error']}")
                return
            done(f"Enviado para {preview['issue_key']}.", None)
        self._jira_call(lambda client: jira_push.execute(client, preview), finished)

    def _after_push(self, preview, result):
        task_id, key = preview["task_id"], preview["issue_key"]
        link = self.repo.jira_link(task_id)
        if link:
            if preview["kind"] == jira_push.STATUS:
                option = result["option"]
                self.repo.save_jira_link(task_id, key, remote_status=option["to_status"],
                                         remote_status_category=option["to_category"])
            elif preview["kind"] == jira_push.FIELDS:
                updates = {}
                if "title" in result["fields"]:
                    updates["remote_title"] = result["fields"]["title"]
                if "estimate" in result["fields"]:
                    updates["remote_estimate_min"] = result["fields"]["estimate"]
                left = [f for f in (link["conflicts"] or "").split(",") if f and f not in result["fields"]]
                updates["conflicts"] = ",".join(left)
                self.repo.save_jira_link(task_id, key, **updates)
            elif preview["kind"] == jira_push.WORKLOG:
                for entry in result["worklogs"]:
                    self.repo.record_worklog(entry["session_ids"], task_id, key, entry["worklog_id"])
            elif preview["kind"] == jira_push.SUBTASKS:
                for entry in result["created"]:
                    self.repo.set_subtask_jira_key(entry["subtask_id"], entry["key"])
        self.repo.log_jira_push(task_id, key, preview["kind"], result["detail"])
        self._changed()

    def jira_pushes(self, task_id):
        return self.repo.list_jira_pushes(task_id)

    def _offer_jira_status(self, task_id):
        """Avisa a tela que uma tarefa ligada ao Jira foi concluída (ela só pergunta; não envia nada)."""
        link = self.repo.jira_link(task_id) if task_id else None
        if link and link["remote_status_category"] != "done":
            self._emit(f"jira-offer:{task_id}")

    def jira_unlink(self, task_id):
        """Solta a tarefa da issue. Não mexe no Jira."""
        self.repo.remove_jira_link(task_id)
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


def _run_in_thread(job, deliver):
    """Executa `job` numa thread e entrega o resultado no laço principal do GTK."""
    def target():
        outcome = job()
        from gi.repository import GLib
        GLib.idle_add(lambda: deliver(outcome) and False)
    threading.Thread(target=target, daemon=True).start()
