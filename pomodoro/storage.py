import json
import os
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "pomodoro-app"
TASKS_FILE = DATA_DIR / "tasks.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "work_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "cycles_before_long_break": 4,
}


def ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings():
    ensure_dir()
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            settings = DEFAULT_SETTINGS.copy()
            settings.update(data)
            return settings
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    ensure_dir()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def load_tasks():
    ensure_dir()
    if TASKS_FILE.exists():
        try:
            return json.loads(TASKS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_tasks(tasks):
    ensure_dir()
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


def new_task_id():
    return uuid.uuid4().hex[:8]
