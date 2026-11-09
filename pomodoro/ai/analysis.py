"""Modelo da tela Análise (D6): indicadores, gráfico por dia, precisão por grupo, padrões e previsões.

Tudo calculado localmente a partir do histórico (sem rede). Sem GTK.
"""

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .. import stats
from . import text
from .estimator import Estimator, bias_phrase, round5
from .samples import collect_samples

PERIODS = ("day", "week", "month")
PERIOD_LABELS = {"day": "Hoje", "week": "Semana", "month": "Mês"}
MIN_FOR_INSIGHT = 3
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


@dataclass
class DayBar:
    day: str
    label: str
    planned_min: float
    real_min: float


@dataclass
class GroupAccuracy:
    id: str
    name: str
    color: str
    accuracy: float | None
    ratio: float | None
    samples: int


@dataclass
class TaskPrediction:
    task_id: str
    title: str
    group_id: str
    group_name: str
    user_min: int | None
    ai_min: int | None
    confidence: int
    confidence_label: str
    current_estimate_min: int | None


@dataclass
class Analysis:
    period: str
    start: str
    end: str
    title: str
    done_count: int = 0
    focus_seconds: int = 0
    accuracy: float | None = None
    mean_deviation_min: float | None = None
    measured_count: int = 0
    days: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    insights: list = field(default_factory=list)
    predictions: list = field(default_factory=list)

    @property
    def has_data(self):
        return self.measured_count > 0 or self.focus_seconds > 0


def period_bounds(period, today):
    """(início, fim) inclusivos como datas, do período que contém `today`."""
    if isinstance(today, str):
        today = date.fromisoformat(today)
    if period == "day":
        return today, today
    if period == "week":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=6)
    if period == "month":
        return today.replace(day=1), today.replace(day=monthrange(today.year, today.month)[1])
    raise ValueError(f"período inválido: {period!r}")


def period_title(period, start, end):
    if period == "day":
        return f"Como foi seu dia · {start.day:02d}/{start.month:02d}"
    if period == "week":
        return f"Como foi sua semana · {start.day:02d}/{start.month:02d} a {end.day:02d}/{end.month:02d}"
    return f"Como foi seu mês · {start.month:02d}/{start.year}"


