"""Formatação e leitura de tempos para a interface. Funções puras, sem GTK."""

import math
import re
from datetime import timedelta

from ..timer import PHASE_LABELS, Phase


def format_minutes(minutes):
    """90 -> '1h 30m', 65 -> '1h 05m', 60 -> '1h', 45 -> '45m', 0 -> '0m'."""
    minutes = max(int(round(minutes)), 0)
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest}m"
    if rest == 0:
        return f"{hours}h"
    return f"{hours}h {rest:02d}m"


def format_real(seconds):
    """Tempo real de uma tarefa: '—' sem registro, '<1m' se muito curto, senão em minutos."""
    if not seconds or seconds <= 0:
        return "—"
    minutes = round(seconds / 60)
    return "<1m" if minutes == 0 else format_minutes(minutes)


def format_clock(seconds):
    """Relógio do timer: 932 -> '15:32', 5400 -> '1:30:00'; negativo (tempo extra) -> '+02:10'."""
    sign = "+" if seconds < 0 else ""
    seconds = abs(int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{sign}{hours}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"


def delta_text(real_seconds, estimate_min):
    """Diferença real × previsto: ('↓5m', 'under'), ('↑12m', 'over') ou ('', 'even').

    Sem previsão ou sem tempo real não há o que comparar.
    """
    if not estimate_min or not real_seconds:
        return "", "even"
    diff = round(real_seconds / 60) - estimate_min
    if diff == 0:
        return "", "even"
    if diff < 0:
        return f"↓{format_minutes(-diff)}", "under"
    return f"↑{format_minutes(diff)}", "over"


def pomodoros_estimate(minutes, work_min=25):
    """Quantos pomodoros cabem na previsão (arredonda para cima)."""
    if not minutes or minutes <= 0:
        return 0
    return math.ceil(minutes / max(work_min, 1))


_HOURS_MINUTES = re.compile(
    r"^(?P<h>\d+(?:[.,]\d+)?)\s*h(?:oras?|rs?)?\s*(?:(?P<m>\d+)\s*(?:m|min|mins|minutos?)?)?$"
)
_COLON = re.compile(r"^(?P<h>\d+):(?P<m>\d{1,2})$")
_MINUTES = re.compile(r"^(?P<m>\d+)\s*(?:m|min|mins|minutos?)?$")


def parse_duration(text):
    """Lê '90', '45m', '1h30', '1h 30m', '1:30', '2h', '1,5h' como minutos; inválido -> None."""
    text = (text or "").strip().lower()
    if not text:
        return None
    if match := _COLON.match(text):
        hours, minutes = int(match["h"]), int(match["m"])
        return hours * 60 + minutes if minutes < 60 else None
    if match := _HOURS_MINUTES.match(text):
        hours = float(match["h"].replace(",", "."))
        return round(hours * 60) + int(match["m"] or 0)
    if match := _MINUTES.match(text):
        return int(match["m"])
    return None


WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def format_date_eyebrow(day):
    """date(2026, 11, 9) -> 'SEGUNDA, 9 DE NOVEMBRO' (independe do idioma do sistema)."""
    return f"{WEEKDAYS[day.weekday()]}, {day.day} de {MONTHS[day.month - 1]}".upper()


def phase_eyebrow(phase, running, started, cycle, cycles, overtime=False, compact=False):
    """Texto em maiúsculas sobre o estado do timer: 'EM FOCO · POMODORO 3 DE 4', 'PAUSA CURTA'…"""
    if phase == Phase.WORK:
        base = f"POMODORO {cycle}/{cycles}" if compact else f"POMODORO {cycle} DE {cycles}"
        if overtime:
            state = "TEMPO EXTRA"
        elif running:
            state = "EM FOCO"
        else:
            state = "PAUSADO" if started else "PRONTO PARA FOCAR"
        return f"{state} · {base}"
    label = PHASE_LABELS[phase].upper()
    if running:
        return label
    return f"{label} · {'PAUSADA' if started else 'PRONTA'}"


def progress_note(real_seconds, estimate_min, running, now):
    """Texto e fração do progresso da tarefa: (texto, 0..1, 'none' | 'ok' | 'over')."""
    if not estimate_min:
        return "Sem previsão. Defina um tempo para acompanhar o ritmo.", 0.0, "none"
    real_min = real_seconds / 60
    if real_min > estimate_min:
        over = max(round(real_min - estimate_min), 1)
        return f"Passou {format_minutes(over)} do previsto.", 1.0, "over"
    left = estimate_min - real_min
    text = f"Faltam ~{format_minutes(max(round(left), 1))} do previsto."
    if running:
        text += f" Se mantiver o ritmo, termina por volta de {(now + timedelta(minutes=left)):%H:%M}."
    return text, min(real_min / estimate_min, 1.0), "ok"


def interval_text(interval):
    """'Pausa curta de 5 min às 15:48' a partir de um item de PomodoroTimer.next_intervals()."""
    return f"{interval['label']} de {interval['seconds'] // 60} min às {interval['start']:%H:%M}"
