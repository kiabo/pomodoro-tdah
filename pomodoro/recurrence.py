"""Regras de repetição de tarefas (texto guardado em tasks.repeat_rule). Funções puras.

Formatos: None (não repete), "daily", "weekdays", "weekly:N" (N = 0 segunda … 6 domingo)
e "monthly:D" (D = dia do mês, 1–31). A geração das próximas ocorrências é da Fase 9.
"""

from datetime import date, datetime

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
