"""Regras de repetição de tarefas (texto guardado em tasks.repeat_rule). Funções puras.

Formatos: None (não repete), "daily", "weekdays", "weekly:N" (N = 0 segunda … 6 domingo)
e "monthly:D" (D = dia do mês, 1–31). next_date() calcula a próxima ocorrência.
"""

import calendar
from datetime import date, datetime, timedelta

WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
NO_REPEAT_LABEL = "Não repete"


def is_valid(rule):
    if rule is None or rule in ("daily", "weekdays"):
        return True
    kind, _, value = str(rule).partition(":")
    if not value.isdigit():
        return False
    number = int(value)
    return (kind == "weekly" and 0 <= number <= 6) or (kind == "monthly" and 1 <= number <= 31)


def describe(rule):
    """'weekly:0' -> 'Toda semana (segunda)'."""
    if rule is None:
        return NO_REPEAT_LABEL
    if not is_valid(rule):
        raise ValueError(f"regra de repetição inválida: {rule!r}")
    if rule == "daily":
        return "Todo dia"
    if rule == "weekdays":
        return "Dias úteis"
    kind, _, value = rule.partition(":")
    if kind == "weekly":
        return f"Toda semana ({WEEKDAYS[int(value)]})"
    return f"Todo mês, dia {int(value)}"


def options_for(day=None):
    """Opções do seletor "Repetir", ajustadas ao dia da tarefa (padrão: hoje)."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    elif isinstance(day, datetime):
        day = day.date()
    day = day or date.today()
    rules = [None, "daily", "weekdays", f"weekly:{day.weekday()}", f"monthly:{day.day}"]
    return [(rule, describe(rule)) for rule in rules]


def next_date(rule, after):
    """Primeira data da regra estritamente depois de `after` (date, datetime ou 'AAAA-MM-DD')."""
    if not rule or not is_valid(rule):
        raise ValueError(f"regra de repetição inválida: {rule!r}")
    if isinstance(after, str):
        after = date.fromisoformat(after)
    elif isinstance(after, datetime):
        after = after.date()
    if rule == "daily":
        return after + timedelta(days=1)
    if rule == "weekdays":
        day = after + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return day
    kind, _, value = rule.partition(":")
    number = int(value)
    if kind == "weekly":
        return after + timedelta(days=(number - after.weekday() - 1) % 7 + 1)
    year, month = after.year, after.month
    while True:                                    # monthly: dia 31 vira o último dia dos meses curtos
        day = date(year, month, min(number, calendar.monthrange(year, month)[1]))
        if day > after:
            return day
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
