#!/usr/bin/env python3
import argparse
import fcntl
import os
import sys
from pathlib import Path

if "--version" in sys.argv[1:]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pomodoro.version import __version__

    print(f"pomodoro-tdah {__version__}")
    sys.exit(0)

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
LOCK_FILE = RUNTIME_DIR / "pomodoro-app.lock"

_lock_handle = open(LOCK_FILE, "w")
try:
    fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("Pomodoro já está em execução.")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pomodoro.app import PomodoroApp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pomodoro para TDAH")
    parser.add_argument("--hidden", action="store_true", help="começa só na bandeja, sem abrir a janela")
    args = parser.parse_args()
    app = PomodoroApp(start_hidden=args.hidden)
    app.run()
