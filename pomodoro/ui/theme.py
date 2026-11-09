"""Carrega o tema (theme.css) e oferece utilitários de estilo para os widgets."""

import logging
from pathlib import Path

import cairo  # noqa: F401  (registra o conversor do cairo.Context usado nos sinais "draw")
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_foreign("cairo")
except ImportError as error:
    raise ImportError(
        "Falta o pacote python3-gi-cairo (desenho do timer e dos gráficos). "
        "Instale com: sudo apt install python3-gi-cairo"
    ) from error
from gi.repository import Gdk, Gtk

from .tokens import COLORS, GROUP_COLORS, hex_to_rgb  # noqa: F401  (reexportados)

log = logging.getLogger(__name__)

THEME_PATH = Path(__file__).with_name("theme.css")
APP_WINDOW_CLASS = "app-window"


def rgba(color, alpha=1.0):
    return Gdk.RGBA(*hex_to_rgb(color), alpha)


def parse_theme():
    """Lê o theme.css sem aplicá-lo. Devolve (provider, lista de erros de CSS)."""
    provider = Gtk.CssProvider()
    errors = []
    provider.connect("parsing-error", lambda _p, section, error: errors.append(
        f"linha {section.get_start_line() + 1}: {error.message}"
    ))
    provider.load_from_path(str(THEME_PATH))
    return provider, errors


_applied = None


def load_theme(screen=None):
    """Aplica o tema à tela (uma vez por processo). Devolve o provider."""
    global _applied
    if _applied is not None:
        return _applied
    provider, errors = parse_theme()
    for message in errors:
        log.warning("theme.css: %s", message)
    screen = screen or Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _applied = provider
    return provider


def style(widget, *classes):
    """Adiciona classes CSS ao widget e o devolve (permite encadear na criação)."""
    context = widget.get_style_context()
    for name in classes:
        context.add_class(name)
    return widget


def themed_window(window):
    """Marca uma janela/diálogo para receber o fundo, a fonte e a cor de texto do tema."""
    load_theme()
    return style(window, APP_WINDOW_CLASS)
