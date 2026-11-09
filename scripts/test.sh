#!/bin/bash
# Roda todos os testes: os puros (tests/) e os de interface GTK (tests_gtk/, precisam de tela).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" || exit 1
status=0
python3 -m unittest discover -s tests -t . "$@" || status=1
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    "$DIR/scripts/_cleanenv.sh" -m unittest discover -s tests_gtk -t . "$@" || status=1
else
    echo "(sem tela: testes de interface em tests_gtk/ ignorados)"
fi
exit $status
