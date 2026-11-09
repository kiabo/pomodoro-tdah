"""Liga o timer à tarefa/subtarefa em foco e grava o tempo real em sessões.

Regras:
- Uma sessão por fase em andamento: abre quando o timer roda, e fica aberta durante pausas
  (o tempo parado não conta, pois os segundos vêm dos ticks). Fecha quando a fase termina
  ou quando a tarefa/subtarefa ativa muda.
- A sessão que leva a fase até o zero fica com completed_phase=1 (conta como pomodoro).
  Se a fase foi cortada antes (pular, resetar, reiniciar, fechar o app), interrupted=1.
- A cada CHECKPOINT_SECONDS o tempo é salvo, e sessões abertas que sobraram de uma queda
  são recuperadas por recover_orphans().
- Sessões de 0 segundo que não completaram nada são apagadas (ruído).
"""

from datetime import datetime, timedelta

from .settings import DEFAULT_SETTINGS
from .timer import Phase


class Tracker:
    CHECKPOINT_SECONDS = 30

    def __init__(self, repo, timer, get_settings, on_alert=None):
        self.repo = repo
        self.timer = timer
        self._get_settings = get_settings
        self.on_alert = on_alert

        self._task_id = None
        self._subtask_id = None

        self._session_id = None
        self._session_kind = None
        self._seconds = 0
        self._saved = 0

        # Cache da tarefa em foco para não consultar o banco a cada segundo.
        self._base_seconds = 0
        self._sub_base_seconds = 0
        self._estimate_seconds = None
        self._alerted = {}

    # ---- tarefa ativa ---------------------------------------------------

    @property
    def active_task_id(self):
        return self._task_id

    @property
    def active_subtask_id(self):
        return self._subtask_id

    @property
    def session_id(self):
        return self._session_id

    def set_active(self, task_id, subtask_id=None):
        """Define a tarefa (e opcionalmente a subtarefa) em foco; None limpa."""
        if subtask_id is not None:
            sub = self.repo.get_subtask(subtask_id)
            if sub is None:
                raise KeyError(f"subtarefa {subtask_id} não existe")
            if task_id is None:
                task_id = sub["task_id"]
            elif sub["task_id"] != task_id:
                raise ValueError("a subtarefa não pertence a essa tarefa")
        task = None
        if task_id is not None:
            task = self.repo.get_task(task_id)
            if task is None:
                raise KeyError(f"tarefa {task_id} não existe")
        if (task_id, subtask_id) == (self._task_id, self._subtask_id):
            return

        splitting = self._session_kind == "work"
        if splitting:
            self._close_session()
        self._task_id, self._subtask_id = task_id, subtask_id

        self.reapply_overrides()
        if splitting and self.timer.running and self.timer.phase == Phase.WORK:
            self._open_session()
        else:
            self._refresh_cache()

    def reapply_overrides(self):
        """Usa no timer a duração própria do grupo da tarefa em foco (chame se ela mudar de grupo)."""
        task = self.repo.get_task(self._task_id) if self._task_id else None
        group = self.repo.get_group(task["group_id"]) if task else None
        self.timer.set_overrides(
            work_min=group["work_min"] if group else None,
            short_break_min=group["short_break_min"] if group else None,
        )

    # ---- sessões --------------------------------------------------------

    def _open_session(self):
        kind = self.timer.phase.value
        is_work = kind == "work"
        self._session_id = self.repo.start_session(
            kind,
            task_id=self._task_id if is_work else None,
            subtask_id=self._subtask_id if is_work else None,
        )
        self._session_kind = kind
        self._seconds = 0
        self._saved = 0
        self._refresh_cache()

    def _checkpoint(self):
        if self._session_id is not None and self._seconds != self._saved:
            self.repo.update_session_seconds(self._session_id, self._seconds)
            self._saved = self._seconds

    def _close_session(self, interrupted=False, completed_phase=False):
        if self._session_id is None:
            return
        if self._seconds == 0 and not completed_phase:
            self.repo.delete_session(self._session_id)
        else:
            self.repo.end_session(
                self._session_id, self._seconds,
                interrupted=interrupted, completed_phase=completed_phase,
            )
        self._session_id = None
        self._session_kind = None
        self._seconds = 0
        self._saved = 0

    def recover_orphans(self):
        """Fecha sessões que ficaram abertas por uma queda do app. Retorna quantas havia."""
        recovered = 0
        for row in self.repo.open_sessions():
            if row["id"] == self._session_id:
                continue
            if row["seconds"] == 0:
                self.repo.delete_session(row["id"])
            else:
                ended = datetime.fromisoformat(row["started_at"]) + timedelta(seconds=row["seconds"])
                self.repo.end_session(row["id"], row["seconds"], interrupted=True, ended_at=ended)
            recovered += 1
        return recovered

    def shutdown(self):
        """Ao sair do app com um pomodoro em andamento: grava o que foi feito como interrompido."""
        self._close_session(interrupted=True)

    # ---- tempo real e hiperfoco ----------------------------------------

    def _refresh_cache(self):
        """Recalcula a base de tempo e a previsão da tarefa em foco."""
        self._base_seconds = 0
        self._sub_base_seconds = 0
        self._estimate_seconds = None
        if self._task_id is None:
            return
        if self._session_kind == "work":
            self._base_seconds = max(self.repo.real_seconds(self._task_id) - self._saved, 0)
            if self._subtask_id is not None:
                self._sub_base_seconds = max(self.repo.real_seconds_subtask(self._subtask_id) - self._saved, 0)
        task = self.repo.get_task(self._task_id)
        if task is not None:
            minutes = task["estimate_min"] or self.repo.subtasks_estimate_sum(self._task_id)
            self._estimate_seconds = minutes * 60 if minutes else None

    def invalidate(self):
        """Chame depois de editar a previsão ou o tempo (ajuste manual) da tarefa em foco."""
        self._refresh_cache()

    def live_real_seconds(self, task_id):
        """Tempo real da tarefa, incluindo os segundos do pomodoro em andamento."""
        if self._session_kind == "work" and task_id == self._task_id:
            return self._base_seconds + self._seconds
        return self.repo.real_seconds(task_id)

    def live_real_seconds_subtask(self, subtask_id):
        """Tempo real da subtarefa, incluindo os segundos do pomodoro em andamento."""
        if self._session_kind == "work" and subtask_id == self._subtask_id:
            return self._sub_base_seconds + self._seconds
        return self.repo.real_seconds_subtask(subtask_id)

    def _check_hyperfocus(self):
        settings = self._get_settings()
        if not settings.get("hyperfocus_alert", DEFAULT_SETTINGS["hyperfocus_alert"]):
            return
        if self._session_kind != "work" or self._task_id is None or not self._estimate_seconds:
            return
        pct = settings.get("hyperfocus_threshold_pct", DEFAULT_SETTINGS["hyperfocus_threshold_pct"])
        limit = self._estimate_seconds * pct / 100
        live = self._base_seconds + self._seconds
        if live >= limit and self._alerted.get(self._task_id) != limit:
            self._alerted[self._task_id] = limit
            if self.on_alert:
                self.on_alert(
                    "hyperfocus", task_id=self._task_id, real_seconds=live,
                    estimate_seconds=self._estimate_seconds, limit_seconds=limit,
                )

    # ---- distrações -----------------------------------------------------

    def add_distraction(self, text):
        """Anota um pensamento solto, ligado à sessão e à tarefa em foco."""
        return self.repo.add_distraction(
            text, session_id=self._session_id, task_id=self._task_id
        )

    # ---- eventos do timer -----------------------------------------------

    def handle(self, event, **data):
        if event == "started":
            if self._session_id is None:
                self._open_session()
        elif event == "paused":
            self._checkpoint()
        elif event == "second":
            if self._session_id is None:
                self._open_session()
            self._seconds += 1
            if self._seconds - self._saved >= self.CHECKPOINT_SECONDS:
                self._checkpoint()
            self._check_hyperfocus()
        elif event == "phase_ended":
            completed = data["completed"]
            self._close_session(interrupted=not completed, completed_phase=completed)
        elif event == "phase_started":
            if self.timer.running and self._session_id is None:
                self._open_session()
