"""Modelo da tela Grupos: por grupo, o dia, a semana, a precisão e as tarefas recorrentes. Sem GTK."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import stats
from .today import build_today


@dataclass
class GroupCard:
    id: str
    name: str
    color: str
    archived: bool
    work_min: int | None
    short_break_min: int | None
    require_estimate: bool
    today_count: int = 0
    week_count: int = 0
    planned_min: int = 0
    real_seconds: int = 0
    accuracy: float | None = None
    bias_ratio: float | None = None
    bias_samples: int = 0
    recurring: list = field(default_factory=list)   # [{title, rule, estimate_min}]

    @property
    def cycle_text(self):
        """'50/10' se o grupo tem ciclo próprio, senão None (usa o padrão do app)."""
        if self.work_min is None and self.short_break_min is None:
            return None
        return f"{self.work_min or '·'}/{self.short_break_min or '·'}"


def week_bounds(day):
    """(segunda, domingo) da semana de `day`, como strings ISO."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    monday = day - timedelta(days=day.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def build_group_cards(repo, day, include_archived=False):
    day_str = day if isinstance(day, str) else day.isoformat()
    view = build_today(repo, day_str)
    planned = {g.id: g.planned_min for g in view.groups}
    real = {g.id: g.real_seconds for g in view.groups}
    monday, sunday = week_bounds(day_str)
    real_by_task, _real_by_sub = repo.real_seconds_map()

    cards = []
    for group in repo.list_groups(include_archived=include_archived):
        tasks = repo.list_tasks(group_id=group["id"])
        subtasks = repo.subtasks_by_task(t["id"] for t in tasks)
        pairs, recurring = [], {}
        for task in tasks:
            if task["status"] == "done":
                estimate = task["estimate_min"]
                if estimate is None:
                    estimate = sum(s["estimate_min"] or 0 for s in subtasks[task["id"]]) or None
                pairs.append((real_by_task.get(task["id"], 0), estimate))
            if task["repeat_rule"] and task["status"] != "discarded":
                known = recurring.get(task["title"])
                if known is None or task["created_at"] > known["created_at"]:
                    recurring[task["title"]] = {"title": task["title"], "rule": task["repeat_rule"],
                                                "estimate_min": task["estimate_min"], "created_at": task["created_at"]}
        ratio, samples = stats.bias(pairs)
        cards.append(GroupCard(
            id=group["id"], name=group["name"], color=group["color"], archived=bool(group["archived"]),
            work_min=group["work_min"], short_break_min=group["short_break_min"],
            require_estimate=bool(group["require_estimate"]),
            today_count=view.group_counts.get(group["id"], 0),
            week_count=sum(1 for t in tasks if t["status"] != "discarded" and t["scheduled_for"]
                           and monday <= t["scheduled_for"] <= sunday),
            planned_min=planned.get(group["id"], 0),
            real_seconds=real.get(group["id"], 0),
            accuracy=stats.mean_accuracy(pairs),
            bias_ratio=ratio, bias_samples=samples,
            recurring=sorted(({k: v for k, v in r.items() if k != "created_at"} for r in recurring.values()),
                             key=lambda r: r["title"].casefold()),
        ))
    return cards
