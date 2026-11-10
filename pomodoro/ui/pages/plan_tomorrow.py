"""Tela "Revisar e planejar amanhã" (D7): resumo do dia, destino das pendências e a lista de amanhã.

Fluxo em uma tela só, como no design: à esquerda o que aconteceu hoje e o que ficou para depois (cada
pendência vai para amanhã, outra data ou é descartada); à direita o plano de amanhã com a capacidade
do dia. "Confirmar plano" aplica os destinos. Nada é gravado antes disso, exceto o humor, o tempo
livre, a ordem da lista e as tarefas novas que você anota para amanhã.
"""

from datetime import date, datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from ... import planning
from ..format import WEEKDAYS, WEEKDAYS_SHORT, format_minutes, format_real, parse_duration
from ..layout import FixedWidthBox, button, expand, hbox, label, vbox
from ..ordering import reorder_ids
from ..theme import hex_to_rgb, style
from ..widgets import CapacityBar, ChoiceGroup, QuickEntry

MOODS = [("hard", "Difícil"), ("ok", "Ok"), ("good", "Bom")]
PLAN_WIDTH = 460
NOTICE_MS = 5000
DRAG_TARGET = Gtk.TargetEntry.new("pomodoro/plan-task", Gtk.TargetFlags.SAME_APP, 0)


def weekday_name(day):
    return WEEKDAYS[day.weekday()]


def short_date(day):
    """'Sáb, 14' — o rótulo do botão "Outra data" depois de escolhida."""
    return f"{WEEKDAYS_SHORT[day.weekday()].capitalize()}, {day.day}"


def leftover_subtitle(item):
    """'Trabalho › Escrever relatório · prev 35m · adiada 1×'."""
    parts = [item.group_name + (f" › {item.subtask_title}" if item.subtask_title else "")]
    if item.estimate_min:
        parts.append(f"prev {format_minutes(item.estimate_min)}")
    if item.postponed_count:
        parts.append(f"adiada {item.postponed_count}×")
    return " · ".join(parts)


def capacity_caption(capacity):
    """'Você previu 4h 05m · ✦ IA estima 4h 45m realista · sobra 1h 15m para pausas'."""
    if capacity.level == "empty":
        return "Nada planejado para amanhã ainda."
    parts = [f"Você previu {format_minutes(capacity.planned_min)}"]
    if capacity.ai_min != capacity.planned_min:
        parts.append(f"✦ IA estima {format_minutes(capacity.ai_min)} realista")
    parts.append(f"passa {format_minutes(capacity.over_min)} do tempo livre" if capacity.level == "over"
                 else f"sobra {format_minutes(capacity.spare_min)} para pausas")
    return " · ".join(parts)


class _ColorBar(Gtk.DrawingArea):
    """Faixa vertical fina com a cor do grupo."""

    def __init__(self, color, width=4, height=18):
        super().__init__()
        self._rgb = hex_to_rgb(color)
        self._width, self._height = width, height
        self.set_size_request(width, height)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._on_draw)

    def _on_draw(self, _widget, cr):
        r = self._width / 2
        cr.new_sub_path()
        cr.arc(r, r, r, 3.1416, 0)
        cr.arc(r, self._height - r, r, 0, 3.1416)
        cr.close_path()
        cr.set_source_rgb(*self._rgb)
        cr.fill()
        return False


