"""Planejamento do dia: virada do dia, recorrência, pendências e capacidade de amanhã. Sem GTK.

Funções puras sobre o Repository. A tela "Revisar e planejar amanhã" (D7) e o Controller as usam.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import recurrence, stats
from .ai.estimator import round5

PENDING = ("todo", "doing")
DISCARD = "discard"            # destino de uma pendência (além de uma data "AAAA-MM-DD")


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def tomorrow(day):
    return _day(day) + timedelta(days=1)


# ---- virada do dia e recorrência ------------------------------------------------

def spawn_recurring(repo, today):
    """Cria a próxima ocorrência de cada tarefa recorrente já concluída ou descartada.

    A tarefa antiga perde a regra (a corrente de repetição passa para a nova), então chamar de
    novo não duplica nada. A próxima data é a primeira da regra depois da data agendada e depois de
    hoje: uma tarefa diária atrasada não gera um monte de ocorrências no passado. Devolve as novas.
    """
    today = _day(today)
    created = []
    rows = repo.conn.execute(
        "SELECT id FROM tasks WHERE repeat_rule IS NOT NULL AND status IN ('done', 'discarded')"
    ).fetchall()
    for row in rows:
        task = repo.get_task(row["id"])
        reference = max(_day(task["scheduled_for"]) if task["scheduled_for"] else today, today)
        if task["done_at"]:
            reference = max(reference, _day(task["done_at"][:10]))
        nxt = recurrence.next_date(task["repeat_rule"], reference)
        try:
            copy = repo.duplicate_task(task["id"], scheduled_for=nxt, repeat_rule=task["repeat_rule"])
        except ValueError:
            continue            # ex.: o grupo passou a exigir previsão e a tarefa não tem; não trava o dia
        repo.update_task(task["id"], repeat_rule=None)
        created.append(copy)
    return created


def roll_over(repo, today, carry=True):
    """Virada do dia: tarefas pendentes de dias anteriores vão para hoje e contam um adiamento.

    Com carry=False elas ficam como estão (a tela Hoje continua mostrando as atrasadas).
    Devolve quantas foram levadas.
    """
    if not carry:
        return 0
    today = _day(today).isoformat()
    moved = 0
    for task in repo.list_tasks(statuses=PENDING):
        if task["scheduled_for"] and task["scheduled_for"] < today:
            repo.postpone_task(task["id"], today)
            moved += 1
    return moved


def start_of_day(repo, today, carry=True):
    """Tudo o que precisa acontecer quando um dia novo começa. Devolve (levadas, recorrentes criadas)."""
    spawned = spawn_recurring(repo, today)
    return roll_over(repo, today, carry=carry), len(spawned)


# ---- revisão do dia -------------------------------------------------------------

@dataclass
class Leftover:
    """Pendência do dia à espera de um destino (amanhã, outra data ou descartar)."""
    task_id: str
    title: str
    group_name: str
    group_color: str
    subtask_title: str | None
    estimate_min: int | None
    postponed_count: int
    has_subtasks: bool


@dataclass
class DayReview:
    day: str
    done_count: int
    total_count: int
    planned_min: int
    real_seconds: int
    mood: str | None
    leftovers: list = field(default_factory=list)
    confirmed: bool = False


def effective_estimate(repo, task):
    """Previsão da tarefa: a própria ou, sem ela, a soma das subtarefas (None se não há nenhuma)."""
    if task["estimate_min"] is not None:
        return task["estimate_min"]
    return repo.subtasks_estimate_sum(task["id"])


def review_day(repo, day):
    """Resumo do dia e as pendências que ficaram. A visão é a mesma da tela Hoje."""
    day = _day(day).isoformat()
    tasks = repo.list_for_day(day)
    real_by_task, _ = repo.real_seconds_map()
    groups = {g["id"]: g for g in repo.list_groups(include_archived=True)}
    saved = repo.get_day_review(day) or {}
    leftovers = []
    for task in tasks:
        if task["status"] not in PENDING:
            continue
        subs = repo.list_subtasks(task["id"])
        pending_sub = next((s["title"] for s in subs if not s["done"]), None)
        group = groups.get(task["group_id"], {})
        leftovers.append(Leftover(
            task["id"], task["title"], group.get("name", ""), group.get("color", "#8A857C"),
            pending_sub, effective_estimate(repo, task), task["postponed_count"], bool(subs)))
    return DayReview(
        day=day, done_count=sum(1 for t in tasks if t["status"] == "done"), total_count=len(tasks),
        planned_min=sum(effective_estimate(repo, t) or 0 for t in tasks),
        real_seconds=sum(real_by_task.get(t["id"], 0) for t in tasks),
        mood=saved.get("mood"), leftovers=leftovers, confirmed=bool(saved.get("confirmed_at")))


def default_destinations(leftovers, day, carry=True):
    """Destino inicial de cada pendência: amanhã (se "levar pendências" está ligado) ou nenhum."""
    target = tomorrow(day).isoformat() if carry else None
    return {item.task_id: target for item in leftovers}


def break_suggestion(leftovers, step_min=20):
    """Aviso para a tarefa mais adiada que ainda não tem passos: (task_id, texto) ou None."""
    candidates = [item for item in leftovers if item.postponed_count >= 1 and not item.has_subtasks]
    if not candidates:
        return None
    item = max(candidates, key=lambda i: (i.postponed_count, i.estimate_min or 0))
    times = "vez" if item.postponed_count == 1 else "vezes"
    text = (f"“{item.title}” já foi adiada {item.postponed_count} {times}. "
            f"Quer quebrar em passos de {step_min} min? Tarefas menores tendem a sair do papel.")
    return item.task_id, text


def apply_destinations(repo, day, destinations):
    """Aplica o destino de cada pendência: data (reagenda e conta o adiamento) ou DISCARD.

    Valida tudo antes de gravar. Pendência sem destino (None) fica como está.
    Devolve {"moved": n, "discarded": n, "skipped": n}.
    """
    day = _day(day)
    for task_id, target in destinations.items():
        if repo.get_task(task_id) is None:
            raise KeyError(f"tarefa {task_id} não existe")
        if target not in (None, DISCARD) and _day(target) <= day:
            raise ValueError("o destino de uma pendência precisa ser depois de hoje")
    result = {"moved": 0, "discarded": 0, "skipped": 0}
    for task_id, target in destinations.items():
        if target is None:
            result["skipped"] += 1
        elif target == DISCARD:
            repo.set_task_status(task_id, "discarded")
            result["discarded"] += 1
        else:
            repo.postpone_task(task_id, _day(target).isoformat())
            result["moved"] += 1
    return result


# ---- plano de amanhã ------------------------------------------------------------

@dataclass
class PlanItem:
    task_id: str
    group_id: str
    title: str
    group_color: str
    estimate_min: int | None
    ai_min: int | None
    recurring: bool


@dataclass
class Capacity:
    planned_min: int          # o que o usuário previu
    ai_min: int               # estimativa "realista" da IA para o mesmo plano
    free_min: int
    level: str                # empty | ok | tight | over (pela estimativa da IA)
    over_min: int
    spare_min: int            # sobra para pausas (livre − IA); 0 se passou

    @property
    def planned_fraction(self):
        return min(self.planned_min / self.free_min, 1.0) if self.free_min else (1.0 if self.planned_min else 0.0)

    @property
    def ai_fraction(self):
        return min(self.ai_min / self.free_min, 1.0) if self.free_min else (1.0 if self.ai_min else 0.0)


def free_minutes_for(repo, day, default):
    """Tempo livre do dia: o que o usuário informou para ele ou, sem isso, o padrão das configurações."""
    review = repo.get_day_review(_day(day).isoformat()) or {}
    return review.get("free_minutes") if review.get("free_minutes") is not None else default


def plan_items(repo, day, estimator=None, samples=None):
    """Tarefas agendadas para `day` (pendentes), na ordem de grupo e posição, com a previsão da IA."""
    day = _day(day).isoformat()
    groups = {g["id"]: g for g in repo.list_groups()}
    rows = [t for t in repo.list_tasks(scheduled_for=day, statuses=PENDING) if t["group_id"] in groups]
    rows.sort(key=lambda t: (groups[t["group_id"]]["position"], groups[t["group_id"]]["created_at"],
                             t["position"], t["created_at"]))
    if estimator is not None and samples is None:
        samples = estimator.collect(repo)
    items = []
    for task in rows:
        estimate = effective_estimate(repo, task)
        ai = estimate
        if estimator is not None and estimate:
            prediction = estimator.predict_from(samples, task["title"], task["group_id"], exclude_task_id=task["id"])
            if prediction is not None:
                ai = round5(estimate * prediction.ratio)
        items.append(PlanItem(task["id"], task["group_id"], task["title"], groups[task["group_id"]]["color"],
                              estimate, ai, bool(task["repeat_rule"])))
    return items


def capacity(items, free_min):
    """Previsto × estimativa da IA × tempo livre de um conjunto de tarefas."""
    planned = sum(i.estimate_min or 0 for i in items)
    ai = sum((i.ai_min if i.ai_min is not None else i.estimate_min) or 0 for i in items)
    level, over = stats.capacity_level(ai, free_min)
    return Capacity(planned, ai, free_min, level, over, max((free_min or 0) - ai, 0))


def reorder_within_groups(repo, ordered_ids):
    """Grava a ordem de uma lista que mistura grupos: cada grupo mantém os mesmos "lugares", só troca quem os ocupa.

    A posição das tarefas é por grupo (é assim que a tela Hoje as mostra), então arrastar uma tarefa
    para outro grupo não muda nada; dentro do grupo muda.
    """
    by_group = {}
    for task_id in ordered_ids:
        task = repo.get_task(task_id)
        if task is not None:
            by_group.setdefault(task["group_id"], []).append(task_id)
    for group_id, wanted in by_group.items():
        full = [t["id"] for t in repo.list_tasks(group_id=group_id)]
        slots = [i for i, task_id in enumerate(full) if task_id in set(wanted)]
        for slot, task_id in zip(slots, wanted):
            full[slot] = task_id
        repo.reorder_tasks(group_id, full)


def confirm_plan(repo, day, free_minutes=None):
    """Marca a revisão do dia como confirmada (guarda o tempo livre de amanhã, se informado)."""
    return repo.save_day_review(_day(day).isoformat(), free_minutes=free_minutes, confirmed=True)
