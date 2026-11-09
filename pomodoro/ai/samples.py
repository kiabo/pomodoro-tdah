"""Amostras do histórico: tarefas concluídas com previsão e tempo real, prontas para estatística."""

from dataclasses import dataclass
from datetime import datetime

from . import text

MIN_REAL_SECONDS = 60


@dataclass(frozen=True)
class Sample:
    task_id: str
    title: str
    group_id: str
    estimate_min: float
    real_min: float
    stems: frozenset
    has_subtasks: bool
    start_hour: int | None          # hora em que o primeiro foco da tarefa começou
    interruptions: int
    done_day: str | None            # AAAA-MM-DD da conclusão

    @property
    def ratio(self):
        """real ÷ previsto: > 1 levou mais do que o previsto."""
        return self.real_min / self.estimate_min


def collect_samples(repo):
    """Todas as tarefas concluídas que dá para medir (com previsão e pelo menos 1 min de tempo real)."""
    tasks = repo.list_tasks(statuses=("done",))
    subtasks = repo.subtasks_by_task(t["id"] for t in tasks)
    real_by_task, _ = repo.real_seconds_map()
    first_hour, interruptions = {}, {}
    for session in repo.list_sessions(kinds=("work",)):
        task_id = session["task_id"]
        if task_id is None:
            continue
        hour = datetime.fromisoformat(session["started_at"]).hour
        first_hour.setdefault(task_id, hour)            # list_sessions vem em ordem de início
        if session["interrupted"]:
            interruptions[task_id] = interruptions.get(task_id, 0) + 1

    samples = []
    for task in tasks:
        subs = subtasks[task["id"]]
        estimate = task["estimate_min"]
        if estimate is None:
            estimate = sum(s["estimate_min"] or 0 for s in subs) or None
        real_seconds = real_by_task.get(task["id"], 0)
        if not estimate or real_seconds < MIN_REAL_SECONDS:
            continue
        samples.append(Sample(
            task_id=task["id"], title=task["title"], group_id=task["group_id"],
            estimate_min=float(estimate), real_min=real_seconds / 60, stems=text.stems(task["title"]),
            has_subtasks=len(subs) > 0, start_hour=first_hour.get(task["id"]),
            interruptions=interruptions.get(task["id"], 0),
            done_day=(task["done_at"] or "")[:10] or None,
        ))
    return samples