class _LeftoverRow(Gtk.Box):
    """Uma pendência com os três destinos. Chama page.on_destination(task_id, valor)."""

    def __init__(self, page, item, destination, tomorrow):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        style(self, "leftover-row")
        self.page, self.item, self.tomorrow = page, item, tomorrow
        self._ignore_calendar = False
        self.pack_start(vbox(label(item.title, "bold", ellipsize=True),
                             label(leftover_subtitle(item), "small", "muted", ellipsize=True), spacing=2),
                        True, True, 0)

        self.tomorrow_button = button("→ Amanhã", "btn-sm", tooltip="Levar para amanhã",
                                      on_click=lambda: page.on_destination(item.task_id, tomorrow.isoformat()))
        self.other_button = style(Gtk.MenuButton(), "btn", "btn-sm")
        self.other_button.set_tooltip_text("Escolher outro dia")
        self.other_button.set_use_popover(True)
        self.other_text = Gtk.Label(label="Outra data")
        self.other_button.add(self.other_text)
        self.calendar = Gtk.Calendar()
        self.calendar.select_month(tomorrow.month - 1, tomorrow.year)       # abre em amanhã, sem contar como escolha
        self.calendar.select_day(tomorrow.day)
        self.calendar.connect("day-selected", self._on_day_selected)
        self.calendar.connect("month-changed", self._on_month_changed)
        popover = Gtk.Popover()
        box = vbox(self.calendar)
        box.set_border_width(10)
        box.show_all()
        popover.add(box)
        self.other_button.set_popover(popover)
        self.discard_button = button("Descartar", "btn-sm", tooltip="Não vou fazer isto",
                                     on_click=lambda: page.on_destination(item.task_id, planning.DISCARD))
        actions = hbox(self.tomorrow_button, self.other_button, self.discard_button, spacing=8)
        self.pack_end(actions, False, False, 0)
        self.set_destination(destination)

    def set_destination(self, destination):
        """Destaca o botão do destino escolhido (None: nenhum)."""
        is_tomorrow = destination == self.tomorrow.isoformat()
        is_other = destination not in (None, planning.DISCARD) and not is_tomorrow
        for widget, active in ((self.tomorrow_button, is_tomorrow), (self.other_button, is_other),
                               (self.discard_button, destination == planning.DISCARD)):
            context = widget.get_style_context()
            context.remove_class("btn-primary" if not active else "btn-secondary")
            context.add_class("btn-primary" if active else "btn-secondary")
        self.other_text.set_text(short_date(date.fromisoformat(destination)) if is_other else "Outra data")

    def _on_month_changed(self, _calendar):
        # Navegar entre meses também dispara "day-selected": não conta como escolha.
        self._ignore_calendar = True
        GLib.idle_add(self._stop_ignoring)

    def _stop_ignoring(self):
        self._ignore_calendar = False
        return False

    def _on_day_selected(self, calendar):
        if self._ignore_calendar:
            return
        year, month, day = calendar.get_date()
        self.other_button.get_popover().popdown()
        self.page.on_destination(self.item.task_id, date(year, month + 1, day).isoformat())


class _PlanRow(Gtk.EventBox):
    """Uma tarefa de amanhã: alça de arrastar, cor do grupo, título, previsto e estimativa da IA."""

    def __init__(self, page, item):
        super().__init__()
        self.set_visible_window(False)
        self.page, self.item = page, item
        self.handle = Gtk.EventBox()
        self.handle.set_visible_window(False)
        self.handle.add(label("⋮⋮", "faint"))
        self.handle.set_tooltip_text("Arraste para reordenar (dentro do mesmo grupo)")
        title = ("↻ " if item.recurring else "") + item.title
        pieces = [self.handle, _ColorBar(item.group_color), expand(label(title, ellipsize=True))]
        if item.estimate_min:
            pieces.append(label(format_minutes(item.estimate_min), "small", "muted"))
            if item.ai_min and item.ai_min != item.estimate_min:
                pieces.append(label(f"✦ {format_minutes(item.ai_min)}", "small", "text-amber"))
        pieces[2].set_tooltip_text("Tarefa que se repete" if item.recurring else item.title)
        self.add(hbox(*pieces, spacing=10, classes=("plan-row",)))

        self.handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [DRAG_TARGET], Gdk.DragAction.MOVE)
        self.handle.connect("drag-data-get", lambda _w, _c, data, _i, _t: data.set(data.get_target(), 8,
                                                                                    item.task_id.encode()))
        self.drag_dest_set(Gtk.DestDefaults.ALL, [DRAG_TARGET], Gdk.DragAction.MOVE)
        self.connect("drag-data-received", self._on_drag_received)
        self.connect("drag-motion", self._on_drag_motion)
        self.connect("drag-leave", lambda *_: self._clear_marker())

    def _clear_marker(self):
        context = self.get_style_context()
        context.remove_class("drop-before")
        context.remove_class("drop-after")

    def _on_drag_motion(self, widget, _context, _x, y, _time):
        self._clear_marker()
        self.get_style_context().add_class("drop-after" if y > widget.get_allocated_height() / 2 else "drop-before")
        return True

    def _on_drag_received(self, widget, _context, _x, y, data, _info, _time):
        self._clear_marker()
        self.page.on_row_dropped(data.get_data().decode(), self.item.task_id,
                                 y > widget.get_allocated_height() / 2)


