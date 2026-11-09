"""Galeria de componentes do design system (para desenvolver e conferir o visual).

  scripts/gallery.sh                 abre a janela
  scripts/gallery.sh --png saida.png gera uma imagem sem abrir janela
"""

import argparse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .theme import COLORS, GROUP_COLORS, load_theme, style, themed_window
from .widgets import (BarChart, ChoiceGroup, GroupDot, ProgressRing, StatusPill, TimeStepper,
                      make_bar, make_toggle)

WEEK = [
    {"label": "Seg", "planned": 102, "real": 119},
    {"label": "Ter", "planned": 153, "real": 143},
    {"label": "Qua", "planned": 136, "real": 170},
    {"label": "Qui", "planned": 119, "real": 112},
    {"label": "Sex", "planned": 102, "real": 129},
    {"label": "Sáb", "planned": 34, "real": 41},
    {"label": "Dom", "planned": 17, "real": 17},
]


def hbox(*children, spacing=10, valign=Gtk.Align.CENTER):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    box.set_valign(valign)
    for child in children:
        child.set_valign(valign)
        box.pack_start(child, False, False, 0)
    return box


def vbox(*children, spacing=8):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for child in children:
        box.pack_start(child, False, False, 0)
    return box


def label(text, *classes, xalign=0.0):
    widget = style(Gtk.Label(label=text), *classes)
    widget.set_xalign(xalign)
    return widget


def button(text, *classes):
    return style(Gtk.Button(label=text), "btn", *classes)


def section(title, *children):
    return vbox(label(title.upper(), "eyebrow"), *children, spacing=10)


def card(*children, classes=("card",), spacing=10):
    box = vbox(*children, spacing=spacing)
    return style(box, *classes)


def typography():
    return section(
        "Tipografia",
        label("Hoje", "title-xl"),
        label("Escrever relatório mensal", "title-md"),
        label("Grupos de tarefas", "section-title"),
        label("Corpo de texto normal, 14px, com cor de tinta do design.", ),
        label("Texto secundário (muted) e legendas pequenas", "muted", "small"),
        label("4h 30m   2h 10m   5 de 10   82%", "stat-value"),
    )


def buttons():
    play = button("▶", "btn-focus", "btn-round", "btn-round-sm")
    pause = button("❚❚", "btn-focus", "btn-round", "btn-round-lg")
    stop = button("■", "btn-dark-soft", "btn-round")
    done = button("✓", "btn-green", "btn-round")
    disabled = button("Desativado", "btn-primary")
    disabled.set_sensitive(False)
    dark_row = style(hbox(stop, pause, done, spacing=16), "card-dark")
    return section(
        "Botões",
        hbox(button("＋  Nova tarefa", "btn-primary"), button("Duplicar p/ amanhã", "btn-secondary"),
             button("Excluir", "btn-danger"), button("Usar 1h 20m", "btn-dark"),
             button("Aplicar previsões", "btn-amber"), disabled),
        hbox(button("▶  Focar nesta tarefa", "btn-focus"), button("Manter 45m", "btn-amber-outline"),
             button("Iniciar pausa de 5 min", "btn-mint"), button("+ Novo grupo", "btn-ghost"),
             button("+ Subtarefa", "btn-link"), play),
        dark_row,
    )


def inputs():
    search = style(Gtk.Entry(), "input")
    search.set_placeholder_text("Buscar ou adicionar tarefa…")
    search.set_size_request(300, -1)
    big = style(Gtk.Entry(), "input", "input-large")
    big.set_text("Preparar apresentação para o cliente")
    big.set_size_request(380, -1)
    stepper = TimeStepper(90, step=5)
    stepper.set_halign(Gtk.Align.START)
    stepper_card = style(vbox(label("⏱ PREVISTO (sua estimativa)", "eyebrow", "text-primary"), stepper,
                              label(f"≈ 4 pomodoros · soma das subtarefas: 1h 30m ✓", "caption", "muted")),
                         "card", "card-selected")
    return section("Campos", hbox(search, big), stepper_card)


def choices():
    when = ChoiceGroup([("today", "Hoje"), ("tomorrow", "Amanhã"), ("date", "Data…")], "today")
    energy = ChoiceGroup([("low", "Baixa"), ("mid", "Média"), ("high", "Alta")], "high")
    times = ChoiceGroup(
        [(15, "15m"), (25, "25m"), (45, "45m"), (60, "1h"), (90, "1h 30m"), (120, "2h")], 45, "chips")
    groups = ChoiceGroup([("w", "Trabalho"), ("h", "Casa"), ("s", "Estudos")], "w", "chips-pill")
    return section("Escolhas", hbox(when, energy), times, groups)


def toggles():
    rows = [(True, "Iniciar pausas automaticamente"), (False, "Iniciar o próximo foco automaticamente"),
            (True, "Alerta de hiperfoco")]
    return section("Interruptores", *[
        hbox(make_toggle(on), label(text), spacing=14) for on, text in rows
    ])


def status_and_bars():
    pills = hbox(StatusPill("done"), StatusPill("doing"), StatusPill("todo"), StatusPill("discarded"),
                 style(Gtk.Label(label="✦ IA"), "pill", "pill-ai"))
    dots = hbox(*[GroupDot(c) for c in GROUP_COLORS], spacing=10)
    bars = vbox(
        make_bar(0.55, "primary"), make_bar(0.8, "green"), make_bar(0.3, "focus"),
        make_bar(0.62, "amber"), make_bar(0.45, "pink"),
        spacing=10,
    )
    bars.set_size_request(380, -1)
    return section("Status, grupos e barras", pills, dots, bars)


