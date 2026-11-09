#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" && exec "$DIR/scripts/_cleanenv.sh" -m pomodoro.ui.gallery "$@"
