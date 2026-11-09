"""Resumo agregado do histórico que pode ser enviado à API do Claude. Só títulos, grupos e tempos."""

from .samples import collect_samples

MAX_TASKS = 60


def build_summary(repo, limit=MAX_TASKS):
    """Texto com as tarefas concluídas mais recentes: grupo, título, previsto e real em minutos."""
    names = {g["id"]: g["name"] for g in repo.list_groups(include_archived=True)}
    samples = sorted(collect_samples(repo), key=lambda s: s.done_day or "", reverse=True)[:limit]
    if not samples:
        return "Sem tarefas concluídas com previsão e tempo real ainda."
    lines = [f"- [{names.get(s.group_id, '?')}] {s.title}: previsto {s.estimate_min:.0f} min, real {s.real_min:.0f} min"
             + (f", {s.interruptions} interrupção(ões)" if s.interruptions else "")
             for s in samples]
    return "Tarefas concluídas (mais recentes primeiro):\n" + "\n".join(lines)
