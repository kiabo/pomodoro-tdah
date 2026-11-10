#!/bin/sh
# Lançador instalado em /usr/bin/pomodoro-tdah
export GDK_BACKEND="${GDK_BACKEND:-x11}"
exec /usr/bin/python3 /usr/lib/pomodoro-tdah/main.py "$@"
