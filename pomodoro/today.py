"""Modelo da tela "Hoje": grupos → tarefas → subtarefas com previsto e tempo real.

Monta, a partir do repositório, tudo o que a interface precisa já calculado, para a tela
não fazer contas nem consultas. Funções puras sobre o Repository (sem GTK).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import stats


@dataclass
class SubtaskView:
    id: str
    title: str
    estimate_min: int | None
    done: bool
    real_seconds: int


@dataclass
class TaskView:
    id: str
    group_id: str
    title: str
    status: str
    estimate_min: int | None        # previsão efetiva: a da tarefa ou, sem ela, a soma das subtarefas
    own_estimate_min: int | None
    real_seconds: int
    postponed_count: int = 0
    subtasks: list = field(default_factory=list)
    jira_key: str | None = None     # chave da issue do Jira ligada à tarefa, se houver

    @property
    def done(self):
        return self.status == "done"

    @property
    def subtasks_done(self):
        return sum(1 for s in self.subtasks if s.done)


@dataclass
class GroupView:
    id: str
    name: str
    color: str
    tasks: list = field(default_factory=list)

    @property
    def planned_min(self):
        return sum(t.estimate_min or 0 for t in self.tasks)

    @property
    def real_seconds(self):
        return sum(t.real_seconds for t in self.tasks)


@dataclass
class TodayView:
    day: str
    groups: list                    # só grupos com tarefas após os filtros
    planned_min: int                # totais do dia inteiro, sem filtros
    real_seconds: int
    task_count: int
    done_count: int
    accuracy: float | None
    group_counts: dict              # {group_id: nº de tarefas do dia} (todos os grupos)
    all_groups: list                # [{id, name, color}] na ordem do usuário
    real_by_task: dict = field(default_factory=dict)   # {task_id: segundos} de todas as tarefas do dia

    @property
    def visible_tasks(self):
        return [t for g in self.groups for t in g.tasks]


def _day_str(day):
    return day.isoformat() if isinstance(day, (date, datetime)) else day


def next_day(day):
    return (date.fromisoformat(_day_str(day)) + timedelta(days=1)).isoformat()


def build_today(repo, day, query="", group_id=None, only_task_id=None):
    """only_task_id: mostra só essa tarefa na lista ("uma coisa por vez"); os totais seguem do dia todo."""
    day = _day_str(day)
    tasks = repo.list_for_day(day)
    groups = repo.list_groups()
    subtasks = repo.subtasks_by_task(t["id"] for t in tasks)
    real_by_task, real_by_subtask = repo.real_seconds_map()
    jira_keys = repo.jira_keys()

    views = []
    for row in tasks:
        subs = [
            SubtaskView(s["id"], s["title"], s["estimate_min"], bool(s["done"]),
                        real_by_subtask.get(s["id"], 0))
            for s in subtasks[row["id"]]
        ]
        sub_sum = sum(s.estimate_min or 0 for s in subs) or None
        estimate = row["estimate_min"] if row["estimate_min"] is not None else sub_sum
        views.append(TaskView(
            row["id"], row["group_id"], row["title"], row["status"], estimate,
            row["estimate_min"], real_by_task.get(row["id"], 0), row["postponed_count"], subs,
            jira_keys.get(row["id"]),
        ))

    needle = (query or "").strip().casefold()

    def visible(task):
        if only_task_id is not None and task.id != only_task_id:
            return False
        if group_id is not None and task.group_id != group_id:
            return False
        if not needle:
            return True
        return (needle in task.title.casefold() or any(needle in s.title.casefold() for s in task.subtasks)
                or needle in (task.jira_key or "").casefold())

    group_views = []
    for group in groups:
        mine = [t for t in views if t.group_id == group["id"] and visible(t)]
        if mine:
            group_views.append(GroupView(group["id"], group["name"], group["color"], mine))

    counts = {g["id"]: 0 for g in groups}
    for task in views:
        counts[task.group_id] = counts.get(task.group_id, 0) + 1

    done = [t for t in views if t.done]
    return TodayView(
        day=day,
        groups=group_views,
        planned_min=sum(t.estimate_min or 0 for t in views),
        real_seconds=sum(t.real_seconds for t in views),
        task_count=len(views),
        done_count=len(done),
        accuracy=stats.mean_accuracy((t.real_seconds, t.estimate_min) for t in done),
        group_counts=counts,
        all_groups=[{"id": g["id"], "name": g["name"], "color": g["color"]} for g in groups],
        real_by_task={t.id: t.real_seconds for t in views},
    )


def next_focus_item(view, active_task_id, active_subtask_id):
    """O que vem depois no foco: (título, previsão em min ou None). Primeiro a próxima subtarefa pendente
    da tarefa em foco, depois a próxima tarefa pendente; (None, None) se não há mais nada."""
    tasks = view.visible_tasks
    active = next((t for t in tasks if t.id == active_task_id), None)
    if active:
        pending = [s for s in active.subtasks if not s.done and s.id != active_subtask_id]
        if active_subtask_id:
            ids = [s.id for s in active.subtasks]
            if active_subtask_id in ids:
                after = active.subtasks[ids.index(active_subtask_id) + 1:]
                pending = [s for s in after if not s.done] or pending
        if pending:
            return pending[0].title, pending[0].estimate_min
    candidates = [t for t in tasks if not t.done and t.id != active_task_id]
    if active:
        later = tasks[tasks.index(active) + 1:]
        candidates = [t for t in later if not t.done] or candidates
    return (candidates[0].title, candidates[0].estimate_min) if candidates else (None, None)


def next_focus(view, active_task_id, active_subtask_id):
    """Só o título do que vem depois no foco (ver next_focus_item)."""
    return next_focus_item(view, active_task_id, active_subtask_id)[0]
