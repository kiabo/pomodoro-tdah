"""Formatação e leitura de tempos para a interface. Funções puras, sem GTK."""

import math
import re


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
