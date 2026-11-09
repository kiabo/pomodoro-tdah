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


def walk(widget):
    """Percorre o widget e todos os descendentes."""
    yield widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            yield from walk(child)
    elif hasattr(widget, "get_child") and widget.get_child() is not None:
        yield from walk(widget.get_child())


def find(widget, predicate):
    return [w for w in walk(widget) if predicate(w)]


def labels(widget):
    from gi.repository import Gtk
    return [w.get_text() for w in walk(widget) if isinstance(w, Gtk.Label)]


def with_class(widget, css_class):
    return find(widget, lambda w: w.get_style_context().has_class(css_class))


def click_event(button=1):
    from gi.repository import Gdk
    event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    event.button = button
    return event


def make_controller(tmpdir, **settings):
    """Controlador de teste: relógio falso, hoje fixo e sem notificações/som."""
    from datetime import date, datetime

    from pomodoro import settings as settings_mod
    from pomodoro.controller import Controller
    from tests.test_repository import FakeClock
    from tests.test_timer import FakeScheduler

    base = {"work_min": 25, "short_break_min": 5, "long_break_min": 15, "warn_before_end_min": 0}
    base.update(settings)
    clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
    controller = Controller(
        data_dir=tmpdir, settings=settings_mod.sanitize(base), scheduler=FakeScheduler(),
        now=clock, today=lambda: date(2026, 11, 9),
    )
    return controller


def populate(controller):
    """Trabalho: E-mails (feita), Relatório (2 subtarefas); Casa: Lavar roupa."""
    repo = controller.repo
    work = repo.update_group(repo.default_group_id(), name="Trabalho", color="#5B5BD6")
    home = repo.create_group("Casa", color="#3DAA7D")
    emails = controller.add_task("Responder e-mails", 20, work["id"])
    session = repo.start_session("work", task_id=emails["id"])
    repo.end_session(session, 15 * 60, completed_phase=True)
    controller.set_task_done(emails["id"], True)
    report = controller.add_task("Escrever relatório", 90, work["id"])
    numbers = controller.add_subtask(report["id"], "Levantar números", 25)
    charts = controller.add_subtask(report["id"], "Montar gráficos", 30)
    laundry = controller.add_task("Lavar roupa", 30, home["id"])
    return {"work": work, "home": home, "emails": emails, "report": report,
            "numbers": numbers, "charts": charts, "laundry": laundry}
