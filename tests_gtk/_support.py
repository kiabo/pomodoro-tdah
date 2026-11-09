"""Apoio aos testes de interface: pula tudo se não houver tela ou o pacote python3-gi-cairo."""

import unittest


def require_gtk():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        from pomodoro.ui import theme  # noqa: F401  (falha com mensagem clara se faltar gi-cairo)
    except (ImportError, ValueError) as error:
        raise unittest.SkipTest(f"GTK indisponível: {error}")
    ok = Gtk.init_check()
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        raise unittest.SkipTest("sem tela (DISPLAY) para os testes de interface")


def pump():
    from gi.repository import Gtk
    for _ in range(4):
        while Gtk.events_pending():
            Gtk.main_iteration()


def render(widget, width, height):
    """Desenha o widget fora da tela e devolve uma função pixel(x, y) -> (r, g, b)."""
    from gi.repository import Gtk
    from pomodoro.ui.theme import themed_window
    window = Gtk.OffscreenWindow()
    themed_window(window)
    window.add(widget)
    window.set_size_request(width, height)
    window.show_all()
    pump()
    pixbuf = window.get_pixbuf()
    pixels, stride, channels = pixbuf.get_pixels(), pixbuf.get_rowstride(), pixbuf.get_n_channels()

    def pixel(x, y):
        i = y * stride + x * channels
        return pixels[i], pixels[i + 1], pixels[i + 2]

    pixel.window = window
    return pixel


def near(actual, expected_hex, tolerance=6):
    expected = tuple(int(expected_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))
