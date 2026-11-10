#!/bin/bash
# Gera dist/pomodoro-tdah_<versão>_all.deb a partir do código atual.
# Uso: scripts/build-deb.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

VERSION="$(python3 -c 'import sys; sys.path.insert(0, "."); from pomodoro.version import __version__; print(__version__)')"
PKG="pomodoro-tdah"
OUT="$DIR/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/${PKG}_${VERSION}_all"

install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/$PKG" \
    "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$ROOT/usr/share/doc/$PKG"

# Aplicação
install -m 644 main.py "$ROOT/usr/lib/$PKG/main.py"
cp -r pomodoro "$ROOT/usr/lib/$PKG/pomodoro"
cp -r icons "$ROOT/usr/lib/$PKG/icons"
find "$ROOT/usr/lib/$PKG" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$ROOT/usr" -type d -exec chmod 755 {} +
find "$ROOT/usr/lib/$PKG" -type f -exec chmod 644 {} +

# Integração com o sistema
install -m 755 packaging/pomodoro-tdah.sh "$ROOT/usr/bin/$PKG"
install -m 644 packaging/pomodoro-tdah.desktop "$ROOT/usr/share/applications/$PKG.desktop"
install -m 644 icons/pomodoro-work.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
install -m 644 README.md "$ROOT/usr/share/doc/$PKG/README.md"
[ -f LICENSE ] && install -m 644 LICENSE "$ROOT/usr/share/doc/$PKG/copyright"

SIZE_KB="$(du -sk "$ROOT/usr" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, gir1.2-notify-0.7
Recommends: gnome-session-canberra
Suggests: python3-pip
Maintainer: Fabiano <comoequetala@gmail.com>
Description: Pomodoro para pessoas com TDAH
 Timer pomodoro com grupos, tarefas e subtarefas, tempo previsto contra
 tempo real, modo compacto, planejamento do dia seguinte e análise por IA
 (estimador local e Claude opcional).
CONTROL

cat > "$ROOT/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
python3 -m compileall -q /usr/lib/pomodoro-tdah || true
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q || true
fi
exit 0
POSTINST
cat > "$ROOT/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
find /usr/lib/pomodoro-tdah -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
exit 0
PRERM
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"

mkdir -p "$OUT"
fakeroot dpkg-deb --build --root-owner-group "$ROOT" "$OUT/${PKG}_${VERSION}_all.deb" >/dev/null
echo "Gerado: $OUT/${PKG}_${VERSION}_all.deb"