class PlanTomorrowPage(Gtk.ScrolledWindow):
    """Emite "done" (voltar ao Hoje depois de confirmar) e "open-task"(id) (quebrar uma tarefa em passos)."""

    __gsignals__ = {
        "done": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "open-task": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.destinations = {}          # {task_id: "AAAA-MM-DD" | planning.DISCARD | None}
        self._review = None
        self._plan = None
        self._rows = {}
        self._leftover_rows = {}
        self._suggestion = None
        self._notice_source = None
        self._updating = False
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        for setter in (body.set_margin_top, body.set_margin_bottom):
            setter(28)
        for setter in (body.set_margin_start, body.set_margin_end):
            setter(32)
        self.add(body)
        body.pack_start(self._build_header(), False, False, 0)
        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        columns.pack_start(self._build_review_card(), True, True, 0)
        columns.pack_start(self._build_plan_card(), False, False, 0)
        body.pack_start(columns, True, True, 0)
        self.refresh()

    # ---- montagem -------------------------------------------------------

    def _build_header(self):
        self.eyebrow = label("", "eyebrow")
        titles = vbox(self.eyebrow, label("Revisar hoje e reanotar amanhã", "title-xl"), spacing=2)
        self.steps = [label(text, "step") for text in ("1 Revisar", "2 Reanotar", "3 Confirmar")]
        stepper = hbox(self.steps[0], label("—", "faint"), self.steps[1], label("—", "faint"), self.steps[2],
                       spacing=8)
        return hbox(expand(titles), stepper, spacing=16)

    def _build_review_card(self):
        self.review_title = label("", "card-title")
        self.done_value = label("", "stat-value")
        self.time_value = label("", "stat-value")
        self.mood = ChoiceGroup(MOODS, allow_empty=True)
        self.mood.connect("changed", lambda _g, value: self._on_mood(value))
        stats = hbox(
            vbox(label("Concluídas", "small", "text-green-dark"), self.done_value, spacing=2,
                 classes=("card-soft", "card-green")),
            vbox(label("Previsto → real", "small", "muted"), self.time_value, spacing=2, classes=("card-soft",)),
            vbox(label("Como foi o dia?", "small", "muted"), self.mood, spacing=6, classes=("card-soft",)),
            spacing=12, valign=Gtk.Align.FILL)
        stats.set_homogeneous(True)

        self.leftover_head = label("FICOU PARA DEPOIS — escolha o destino de cada uma", "eyebrow")
        self.leftover_box = vbox(spacing=10)
        self.empty_card = vbox(label("✓ Nada ficou para depois. Dia fechado!", "bold", "text-green-dark"),
                               label("Se ainda restar energia, anote algo para amanhã ao lado.", "small", "text2"),
                               spacing=2, classes=("card-green", "card"))
        self.confirmed_text = label("", "small", "text2", wrap=True)
        self.confirmed_card = vbox(label("✓ Plano de amanhã confirmado", "bold", "text-green-dark"),
                                   self.confirmed_text, spacing=4, classes=("card-green", "card"))
        self.today_button = button("Ir para Hoje", "btn-secondary", on_click=lambda: self.emit("done"))
        self.confirmed_card.pack_start(self.today_button, False, False, 6)
        self.today_button.set_halign(Gtk.Align.START)

        self.suggestion_text = label("", "small", "text-amber-dark", wrap=True)
        self.suggestion_button = button("Abrir tarefa", "btn-secondary", "btn-sm",
                                        tooltip="Abrir a tarefa para dividir em subtarefas",
                                        on_click=self._on_open_suggestion)
        self.suggestion_card = hbox(expand(self.suggestion_text), self.suggestion_button, spacing=12,
                                    classes=("card", "card-ai"))
        self.notice_label = label("", "small", "text-danger", wrap=True)

        card = vbox(self.review_title, stats, self.leftover_head, self.leftover_box, self.empty_card,
                    self.confirmed_card, self.suggestion_card, self.notice_label, spacing=14,
                    classes=("card", "card-lg"))
        for widget in (self.leftover_head, self.leftover_box, self.empty_card, self.confirmed_card,
                       self.suggestion_card, self.notice_label):
            widget.show_all()
            widget.set_no_show_all(True)
        return card

    def _build_plan_card(self):
        self.plan_title = label("", "card-title")
        self.free_button = style(Gtk.MenuButton(), "btn", "btn-ghost")
        self.free_label = label("", "small", "text-primary")
        self.free_button.add(self.free_label)
        self.free_button.set_use_popover(True)
        self.free_entry = style(Gtk.Entry(), "input")
        self.free_entry.set_placeholder_text("6h, 4h30…")
        self.free_entry.set_width_chars(10)
        self.free_entry.connect("activate", lambda *_: self._on_free_time())
        popover = Gtk.Popover()
        box = vbox(label("Quanto tempo livre amanhã?", "small", "muted"),
                   hbox(self.free_entry, button("Salvar", "btn-primary", "btn-sm", on_click=self._on_free_time),
                        spacing=6), spacing=8)
        box.set_border_width(12)
        box.show_all()
        popover.add(box)
        self.free_button.set_popover(popover)
        self.free_button.set_tooltip_text("Quanto tempo você tem livre amanhã")
        self.capacity_bar = CapacityBar()
        self.capacity_text = label("", "caption", "muted", wrap=True)
        self.plan_rows = vbox(spacing=8)
        self.plan_empty = label("Nada agendado para amanhã. O que você levar das pendências aparece aqui.",
                                "small", "muted", wrap=True)
        self.plan_empty.set_no_show_all(True)           # só aparece quando a lista de amanhã está vazia
        self.quick = QuickEntry("＋  Anotar mais algo para amanhã…", ghost=True)
        self.quick.connect("submitted", self._on_quick_add)
        quick_card = vbox(self.quick, classes=("card-dashed",))
        self.confirm_button = button("Confirmar plano de amanhã", "btn-primary", on_click=self.on_confirm)
        self.confirm_button.set_tooltip_text("Aplica os destinos escolhidos e fecha o dia")

        top = vbox(hbox(expand(self.plan_title), self.free_button), self.capacity_bar, self.capacity_text,
                   spacing=8)
        content = vbox(top, self.plan_rows, self.plan_empty, quick_card, spacing=14)
        card = FixedWidthBox(PLAN_WIDTH, orientation=Gtk.Orientation.VERTICAL, spacing=14)
        style(card, "plan-card")
        card.pack_start(content, False, True, 0)
        card.pack_end(self.confirm_button, False, False, 0)
        return card

    # ---- dados ----------------------------------------------------------

    def on_data(self, _kind=None):
        self.refresh()

    def refresh(self):
        controller = self.controller
        today, tomorrow = controller.plan_day()
        review = self._review = controller.day_review()
        plan = self._plan = controller.tomorrow_plan()
        self._updating = True
        self.eyebrow.set_text(f"FIM DO DIA · {datetime.now():%H:%M}")
        self.review_title.set_text(f"Hoje, {weekday_name(today)}")
        self.done_value.set_text(f"{review.done_count} de {review.total_count}")
        self.time_value.set_text(f"{format_minutes(review.planned_min)} → {format_real(review.real_seconds)}")
        self.mood.set_value(review.mood)
        self._updating = False
        self._sync_destinations(review.leftovers, tomorrow)
        self._fill_leftovers(review, tomorrow)
        self._fill_plan(plan, tomorrow)
        self._update_state()

    def _sync_destinations(self, leftovers, tomorrow):
        defaults = self.controller.default_destinations(leftovers)
        current = {item.task_id for item in leftovers}
        self.destinations = {task_id: self.destinations.get(task_id, default)
                             for task_id, default in defaults.items() if task_id in current}

    def _clear(self, box):
        for child in box.get_children():
            box.remove(child)
            child.destroy()

    def _fill_leftovers(self, review, tomorrow):
        self._clear(self.leftover_box)
        self._leftover_rows = {}
        for item in review.leftovers:
            row = _LeftoverRow(self, item, self.destinations.get(item.task_id), tomorrow)
            self._leftover_rows[item.task_id] = row
            self.leftover_box.pack_start(row, False, True, 0)
        self.leftover_box.show_all()

    def _fill_plan(self, plan, tomorrow):
        self._clear(self.plan_rows)
        self._rows = {}
        self.plan_title.set_text(f"Amanhã, {weekday_name(tomorrow)} {tomorrow.day}")
        self.free_label.set_text(f"Tempo livre: {format_minutes(plan['free_min'])} ✎")
        capacity = plan["capacity"]
        self.capacity_bar.set_fractions(capacity.planned_fraction, capacity.ai_fraction)
        self.capacity_text.set_text(capacity_caption(capacity))
        ctx = self.capacity_text.get_style_context()
        ctx.remove_class("text-focus")
        if capacity.level == "over":
            ctx.add_class("text-focus")
        for item in plan["items"]:
            row = _PlanRow(self, item)
            self._rows[item.task_id] = row
            self.plan_rows.pack_start(row, False, True, 0)
        self.plan_rows.show_all()
        self.plan_empty.set_visible(not plan["items"])

    def _update_state(self):
        """Mostra o que cabe no momento: pendências, "dia fechado" ou "plano confirmado"; atualiza etapas e aviso."""
        review, plan = self._review, self._plan
        has_left = bool(review.leftovers)
        confirmed = review.confirmed and not has_left
        self.leftover_head.set_visible(has_left)
        self.leftover_box.set_visible(has_left)
        self.empty_card.set_visible(not has_left and not confirmed)
        self.confirmed_card.set_visible(confirmed)
        if confirmed:
            count, planned = len(plan["items"]), format_minutes(plan["capacity"].planned_min)
            self.confirmed_text.set_text(
                f"Amanhã: {count} {'tarefa' if count == 1 else 'tarefas'}, {planned} previstos. Descanse — "
                "o app te mostra tudo pronto quando o dia começar.")
        self.confirm_button.set_label("✓ Plano confirmado" if confirmed else "Confirmar plano de amanhã")
        self.confirm_button.set_sensitive(not confirmed)
        states = ("step-done", "step-done", "step-done") if confirmed else ("step-done", "step-active", "step-todo")
        texts = ("1 Revisar", "2 Reanotar", "3 Confirmar")
        for widget, state, text in zip(self.steps, states, texts):
            context = widget.get_style_context()
            for name in ("step-todo", "step-active", "step-done"):
                context.remove_class(name)
            context.add_class(state)
            widget.set_text(("✓ " if state == "step-done" else "") + text)
        self._update_suggestion()

    def _update_suggestion(self):
        left = [i for i in self._review.leftovers if self.destinations.get(i.task_id) != planning.DISCARD]
        self._suggestion = self.controller.break_suggestion(left)
        self.suggestion_card.set_visible(self._suggestion is not None)
        if self._suggestion:
            self.suggestion_text.set_text("✦ " + self._suggestion[1])

    # ---- ações ----------------------------------------------------------

    def notice(self, message):
        self.notice_label.set_text(message)
        self.notice_label.show()
        if self._notice_source is not None:
            GLib.source_remove(self._notice_source)
        self._notice_source = GLib.timeout_add(NOTICE_MS, self._clear_notice)

    def _clear_notice(self):
        self._notice_source = None
        self.notice_label.hide()
        return False

    def _on_mood(self, mood):
        if not self._updating and mood:
            self.controller.set_day_mood(mood)

    def on_destination(self, task_id, destination):
        today = self.controller.plan_day()[0]
        if destination != planning.DISCARD and date.fromisoformat(destination) <= today:
            self.notice("Escolha uma data depois de hoje.")
            return
        self.destinations[task_id] = destination
        row = self._leftover_rows.get(task_id)
        if row is not None:
            row.set_destination(destination)
        self._update_suggestion()

    def _on_open_suggestion(self):
        if self._suggestion:
            self.emit("open-task", self._suggestion[0])

    def _on_free_time(self):
        text = self.free_entry.get_text().strip()
        minutes = parse_duration(text)
        if minutes is None or not 0 < minutes <= 24 * 60:
            self.notice("Não entendi o tempo livre. Use 6h, 4h30 ou 90.")
            return
        self.free_button.get_popover().popdown()
        self.free_entry.set_text("")
        self.controller.set_tomorrow_free_minutes(minutes)
        self.refresh()

    def _on_quick_add(self, _entry, title, minutes):
        try:
            self.controller.add_to_tomorrow(title, minutes)
        except (ValueError, KeyError) as error:
            self.notice(str(error))
            return
        self.quick.clear()
        self.refresh()

    def on_row_dropped(self, dragged_id, target_id, after):
        ids = [item.task_id for item in self._plan["items"]]
        order = reorder_ids(ids, dragged_id, target_id, after)
        if order == ids:
            return
        groups = {item.task_id: item.group_id for item in self._plan["items"]}
        if groups.get(dragged_id) != groups.get(target_id):
            self.notice("A ordem só muda dentro do mesmo grupo, como na tela Hoje.")
            return
        self.controller.reorder_plan(order)
        self.refresh()

    def on_confirm(self):
        missing = [i for i in self._review.leftovers if self.destinations.get(i.task_id) is None]
        if missing:
            more = f" e mais {len(missing) - 1}" if len(missing) > 1 else ""
            self.notice(f"Escolha o destino de “{missing[0].title}”{more} antes de confirmar.")
            return False
        try:
            self.controller.confirm_plan(dict(self.destinations))
        except (ValueError, KeyError) as error:
            self.notice(str(error))
            return False
        self.destinations = {}
        self.refresh()
        return True

    def destroy(self):
        if self._notice_source is not None:
            GLib.source_remove(self._notice_source)
            self._notice_source = None
        super().destroy()
