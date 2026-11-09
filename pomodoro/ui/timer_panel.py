"""Painel do timer da tela Hoje: anel, controles, próximos intervalos e progresso da tarefa."""

from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from ..timer import Phase
from .format import format_clock, format_minutes, format_real, interval_text, phase_eyebrow, progress_note
from .layout import FixedWidthBox, button, expand, hbox, label, vbox
from .theme import COLORS, style
from .widgets import GroupDot, ProgressRing, make_bar, set_bar_fraction

PHASE_COLORS = {Phase.WORK: COLORS["focus"], Phase.SHORT_BREAK: COLORS["green"], Phase.LONG_BREAK: COLORS["primary"]}
WIDTH = 340


class TimerPanel(FixedWidthBox):
    def __init__(self, controller):
        super().__init__(WIDTH, orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.controller = controller
        self._context = {"task_id": None, "task_title": None, "subtask_title": None,
                         "estimate_min": None, "next_title": None}
        self.pack_start(self._build_timer_card(), False, False, 0)
        self.pack_start(self._build_intervals_card(), False, False, 0)
        self.pack_start(self._build_progress_card(), False, False, 0)
        self.refresh()

    # ---- montagem -------------------------------------------------------

    def _build_timer_card(self):
        self.phase_label = label("", "eyebrow", "text-amber-bright", center=True)
        self.title_label = label("", "title-md", "text-on-dark", center=True, wrap=True)
        self.title_label.set_max_width_chars(26)
        self.subtitle_label = label("", "caption", "text-dark-muted", center=True, ellipsize=True)
        self.ring = ProgressRing(size=184, thickness=10, color=COLORS["focus"], dark=True)

        self.stop_button = button("■", "btn-dark-soft", "btn-round", tooltip="Zerar o relógio desta fase",
                                  on_click=self.controller.reset_phase)
        self.play_button = button("▶", "btn-focus", "btn-round", "btn-round-lg", tooltip="Iniciar / pausar",
                                  on_click=self.controller.toggle_timer)
        self.done_button = button("✓", "btn-green", "btn-round", on_click=self._on_done)
        controls = hbox(self.stop_button, self.play_button, self.done_button, spacing=16)
        controls.set_halign(Gtk.Align.CENTER)
        self.skip_button = button("Pular fase  ⏭", "btn-link-dark", tooltip="Passar para a próxima fase",
                                  on_click=self.controller.skip_phase)
        self.skip_button.set_halign(Gtk.Align.CENTER)
        titles = vbox(self.title_label, self.subtitle_label, spacing=2)
        return vbox(self.phase_label, titles, self.ring, controls, self.skip_button,
                    spacing=14, classes=("card-dark", "card-timer"))

    def _build_intervals_card(self):
        self._interval_rows = []
        rows = []
        for _ in range(3):
            dot = GroupDot(COLORS["green"], size=8, radius=4)
            text = expand(label("", "text2", ellipsize=True))
            when = label("", "text2")
            self._interval_rows.append((dot, text, when))
            rows.append(hbox(dot, text, when, spacing=10))
        return vbox(label("PRÓXIMOS INTERVALOS", "eyebrow"), *rows, spacing=10, classes=("card",))

    def _build_progress_card(self):
        self.progress_title = label("", "bold", "small", ellipsize=True)
        self.progress_numbers = label("", "caption", "muted")
        self.progress_bar = make_bar(0, "green", thin=True)
        self.progress_text = label("", "small", "text2", wrap=True)
        header = hbox(expand(self.progress_title), self.progress_numbers, spacing=8)
        self.progress_card = vbox(header, self.progress_bar, self.progress_text, spacing=8, classes=("card-soft",))
        return self.progress_card

    # ---- ações ----------------------------------------------------------

    def _on_done(self):
        self.controller.complete_current()

    # ---- dados ----------------------------------------------------------

    def set_context(self, task_id, task_title, subtask_title, estimate_min, next_title):
        """Chamado quando a tarefa em foco, os dados ou a lista mudam (não a cada segundo)."""
        self._context = {"task_id": task_id, "task_title": task_title, "subtask_title": subtask_title,
                         "estimate_min": estimate_min, "next_title": next_title}
        self.refresh()

    def refresh(self):
        self._refresh_card()
        self._refresh_intervals()
        self._refresh_progress()

    def _refresh_card(self):
        timer = self.controller.timer
        ctx = self._context
        settings = self.controller.settings
        self.phase_label.set_text(phase_eyebrow(
            timer.phase, timer.running, timer.started, timer.cycle,
            settings["cycles_before_long_break"], overtime=timer.in_overtime,
        ))
        if timer.phase == Phase.WORK:
            if ctx["subtask_title"]:
                self.title_label.set_text(ctx["subtask_title"])
                self.subtitle_label.set_text(ctx["task_title"] or "")
            elif ctx["task_title"]:
                self.title_label.set_text(ctx["task_title"])
                self.subtitle_label.set_text("")
            else:
                self.title_label.set_text("Escolha uma tarefa para focar")
                self.subtitle_label.set_text("ou comece um foco livre")
        else:
            self.title_label.set_text("Hora de respirar")
            self.subtitle_label.set_text("Levante, alongue e beba água. Longe da tela.")

        total = max(timer.phase_total, 1)
        fraction = 1.0 if timer.in_overtime else (total - timer.remaining) / total
        self.ring.set_fraction(fraction)
        self.ring.set_color(COLORS["amber"] if timer.in_overtime else PHASE_COLORS[timer.phase])
        self.ring.set_time(format_clock(timer.remaining))
        self.ring.set_caption("tempo extra" if timer.in_overtime else f"de {format_clock(timer.phase_total)}")
        self.play_button.set_label("❚❚" if timer.running else "▶")
        in_work = timer.phase == Phase.WORK
        self.done_button.set_sensitive(in_work and (ctx["task_id"] is not None))
        self.done_button.set_tooltip_text("Concluir subtarefa" if ctx["subtask_title"] else "Concluir tarefa")

    def _refresh_intervals(self):
        timer = self.controller.timer
        intervals = timer.next_intervals(now=datetime.now(), count=3)
        for index, ((dot, text, when), item) in enumerate(zip(self._interval_rows, intervals)):
            dot.set_color(PHASE_COLORS[item["phase"]])
            if item["phase"] == Phase.WORK:
                title = self._context["next_title"]
                text.set_text(f"Foco · {title}" if title else "Foco")
            else:
                text.set_text(f"{item['label']} · {item['seconds'] // 60} min")
            when.set_text(f"{item['start']:%H:%M}")
            for widget in (text, when):
                context = widget.get_style_context()
                (context.add_class if index == 0 else context.remove_class)("bold")
                (context.remove_class if index == 0 else context.add_class)("muted")

    def _refresh_progress(self):
        ctx = self._context
        task_id = ctx["task_id"]
        self.progress_card.set_visible(task_id is not None)
        if task_id is None:
            return
        timer = self.controller.timer
        real = self.controller.tracker.live_real_seconds(task_id)
        text, fraction, kind = progress_note(
            real, ctx["estimate_min"], timer.running and timer.phase == Phase.WORK, datetime.now())
        self.progress_title.set_text(ctx["task_title"] or "")
        estimate = format_minutes(ctx["estimate_min"]) if ctx["estimate_min"] else "—"
        self.progress_numbers.set_text(f"Real {format_real(real)} / Prev {estimate}")
        self.progress_text.set_text(text)
        set_bar_fraction(self.progress_bar, fraction)
        bar = self.progress_bar.get_style_context()
        bar.remove_class("bar-green")
        bar.remove_class("bar-focus")
        bar.add_class("bar-focus" if kind == "over" else "bar-green")
