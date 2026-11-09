"""Cálculos de desempenho: precisão das previsões e capacidade do dia. Funções puras."""


def accuracy(real_seconds, estimate_min):
    """Precisão de uma previsão: 1 - |real - previsto| / previsto, entre 0 e 1.

    Sem previsão ou sem tempo real não há o que medir (None).
    """
    if not estimate_min or not real_seconds or real_seconds <= 0:
        return None
    real_min = real_seconds / 60
    return max(0.0, 1 - abs(real_min - estimate_min) / estimate_min)


def mean_accuracy(pairs):
    """Média da precisão de [(real_seconds, estimate_min), ...], ignorando o que não dá para medir."""
    values = [a for a in (accuracy(real, est) for real, est in pairs) if a is not None]
    return sum(values) / len(values) if values else None


def capacity_level(planned_min, free_min):
    """Como o planejado se encaixa no tempo livre: (nível, minutos que passam do livre).

    Níveis: "empty" (nada planejado), "ok" (até 75% do livre, com folga para pausas),
    "tight" (cabe, mas sem folga) e "over" (passa do tempo livre).
    """
    if not planned_min or planned_min <= 0:
        return "empty", 0
    if free_min is None or free_min <= 0:
        return "over", planned_min
    if planned_min <= free_min * 0.75:
        return "ok", 0
    if planned_min <= free_min:
        return "tight", 0
    return "over", planned_min - free_min
