"""Modo compacto: janelinha sempre à vista com o essencial do foco.

Estados (ver o design C1–C6): foco (C1, que se expande ao passar o mouse: C4), pausa (C2), pílula mini (C3),
alerta de hiperfoco (C5) e "como foi?" ao fim do pomodoro (C6).
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from . import compact_geometry
from .format import (compact_eyebrow, format_clock, format_minutes, format_real, next_interval_hint)
from .layout import button, expand, hbox, label, vbox
from .theme import COLORS, load_theme, style
from .widgets import GroupDot, make_bar, set_bar_fraction
from ..timer import Phase

CARD_WIDTH = 360
HOVER_OPEN_MS = 250
HOVER_CLOSE_MS = 450
SAVE_POSITION_MS = 700
RATING_TIMEOUT_S = 90
FEEDBACK_MS = 2500
DOUBLE_CLICK_MS = 350
DIFFICULTIES = [("easy", "Fácil"), ("ok", "Ok"), ("hard", "Difícil")]
PHASE_DOT = {Phase.WORK: COLORS["focus"], Phase.SHORT_BREAK: COLORS["mint"], Phase.LONG_BREAK: COLORS["mint"]}


def _icon(text, tooltip, callback):
    return button(text, "btn-icon-dark", tooltip=tooltip, on_click=callback)


def _hide_by_default(*widgets):
    """Widgets cuja visibilidade vem das opções: um show_all() de fora não pode revelá-los."""
    for widget in widgets:
        widget.set_no_show_all(True)


class FocusCard(Gtk.Box):
    """C1: tempo, tarefa, progresso e controles. C4: ao passar o mouse abre subtarefas e a captura de distrações."""

    def __init__(self, controller, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        style(self, "compact-card", "compact-dark")
        self.controller, self.host = controller, host
        self._feedback_source = None
        self.set_size_request(CARD_WIDTH, -1)

        self.dot = GroupDot(COLORS["focus"], size=8, radius=4)
        self.eyebrow = label("", "eyebrow", "text-amber-bright")
        header = hbox(self.dot, expand(self.eyebrow),
                      _icon("⤢", "Voltar ao app", host.expand_main), _icon("✕", "Esconder (continua na bandeja)", host.close_compact),
                      spacing=8)

        self.time = label("", "compact-time", "text-on-dark")
        self.title = label("", "bold", "text-on-dark", ellipsize=True)
        self.parent = label("", "caption", "text-dark-muted", ellipsize=True)
        main = hbox(self.time, expand(vbox(self.title, self.parent, spacing=2)), spacing=14)
        self.bar = make_bar(0, "focus", dark=True, thin=True)
        self.estimate = label("", "caption", "text-dark-muted")

        self.next = label("", "caption", "text-dark-muted", ellipsize=True)
        self.play = button("▶", "btn-focus", "btn-round", "btn-round-sm", tooltip="Iniciar / pausar",
                           on_click=controller.toggle_timer)
        self.done = button("✓", "btn-green", "btn-round", "btn-round-sm", tooltip="Concluir",
                           on_click=controller.complete_current)
        self.skip = button("⏭", "btn-dark-soft", "btn-round", "btn-round-sm", tooltip="Pular fase",
                           on_click=controller.skip_phase)
        footer = hbox(expand(self.next), self.play, self.done, self.skip, spacing=8)

        self.subtasks_box = vbox(spacing=6, classes=("card-dark2",))
        self.capture = Gtk.Entry()
        style(self.capture, "compact-input-field")
        self.capture.set_placeholder_text("Distraiu? Anote e volte ao foco…")
        self.capture.connect("activate", lambda *_: self.submit_capture())
        self.capture.connect("key-press-event", self._on_capture_key)
        self.feedback = label("", "caption", "text-mint")
        capture_row = hbox(expand(self.capture), label("↵", "text-amber-bright", "small"), spacing=8,
                           classes=("compact-input",))
        extra = vbox(self.subtasks_box, capture_row, self.feedback, spacing=10)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.add(extra)

        for widget in (header, main, self.bar, self.estimate, footer, self.revealer):
            self.pack_start(widget, False, True, 0)
        self.show_all()
        _hide_by_default(self.parent, self.estimate, self.subtasks_box, self.feedback, self.time, self.title,
                         self.bar, self.next)

    # ---- estado ---------------------------------------------------------

    @property
    def expanded(self):
        return self.revealer.get_reveal_child()

    def set_expanded(self, value):
        if value and not self.expanded:
            self.rebuild_subtasks()
        self.revealer.set_reveal_child(value)

    def update(self):
        controller, ctx = self.controller, self.host.context
        timer = controller.timer
        fields = controller.settings["compact_fields"]
        cycles = controller.settings["cycles_before_long_break"]
        self.dot.set_color(PHASE_DOT[timer.phase])
        self.eyebrow.set_text(compact_eyebrow(timer.phase, timer.running, timer.started, timer.cycle, cycles,
                                              overtime=timer.in_overtime))
        self.time.set_text(format_clock(timer.remaining))
        self.time.set_visible("remaining" in fields)
        title = ctx.get("subtask_title") or ctx.get("task_title") or "Foco livre"
        self.title.set_text(title)
        self.title.set_visible("current_task" in fields)
        parent = ctx.get("task_title") if ctx.get("subtask_title") else ""
        self.parent.set_text(parent or "")
        self.parent.set_visible(bool(parent) and "current_task" in fields)
        total = max(timer.phase_total, 1)
        set_bar_fraction(self.bar, 1.0 if timer.in_overtime else (total - timer.remaining) / total)
        self.bar.set_visible("progress" in fields)

        task_id, estimate = ctx.get("task_id"), ctx.get("estimate_min")
        show_estimate = "estimate_vs_real" in fields and task_id is not None and bool(estimate)
        if show_estimate:
            real = controller.tracker.live_real_seconds(task_id)
            self.estimate.set_text(f"Real {format_real(real)} de {format_minutes(estimate)} previstos")
        self.estimate.set_visible(show_estimate)
        nxt = timer.next_intervals(count=1)[0]
        self.next.set_text(next_interval_hint(nxt))
        self.next.set_visible("next_break" in fields)
        self.play.set_label("❚❚" if timer.running else "▶")
        self.done.set_sensitive(task_id is not None)

    def rebuild_subtasks(self):
        for child in self.subtasks_box.get_children():
            self.subtasks_box.remove(child)
            child.destroy()
        task_id = self.host.context.get("task_id")
        detail = self.controller.task_detail(task_id) if task_id else None
        subs = detail["subtasks"] if detail else []
        active = self.controller.tracker.active_subtask_id
        for sub in subs:
            if sub["done"]:
                text, classes = f"☑  {sub['title']}", ("small", "text-dark-muted", "strike")
            elif sub["id"] == active:
                text, classes = f"▸  {sub['title']}  · agora", ("small", "text-on-dark", "bold")
            else:
                text, classes = f"☐  {sub['title']}", ("small", "text-on-dark")
            box = Gtk.EventBox()
            box.set_visible_window(False)
            box.add(label(text, *classes, ellipsize=True))
            box.connect("button-press-event", lambda _w, _e, sid=sub["id"]: self.controller.focus(task_id, sid))
            box.show_all()
            self.subtasks_box.pack_start(box, False, True, 0)
        self.subtasks_box.set_visible(bool(subs))

    # ---- captura de distrações ---------------------------------------------

    def submit_capture(self):
        text = self.capture.get_text().strip()
        if not text:
            return False
        self.controller.add_distraction(text)
        self.capture.set_text("")
        self.feedback.set_text("✓ Anotado — volte ao foco")
        self.feedback.show()
        if self._feedback_source is not None:
            GLib.source_remove(self._feedback_source)
        self._feedback_source = GLib.timeout_add(FEEDBACK_MS, self._clear_feedback)
        return True

    def _clear_feedback(self):
        self._feedback_source = None
        self.feedback.hide()
        return False

    def _on_capture_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.capture.set_text("")
            self.set_expanded(False)
            return True
        return False

    def destroy(self):
        if self._feedback_source is not None:
            GLib.source_remove(self._feedback_source)
            self._feedback_source = None
        super().destroy()


class BreakCard(Gtk.Box):
    """C2: pausa com sugestão do que fazer e o que vem a seguir."""

    def __init__(self, controller, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        style(self, "compact-card", "compact-break")
        self.controller, self.host = controller, host
        self.set_size_request(CARD_WIDTH, -1)
        self.eyebrow = label("", "eyebrow", "text-mint")
        header = hbox(GroupDot(COLORS["mint"], size=8, radius=4), expand(self.eyebrow),
                      _icon("⤢", "Voltar ao app", host.expand_main), _icon("✕", "Esconder (continua na bandeja)", host.close_compact),
                      spacing=8)
        self.time = label("", "compact-time", "text-on-dark")
        hint = label("Levante, alongue e beba água. Longe da tela.", "text-break", wrap=True)
        hint.set_max_width_chars(24)
        main = hbox(self.time, expand(hint), spacing=14)
        self.next = label("", "caption", "text-break-muted", wrap=True)
        self.next.set_max_width_chars(30)
        self.plus = button("+1 min", "btn-break-soft", tooltip="Estender a pausa em 1 minuto",
                           on_click=lambda: controller.extend_phase(60))
        self.skip = button("Pular pausa", "btn-mint", tooltip="Voltar ao foco agora", on_click=controller.skip_phase)
        self.skip.get_style_context().add_class("small")
        footer = hbox(expand(self.next), self.plus, self.skip, spacing=8)
        for widget in (header, main, footer):
            self.pack_start(widget, False, True, 0)
        self.show_all()

    def update(self):
        timer, ctx = self.controller.timer, self.host.context
        cycles = self.controller.settings["cycles_before_long_break"]
        self.eyebrow.set_text(compact_eyebrow(timer.phase, timer.running, timer.started, timer.cycle, cycles))
        self.time.set_text(format_clock(timer.remaining))
        title, estimate = ctx.get("next_title"), ctx.get("next_estimate_min")
        if title:
            self.next.set_text(f"A seguir: {title}" + (f" · {format_minutes(estimate)}" if estimate else ""))
        else:
            self.next.set_text("A seguir: foco livre")


class MiniPill(Gtk.EventBox):
    """C3: só o essencial numa pílula. Clique para voltar ao cartão."""

    def __init__(self, controller, host):
        super().__init__()
        self.set_visible_window(False)
        self.controller, self.host = controller, host
        self.dot = GroupDot(COLORS["focus"], size=10, radius=5)
        self.time = label("", "compact-time-sm", "text-on-dark")
        self.title = label("", "small", "text-dark-muted", ellipsize=True)
        self.title.set_max_width_chars(22)
        self.toggle = button("❚❚", "btn-icon-dark", tooltip="Iniciar / pausar", on_click=controller.toggle_timer)
        self.box = hbox(self.dot, self.time, self.title, self.toggle, spacing=10, classes=("compact-pill", "compact-dark"))
        self.add(self.box)
        self.show_all()

    def update(self):
        timer, ctx = self.controller.timer, self.host.context
        working = timer.phase == Phase.WORK
        self.dot.set_color(PHASE_DOT[timer.phase])
        self.time.set_text(format_clock(timer.remaining))
        if working:
            self.title.set_text(ctx.get("subtask_title") or ctx.get("task_title") or "Foco livre")
        else:
            self.title.set_text("Pausa curta" if timer.phase == Phase.SHORT_BREAK else "Pausa longa")
        self.toggle.set_label("❚❚" if timer.running else "▶")
        context = self.box.get_style_context()
        context.remove_class("compact-dark")
        context.remove_class("compact-break")
        context.add_class("compact-dark" if working else "compact-break")


class AlertCard(Gtk.Box):
    """C5: passou do previsto. Escolha: pausar, dar mais 15 min ou ajustar a previsão."""

    def __init__(self, controller, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        style(self, "compact-card", "compact-alert")
        self.controller, self.host = controller, host
        self.set_size_request(CARD_WIDTH, -1)
        close = button("✕", "btn-ghost", tooltip="Dispensar o aviso", on_click=host.dismiss_alert)
        header = hbox(expand(label("⚠  PASSOU DO PREVISTO", "eyebrow", "text-amber")), close)
        self.text = label("", "small", "text-amber-dark", wrap=True)
        self.text.set_max_width_chars(40)
        pause = button("Fazer pausa", "btn-alert-dark", on_click=host.alert_take_break)
        more = button("+15 min", "btn-alert-light", on_click=lambda: host.alert_extend(15))
        adjust = button("Ajustar previsão", "btn-alert-light", on_click=host.alert_adjust)
        buttons = hbox(pause, more, adjust, spacing=6)
        buttons.set_homogeneous(True)
        for widget in (header, self.text, buttons):
            self.pack_start(widget, False, True, 0)
        self.show_all()

    def show_for(self, alert):
        real, estimate = format_minutes(round(alert["real_seconds"] / 60)), format_minutes(round(alert["estimate_seconds"] / 60))
        self.text.set_text(f"Você está há {real} em “{alert['title']}” (previsto {estimate}). "
                           "Tudo bem continuar — só confira se ainda é a prioridade.")


class RatingCard(Gtk.Box):
    """C6: o pomodoro acabou. "Como foi?" (fácil, ok, difícil) e iniciar a pausa."""

    def __init__(self, controller, host):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        style(self, "compact-card", "compact-dark")
        self.controller, self.host = controller, host
        self.set_size_request(CARD_WIDTH, -1)
        self.header = label("", "eyebrow", "text-mint")
        self.question = label("", "card-title", "text-on-dark", wrap=True)
        self.question.set_max_width_chars(30)
        self.choices = {}
        choices = hbox(spacing=6)
        choices.set_homogeneous(True)
        for value, text in DIFFICULTIES:
            chip = style(Gtk.ToggleButton(label=text), "btn", "btn-on-dark")
            chip.connect("toggled", self._on_choice, value)
            self.choices[value] = chip
            choices.pack_start(chip, True, True, 0)
        self.choices_row = choices
        self.primary = button("", "btn-mint", on_click=host.rating_continue)
        self._updating = False
        for widget in (self.header, self.question, choices, self.primary):
            self.pack_start(widget, False, True, 0)
        self.show_all()
        _hide_by_default(self.choices_row)

    def show_for(self, data):
        timer = self.controller.timer
        minutes = round(data["seconds"] / 60)
        self.header.set_text(f"✓ POMODORO {data['number']} CONCLUÍDO · +{minutes} MIN NO REAL")
        self.question.set_text(f"Como foi “{data['title']}”?" if data["title"] else "Como foi este foco?")
        self.choices_row.set_visible(data["task_id"] is not None)
        self._updating = True
        for value, chip in self.choices.items():        # mantém a escolha já feita ao redesenhar
            chip.set_active(value == data.get("difficulty"))
        self._updating = False
        self.primary.set_label("Continuar" if timer.running else
                               f"Iniciar pausa de {max(timer.phase_total // 60, 1)} min")

    def _on_choice(self, chip, value):
        if self._updating or not chip.get_active():
            return
        self._updating = True
        for other_value, other in self.choices.items():
            other.set_active(other_value == value)
        self._updating = False
        self.host.rate(value)


class CompactWindow(Gtk.Window):
    def __init__(self, controller, on_expand=None, on_close=None, on_adjust=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        load_theme()
        style(self, "compact-window")
        self.controller = controller
        self._on_expand, self._on_close, self._on_adjust = on_expand, on_close, on_adjust
        self.context = {}
        self.alert = None
        self.rating = None
        self.mini = False
        self._hover_source = None
        self._position_source = None
        self._rating_source = None
        self._last_click = 0
        self._last_position = None
        self._pointer_inside = False

        self.set_title("Foco — compacto")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self.focus_card = FocusCard(controller, self)
        self.break_card = BreakCard(controller, self)
        self.mini_pill = MiniPill(controller, self)
        self.alert_card = AlertCard(controller, self)
        self.rating_card = RatingCard(controller, self)
        self.stack = Gtk.Stack()
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        for name, widget in (("focus", self.focus_card), ("break", self.break_card), ("mini", self.mini_pill),
                             ("alert", self.alert_card), ("rating", self.rating_card)):
            self.stack.add_named(widget, name)
        self.stack.show_all()

        self.frame = Gtk.EventBox()
        self.frame.set_visible_window(False)
        self.frame.add(self.stack)
        self.frame.set_margin_start(14)
        self.frame.set_margin_end(14)
        self.frame.set_margin_top(10)
        self.frame.set_margin_bottom(18)
        self.frame.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                              Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.frame.connect("button-press-event", self._on_press)
        self.frame.connect("enter-notify-event", self._on_enter)
        self.frame.connect("leave-notify-event", self._on_leave)
        self.add(self.frame)
        self.frame.show()
        self.connect("configure-event", self._on_configure)
        self.connect("key-press-event", self._on_key)
        controller.subscribe(self._on_event)
        self.refresh()

    # ---- ações dos botões (chamadas pelos cartões) ------------------------

    def expand_main(self):
        if self._on_expand:
            self._on_expand()

    def close_compact(self):
        if self._on_close:
            self._on_close()
        else:
            self.hide()

    def toggle_mini(self):
        self.mini = not self.mini
        self.focus_card.set_expanded(False)
        self.refresh()

    def dismiss_alert(self):
        self.alert = None
        self.refresh()

    def alert_take_break(self):
        self.alert = None
        self.controller.skip_phase()
        self.refresh()

    def alert_extend(self, minutes):
        alert, self.alert = self.alert, None
        if alert:
            self.controller.bump_estimate(alert["task_id"], minutes)
        self.refresh()

    def alert_adjust(self):
        alert, self.alert = self.alert, None
        self.refresh()
        if alert and self._on_adjust:
            self._on_adjust(alert["task_id"])

    def rate(self, difficulty):
        if self.rating and self.rating["task_id"]:
            self.rating["difficulty"] = difficulty
            self.controller.set_task_difficulty(self.rating["task_id"], difficulty)

    def rating_continue(self):
        if not self.controller.timer.running:
            self.controller.toggle_timer()
        self.dismiss_rating()

    def dismiss_rating(self):
        self.rating = None
        if self._rating_source is not None:
            GLib.source_remove(self._rating_source)
            self._rating_source = None
        self.refresh()

    # ---- qual cartão mostrar ------------------------------------------------

    def view_name(self):
        if self.alert:
            return "alert"
        if self.rating:
            return "rating"
        if self.mini:
            return "mini"
        return "focus" if self.controller.timer.phase == Phase.WORK else "break"

    def refresh(self):
        """Refaz o contexto (tarefa em foco, o que vem a seguir) e o cartão visível."""
        self.context = self.controller.focus_context(self.controller.today_view())
        view = self.view_name()
        if view == "alert":
            self.alert_card.show_for(self.alert)
        elif view == "rating":
            self.rating_card.show_for(self.rating)
        self.stack.set_visible_child_name(view)
        self.update()
        if self.focus_card.expanded:
            self.focus_card.rebuild_subtasks()
        self.resize(1, 1)                       # encolhe até o tamanho do cartão
        self._apply_window_state()

    def update(self):
        """A cada segundo: só os textos do cartão visível."""
        view = self.stack.get_visible_child_name()
        card = {"focus": self.focus_card, "break": self.break_card, "mini": self.mini_pill}.get(view)
        if card is not None:
            card.update()

    def _apply_window_state(self):
        settings = self.controller.settings
        self.set_keep_above(bool(settings["compact_always_on_top"]))
        urgent = self.view_name() in ("alert", "rating")
        self.frame.set_opacity(1.0 if urgent or self._pointer_inside else settings["compact_idle_opacity"])

    # ---- eventos do controlador ---------------------------------------------

    def _on_event(self, kind):
        visible = self.get_visible()
        if kind == "tick":
            if visible:
                self.update()
        elif kind == "alert":
            if visible and self.controller.last_alert:
                self.alert = dict(self.controller.last_alert)
                self.refresh()
        elif kind == "pomodoro-done":
            if visible and self.controller.settings["ask_difficulty"] and self.controller.last_pomodoro:
                self.rating = dict(self.controller.last_pomodoro)
                if self._rating_source is not None:
                    GLib.source_remove(self._rating_source)
                self._rating_source = GLib.timeout_add_seconds(RATING_TIMEOUT_S, self._rating_timeout)
        elif kind in ("phase", "data", "settings", "started"):
            if kind == "phase" and self.alert and self.controller.timer.phase != Phase.WORK:
                self.alert = None                    # já fez a pausa: o aviso perdeu o sentido
            if visible:
                self.refresh()

    def _rating_timeout(self):
        self._rating_source = None
        self.rating = None
        self.refresh()
        return False

    # ---- janela: mover, passar o mouse, menu --------------------------------

    def _on_press(self, _widget, event):
        if event.button == 3:
            self._popup_menu(event)
            return True
        if event.button != 1:
            return False
        if 0 < event.time - self._last_click <= DOUBLE_CLICK_MS:
            self._last_click = 0
            self.toggle_mini()
            return True
        self._last_click = event.time
        self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def _popup_menu(self, event):
        menu = Gtk.Menu()
        items = [
            ("Expandir" if self.mini else "Mini (pílula)", self.toggle_mini),
            ("Voltar ao app", self.expand_main),
        ]
        for text, callback in items:
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _i, cb=callback: cb())
            menu.append(item)
        top = Gtk.CheckMenuItem(label="Sempre por cima")
        top.set_active(bool(self.controller.settings["compact_always_on_top"]))
        top.connect("toggled", lambda i: self.controller.apply_settings({"compact_always_on_top": i.get_active()}))
        menu.append(top)
        menu.append(Gtk.SeparatorMenuItem())
        hide = Gtk.MenuItem(label="Esconder (continua na bandeja)")
        hide.connect("activate", lambda *_: self.close_compact())
        menu.append(hide)
        menu.show_all()
        menu.popup_at_pointer(event)
        return menu

    def _on_enter(self, _widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self._pointer_inside = True
        self.frame.set_opacity(1.0)
        self._schedule_hover(True)
        return False

    def _on_leave(self, _widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self._pointer_inside = False
        self._apply_window_state()
        self._schedule_hover(False)
        return False

    def _schedule_hover(self, opening):
        if self._hover_source is not None:
            GLib.source_remove(self._hover_source)
        self._hover_source = GLib.timeout_add(HOVER_OPEN_MS if opening else HOVER_CLOSE_MS, self._apply_hover, opening)

    def _apply_hover(self, opening):
        self._hover_source = None
        if self.view_name() != "focus":
            return False
        if opening:
            self.focus_card.set_expanded(True)
        elif not self.focus_card.capture.has_focus():        # não fecha enquanto o usuário digita
            self.focus_card.set_expanded(False)
        self.resize(1, 1)
        return False

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape and self.focus_card.expanded:
            self.focus_card.set_expanded(False)
            return True
        focus = self.get_focus()
        if event.keyval == Gdk.KEY_space and not isinstance(focus, (Gtk.Entry, Gtk.Button)):
            self.controller.toggle_timer()          # Espaço pausa/retoma, como na janela principal
            return True
        return False

    # ---- posição --------------------------------------------------------------

    def monitors(self):
        display = Gdk.Display.get_default()
        rects = []
        for index in range(display.get_n_monitors()):
            geo = display.get_monitor(index).get_geometry()
            rects.append((geo.x, geo.y, geo.width, geo.height))
        return rects

    def place(self):
        saved = self.controller.settings["compact_position"]
        size = self.get_size()
        x, y = compact_geometry.valid_position(saved, self.monitors(), size)
        self._last_position = (x, y)
        self.move(x, y)

    def _on_configure(self, _widget, _event):
        if self.get_visible() and self.get_position() != self._last_position:
            if self._position_source is not None:
                GLib.source_remove(self._position_source)
            self._position_source = GLib.timeout_add(SAVE_POSITION_MS, self._save_position)
        return False

    def _save_position(self):
        self._position_source = None
        position = tuple(self.get_position())
        if position != self._last_position:
            self._last_position = position
            self.controller.apply_settings({"compact_position": list(position)})
        return False

    def present_compact(self):
        """Mostra a janela compacta (na posição salva) por cima de tudo."""
        self.stack.show_all()
        self.refresh()
        self.show()
        self.place()
        self.present()

    def destroy(self):
        for source in (self._hover_source, self._position_source, self._rating_source):
            if source is not None:
                GLib.source_remove(source)
        self._hover_source = self._position_source = self._rating_source = None
        super().destroy()
