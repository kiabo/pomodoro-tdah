"""Configurações do app em JSON (settings.json), com padrões e validação de tipos.

As tarefas e o histórico ficam no SQLite (ver db.py); aqui ficam só as preferências.
"""

import json
import os
from pathlib import Path


def data_dir():
    """Pasta de dados do app. POMODORO_DATA_DIR permite apontar para outra (ex.: testes)."""
    override = os.environ.get("POMODORO_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "pomodoro-app"


SETTINGS_FILENAME = "settings.json"

COMPACT_FIELDS = ("remaining", "current_task", "next_break", "progress", "estimate_vs_real")

DEFAULT_SETTINGS = {
    # Ciclo do pomodoro
    "work_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "cycles_before_long_break": 4,
    "auto_start_breaks": True,
    "auto_start_work": False,
    "count_overtime": True,
    # Apoio para TDAH
    "warn_before_end_min": 2,          # 0 desliga o aviso suave
    "hyperfocus_alert": True,
    "hyperfocus_threshold_pct": 150,   # avisa quando o real passa deste % do previsto
    "carry_over_unfinished": True,
    "one_thing_at_a_time": False,
    "ask_difficulty": True,
    # Modo compacto
    "compact_always_on_top": True,
    "compact_on_focus_start": True,
    "compact_idle_opacity": 0.7,
    "compact_position": None,          # [x, y] ou None (canto superior direito)
    "compact_fields": ["remaining", "current_task", "next_break", "progress"],
    # Sons e notificações
    "end_sound": "complete",           # id de evento do tema de sons (canberra) ou "" para mudo
    "ambient_sound": "",               # "" = nenhum
    "ticking": False,
    "system_notifications": True,
    # Planejamento do dia
    "free_minutes_per_day": 360,
    "end_of_day_reminder": "18:00",    # "" desliga
    # IA
    "ai_enabled": True,                # estimativas locais
    "ai_cloud_enabled": False,         # textos/subtarefas via Claude API (opcional)
    "anthropic_api_key": "",           # se vazio, usa a variável ANTHROPIC_API_KEY
}

_RANGES = {
    "work_min": (1, 180),
    "short_break_min": (1, 60),
    "long_break_min": (1, 120),
    "cycles_before_long_break": (1, 12),
    "warn_before_end_min": (0, 30),
    "hyperfocus_threshold_pct": (100, 500),
    "free_minutes_per_day": (0, 24 * 60),
}


def _valid(key, value):
    default = DEFAULT_SETTINGS[key]
    if key == "compact_position":
        return value is None or (
            isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        )
    if key == "compact_fields":
        return isinstance(value, list) and all(v in COMPACT_FIELDS for v in value)
    if key == "compact_idle_opacity":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.2 <= value <= 1.0
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        lo, hi = _RANGES.get(key, (None, None))
        return lo is None or lo <= value <= hi
    if isinstance(default, str):
        return isinstance(value, str)
    return False


def sanitize(data):
    """Mescla data sobre os padrões, descartando chaves desconhecidas e valores inválidos."""
    settings = {key: (list(v) if isinstance(v, list) else v) for key, v in DEFAULT_SETTINGS.items()}
    if isinstance(data, dict):
        for key, value in data.items():
            if key in DEFAULT_SETTINGS and _valid(key, value):
                settings[key] = list(value) if isinstance(value, (list, tuple)) else value
    return settings


def load_settings(directory=None):
    path = Path(directory or data_dir()) / SETTINGS_FILENAME
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = None
    return sanitize(data)


def save_settings(settings, directory=None):
    directory = Path(directory or data_dir())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SETTINGS_FILENAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(sanitize(settings), indent=2, ensure_ascii=False))
    # O arquivo pode conter a chave da API: só o dono lê.
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def api_key(settings):
    return settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
