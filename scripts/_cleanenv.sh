#!/bin/bash
# Roda um comando com o ambiente limpo, mantendo só o necessário para abrir janelas.
# Terminais de apps instalados via snap (ex.: VS Code) injetam bibliotecas que derrubam o PyGObject.
exec env -i HOME="$HOME" PATH=/usr/bin:/bin LANG="${LANG:-C.UTF-8}" \
    DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    XDG_DATA_DIRS="$XDG_DATA_DIRS" GDK_BACKEND=x11 POMODORO_DATA_DIR="$POMODORO_DATA_DIR" \
    /usr/bin/python3 "$@"