def rings():
    light = ProgressRing(size=160, thickness=10, color=COLORS["primary"], dark=False)
    light.set_fraction(0.62)
    light.set_time("62%")
    light.set_caption("do previsto")
    dark = ProgressRing(size=200, thickness=10, color=COLORS["focus"], dark=True)
    dark.set_fraction(0.38)
    dark.set_time("15:32")
    dark.set_caption("de 25:00")
    timer = card(label("EM FOCO · POMODORO 3 DE 4", "eyebrow", "text-amber"),
                 label("Montar gráficos", "title-md", "text-on-dark"), dark,
                 make_bar(0.45, "mint", dark=True, thin=True), classes=("card-dark",), spacing=14)
    return section("Anéis e painel do timer", hbox(light, timer, spacing=24, valign=Gtk.Align.START))


def chart():
    legend = hbox(label("■ Previsto", "caption", "text-primary-soft"), label("■ Real dentro", "caption", "text-primary"),
                  label("■ Real acima", "caption", "text-focus"), spacing=14)
    box = card(label("Previsto vs real por dia", "card-title"), legend, BarChart(WEEK, height=200),
               classes=("card", "card-lg"))
    box.set_size_request(560, -1)
    return section("Gráfico", box)


def nav_and_tasks():
    nav = vbox(*[
        _nav(text, active) for text, active in
        (("Hoje", True), ("Revisar e planejar amanhã", False), ("Grupos", False), ("✦ Análise da IA", False))
    ], spacing=2)
    nav.set_size_request(220, -1)
    sidebar = style(vbox(nav), "sidebar")
    sidebar.set_border_width(12)

    def task(title, meta, classes, check):
        row = hbox(label(check, "text-green" if check == "✓" else "muted"),
                   vbox(label(title, "bold" if "task-row-focus" in classes else ""),
                        label(meta, "caption", "muted"), spacing=2),
                   spacing=12)
        return style(row, *classes)

    rows = vbox(
        task("Responder e-mails do cliente", "Prev 20m   Real 15m  ↓5m", ("task-row", "task-row-done"), "✓"),
        task("Escrever relatório mensal", "Prev 1h 30m   Real 50m · cronometrando", ("task-row", "task-row-focus"), "○"),
        task("Lavar roupa", "Prev 30m", ("task-row",), "○"),
        card(label("＋ Despeje aqui o que veio à cabeça", "faint"), classes=("card-dashed",)),
        spacing=8,
    )
    rows.set_size_request(380, -1)
    return section("Navegação e linhas de tarefa", hbox(sidebar, rows, spacing=20, valign=Gtk.Align.START))


def _nav(text, active):
    btn = style(Gtk.ToggleButton(label=text), "nav-item")
    btn.set_active(active)
    btn.get_child().set_xalign(0.0)
    return btn


def ai_cards():
    ai = card(label("✦ SUGESTÃO DA IA", "eyebrow", "text-amber"),
              label("Tarefas parecidas levaram em média 1h 20m para você.", "text-amber-dark", "small"),
              hbox(button("Usar 1h 20m", "btn-dark"), button("Manter 45m", "btn-amber-outline")),
              classes=("card", "card-ai"))
    green = card(label("◷ REAL (cronometrado)", "eyebrow", "text-green-dark"), label("50m", "stat-value"),
                 classes=("card", "card-green"))
    primary = card(label("⏱ PREVISTO", "eyebrow", "text-primary"), label("1h 30m", "stat-value"),
                   classes=("card", "card-primary"))
    for widget in (ai, green, primary):
        widget.set_size_request(250, -1)
    return section("Cartões", hbox(primary, green, ai, spacing=14, valign=Gtk.Align.START))


def build_gallery():
    load_theme()
    columns = hbox(
        vbox(typography(), buttons(), inputs(), choices(), toggles(), spacing=22),
        vbox(status_and_bars(), rings(), chart(), nav_and_tasks(), ai_cards(), spacing=22),
        spacing=40, valign=Gtk.Align.START,
    )
    columns.set_border_width(28)
    return columns


def render_png(path, width=1480):
    """Desenha a galeria fora da tela e salva em PNG."""
    window = Gtk.OffscreenWindow()
    themed_window(window)
    window.add(build_gallery())
    window.set_size_request(width, -1)
    window.show_all()
    for _ in range(3):  # deixa o GTK calcular o layout
        while Gtk.events_pending():
            Gtk.main_iteration()
    _, natural = window.get_preferred_height_for_width(width)
    window.set_size_request(width, natural)
    window.resize(width, natural)
    for _ in range(3):
        while Gtk.events_pending():
            Gtk.main_iteration()
    window.get_pixbuf().savev(path, "png", [], [])
    return width, natural


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", help="salva a galeria neste arquivo PNG em vez de abrir a janela")
    args = parser.parse_args()
    if args.png:
        print("PNG %dx%d -> %s" % (*render_png(args.png), args.png))
        return
    window = themed_window(Gtk.Window(title="Galeria — Pomodoro TDAH"))
    scrolled = Gtk.ScrolledWindow()
    scrolled.add(build_gallery())
    window.add(scrolled)
    window.set_default_size(1500, 900)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