def _days_between(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _in_range(sample, start, end):
    return sample.done_day is not None and start.isoformat() <= sample.done_day <= end.isoformat()


def build_insights(samples, group_names):
    """Padrões simples encontrados no histórico (frases curtas). Precisa de amostras suficientes."""
    insights = []
    # 1. Tipo de tarefa (primeira palavra-chave) que mais estoura.
    by_word = defaultdict(list)
    for s in samples:
        for stem in s.stems:
            by_word[stem].append(s)
    ranked = sorted(((stem, group) for stem, group in by_word.items() if len(group) >= MIN_FOR_INSIGHT),
                    key=lambda item: -abs(text.weighted_median([s.ratio for s in item[1]]) - 1))
    if ranked:
        stem, group = ranked[0]
        ratio = text.weighted_median([s.ratio for s in group])
        if abs(ratio - 1) >= 0.15:
            word = text.display_word(stem, [s.title for s in group])
            insights.append(f"Tarefas com “{word}” ({len(group)}): {bias_phrase(ratio)}.")
    # 2. Melhor horário.
    by_hour = defaultdict(list)
    for s in samples:
        if s.start_hour is not None:
            by_hour[s.start_hour // 3 * 3].append(s)
    slots = {h: g for h, g in by_hour.items() if len(g) >= MIN_FOR_INSIGHT}
    if len(slots) >= 2:
        def error(group):
            return sum(abs(s.ratio - 1) for s in group) / len(group)
        best = min(slots, key=lambda h: error(slots[h]))
        insights.append(f"Suas previsões são mais certeiras entre {best:02d}h e {best + 3:02d}h.")
    # 3. Interrupções.
    interrupted = [s for s in samples if s.interruptions]
    clean = [s for s in samples if not s.interruptions]
    if len(interrupted) >= MIN_FOR_INSIGHT and len(clean) >= MIN_FOR_INSIGHT:
        gap = text.weighted_median([s.ratio for s in interrupted]) - text.weighted_median([s.ratio for s in clean])
        if gap >= 0.15:
            insights.append(f"Quando você é interrompido, leva ~{round(gap * 100)} pontos a mais do que o previsto.")
    # 4. Subtarefas.
    with_subs = [s for s in samples if s.has_subtasks]
    without = [s for s in samples if not s.has_subtasks]
    if len(with_subs) >= MIN_FOR_INSIGHT and len(without) >= MIN_FOR_INSIGHT:
        a = sum(max(0.0, 1 - abs(s.ratio - 1)) for s in with_subs) / len(with_subs)
        b = sum(max(0.0, 1 - abs(s.ratio - 1)) for s in without) / len(without)
        if a - b >= 0.1:
            insights.append(f"Quando você quebra em subtarefas, a precisão sobe de {round(b * 100)}% para {round(a * 100)}%.")
    # 5. Grupo com maior viés.
    worst = None
    for group_id, name in group_names.items():
        group = [s for s in samples if s.group_id == group_id]
        if len(group) >= MIN_FOR_INSIGHT:
            ratio = text.weighted_median([s.ratio for s in group])
            if worst is None or abs(ratio - 1) > abs(worst[1] - 1):
                worst = (name, ratio)
    if worst and abs(worst[1] - 1) >= 0.15:
        insights.append(f"Em {worst[0]}, {bias_phrase(worst[1])}.")
    return insights


def build_predictions(repo, samples, today, estimator=None):
    """Previsão da IA para as tarefas pendentes de hoje: você × IA × confiança."""
    estimator = estimator or Estimator()
    names = {g["id"]: g["name"] for g in repo.list_groups(include_archived=True)}
    result = []
    for task in repo.list_for_day(today):
        if task["status"] not in ("todo", "doing"):
            continue
        if task["ai_estimate_min"] and task["estimate_min"] == task["ai_estimate_min"]:
            continue                     # já ajustada pela IA: reaplicar empilharia o fator
        prediction = estimator.predict_from(samples, task["title"], task["group_id"], exclude_task_id=task["id"])
        if prediction is None:
            continue
        user = task["estimate_min"] or sum(s["estimate_min"] or 0 for s in repo.list_subtasks(task["id"])) or None
        if user:
            ai = round5(user * prediction.ratio)
        elif prediction.basis == "similar":
            ai = round5(prediction.typical_minutes)
        else:
            continue
        result.append(TaskPrediction(
            task_id=task["id"], title=task["title"], group_id=task["group_id"],
            group_name=names.get(task["group_id"], ""), user_min=user, ai_min=ai,
            confidence=prediction.confidence, confidence_label=prediction.confidence_label,
            current_estimate_min=task["estimate_min"]))
    return result


def build_analysis(repo, today, period="week", estimator=None):
    if isinstance(today, str):
        today = date.fromisoformat(today)
    start, end = period_bounds(period, today)
    samples = collect_samples(repo)
    in_period = [s for s in samples if _in_range(s, start, end)]

    done = [t for t in repo.list_tasks(statuses=("done",))
            if t["done_at"] and start.isoformat() <= t["done_at"][:10] <= end.isoformat()]
    sessions = repo.list_sessions(since=start.isoformat(), until=(end + timedelta(days=1)).isoformat(),
                                  kinds=("work", "manual"))
    focus_seconds = max(sum(s["seconds"] for s in sessions), 0)

    deviation = [abs(s.real_min - s.estimate_min) for s in in_period]
    accuracy = stats.mean_accuracy([(s.real_min * 60, s.estimate_min) for s in in_period])

    chart_start, chart_end = (period_bounds("week", today) if period == "day" else (start, end))
    per_day = {d.isoformat(): [0.0, 0.0] for d in _days_between(chart_start, chart_end)}
    for s in samples:
        if s.done_day in per_day:
            per_day[s.done_day][0] += s.estimate_min
            per_day[s.done_day][1] += s.real_min
    days = [DayBar(day=d, label=(WEEKDAYS[date.fromisoformat(d).weekday()] if period != "month"
                                 else str(date.fromisoformat(d).day)),
                   planned_min=v[0], real_min=v[1]) for d, v in per_day.items()]

    groups = []
    for group in repo.list_groups():
        pairs = [(s.real_min * 60, s.estimate_min) for s in in_period if s.group_id == group["id"]]
        ratio, count = stats.bias(pairs, min_samples=1)
        if count:
            groups.append(GroupAccuracy(group["id"], group["name"], group["color"],
                                        stats.mean_accuracy(pairs), ratio, count))
    groups.sort(key=lambda g: -(g.accuracy or 0))

    names = {g["id"]: g["name"] for g in repo.list_groups(include_archived=True)}
    return Analysis(
        period=period, start=start.isoformat(), end=end.isoformat(), title=period_title(period, start, end),
        done_count=len(done), focus_seconds=focus_seconds, accuracy=accuracy,
        mean_deviation_min=sum(deviation) / len(deviation) if deviation else None,
        measured_count=len(in_period), days=days, groups=groups,
        insights=build_insights(samples, names),
        predictions=build_predictions(repo, samples, today, estimator),
    )
