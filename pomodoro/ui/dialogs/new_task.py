"""Modal "Nova tarefa" (D3): nome, grupo, quando, repetir, tempo previsto, sugestão da IA e subtarefas."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from ... import recurrence
from ..format import format_minutes, parse_duration, pomodoros_estimate
from ..layout import button, expand, hbox, label, make_check, vbox
from ..theme import style, themed_window
from ..widgets import ChoiceGroup, DatePicker, Select

TIME_CHIPS = [(15, "15m"), (25, "25m"), (45, "45m"), (60, "1h"), (90, "1h 30m"), (120, "2h")]
SUGGESTION_DELAY_MS = 350


class _DraftRow(Gtk.Box):
    """Uma subtarefa ainda não criada: título, tempo e ✕."""

    def __init__(self, dialog, title="", minutes=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._dialog = dialog
        self.title_entry = style(Gtk.Entry(), "input")
        self.title_entry.set_placeholder_text("Subtarefa")
        self.title_entry.set_text(title)
        self.title_entry.set_hexpand(True)
        self.time_entry = style(Gtk.Entry(), "input")
        self.time_entry.set_placeholder_text("tempo")
        self.time_entry.set_width_chars(8)
        if minutes:
            self.time_entry.set_text(format_minutes(minutes))
        remove = button("✕", "btn-ghost", tooltip="Remover esta subtarefa")
        remove.connect("clicked", lambda *_: dialog.remove_subtask_row(self))
        for widget in (self.title_entry, self.time_entry):
            widget.connect("changed", lambda *_: dialog.on_subtasks_changed())
        self.title_entry.connect("activate", lambda *_: dialog.add_subtask_row(after=self))
        self.pack_start(self.title_entry, True, True, 0)
        self.pack_start(self.time_entry, False, True, 0)
        self.pack_start(remove, False, True, 0)

    def value(self):
        """(título, minutos, válido): linhas sem título são ignoradas pelo diálogo."""
        text = self.time_entry.get_text().strip()
        minutes = parse_duration(text) if text else None
        return self.title_entry.get_text().strip(), minutes, not text or minutes is not None


class NewTaskDialog(Gtk.Dialog):
    def __init__(self, parent, controller, group_id=None, day=...):
        super().__init__(title="Nova tarefa", transient_for=parent, modal=True)
        themed_window(self)
        self.controller = controller
        self.created = None
        self._dismissed = set()
        self._suggestion_source = None
        self._suggestion = None
        self._rows = []
        self._updating = False
        today = controller.today()
        self.set_default_size(680, -1)

        self.title_entry = style(Gtk.Entry(), "input", "input-large")
        self.title_entry.set_placeholder_text("Ex.: Preparar apresentação para o cliente")
        self.title_entry.connect("changed", lambda *_: self._on_inputs_changed())

        groups = [(g["id"], g["name"]) for g in controller.repo.list_groups()]
        group_id = group_id if group_id in dict(groups) else controller.repo.default_group_id()
        self.group_select = Select(groups, group_id, width=190)
        self.group_select.connect("changed", lambda *_: self._on_inputs_changed())
        self.date_picker = DatePicker(today if day is ... else day, today=controller.today, width=190)
        self.date_picker.connect("changed", lambda _p, _d: self._on_date_changed())
        self.repeat_select = Select(recurrence.options_for(self.date_picker.date or today), None, width=190)

        self.chips = ChoiceGroup(TIME_CHIPS, None, "chips", allow_empty=True)
        self.chips.connect("changed", lambda _c, _v: self._on_chip_changed())
        self.time_entry = style(Gtk.Entry(), "input")
        self.time_entry.set_placeholder_text("__ h __ m")
        self.time_entry.set_width_chars(9)
        self.time_entry.set_tooltip_text("Outro tempo: 50, 1h20, 1:20…")
        self.time_entry.connect("changed", lambda *_: self._on_time_text_changed())
        self.pomodoro_label = label("", "small", "muted")
        self.require_label = label("Este grupo exige a previsão de tempo.", "small", "text-danger")

        self.ai_card = self._build_ai_card()
        self.sub_box = vbox(spacing=6)
        self.sum_label = label("", "small", "muted")
        self.error_label = label("", "small", "text-danger", wrap=True)
        self.focus_check = make_check(False)

        body = self.body = vbox(spacing=18)
        body.set_border_width(28)
        body.pack_start(self._build_header(), False, True, 0)
        body.pack_start(self._build_name_block(), False, True, 0)
        body.pack_start(self._build_fields_row(), False, True, 0)
        body.pack_start(self._build_time_block(), False, True, 0)
        body.pack_start(self.ai_card, False, True, 0)
        body.pack_start(self._build_subtasks_block(), False, True, 0)
        body.pack_start(self.error_label, False, True, 0)
        body.pack_start(self._build_footer(), False, True, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(640)
        scrolled.add(body)
        self.get_content_area().pack_start(scrolled, True, True, 0)
        self.connect("key-press-event", self._on_key)
        self.get_content_area().show_all()          # o diálogo em si só aparece no run()
        # Widgets que só aparecem em certas situações: um show_all() futuro não pode revelá-los.
        for widget in (self.ai_card, self.error_label, self.require_label, self.ai_subs_link):
            widget.set_no_show_all(True)
            widget.hide()
        self._on_inputs_changed()

    # ---- montagem -------------------------------------------------------

    def _build_header(self):
        close = button("Esc para fechar  ✕", "btn-ghost", on_click=lambda: self.response(Gtk.ResponseType.CANCEL))
        close.get_style_context().add_class("muted")
        return hbox(expand(label("Nova tarefa", "title-lg")), close)

    def _build_name_block(self):
        box = vbox(label("O que precisa ser feito?", "caption", "text-primary"), self.title_entry, spacing=4)
        return box

    def _build_fields_row(self):
        def field(text, widget):
            return vbox(label(text, "caption", "muted"), widget, spacing=6)

        return hbox(field("Grupo", self.group_select), field("Quando", self.date_picker),
                    field("Repetir", self.repeat_select), spacing=12, valign=Gtk.Align.START)

    def _build_time_block(self):
        row = hbox(self.chips, self.time_entry, self.pomodoro_label, spacing=8)
        return vbox(label("⏱  Quanto tempo você acha que vai levar?", "bold"), row, self.require_label, spacing=10)

    def _build_ai_card(self):
        self.ai_title = label("", "bold", "text-amber-dark")
        self.ai_note = label("", "small", "text-amber-dark", wrap=True)
        self.ai_use = button("", "btn-dark", on_click=self._use_suggestion)
        self.ai_keep = button("", "btn-amber-outline", on_click=self._dismiss_suggestion)
        text = vbox(self.ai_title, self.ai_note, spacing=4)
        return hbox(expand(text), self.ai_use, self.ai_keep, spacing=10, classes=("card", "card-ai"))

    def _build_subtasks_block(self):
        self.ai_subs_link = button("✦ Sugeridas pela IA · refazer", "btn-ghost", on_click=self._fill_ai_subtasks)
        add = button("＋ Adicionar subtarefa", "btn-link", on_click=self.add_subtask_row)
        header = hbox(expand(label("Subtarefas (opcional)", "bold")), self.ai_subs_link)
        footer = hbox(add, expand(label("")), self.sum_label)
        return vbox(header, self.sub_box, footer, spacing=8, classes=("card-soft",))

    def _build_footer(self):
        check = hbox(self.focus_check, label("Começar a focar logo após criar"), spacing=10)
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(check)
        box.connect("button-press-event", lambda *_: self.focus_check.set_active(not self.focus_check.get_active()))
        cancel = button("Cancelar", "btn-secondary", on_click=lambda: self.response(Gtk.ResponseType.CANCEL))
        self.create_button = button("Criar tarefa   Ctrl+Enter", "btn-primary", on_click=self.submit)
        return hbox(expand(box), cancel, self.create_button, spacing=10)

    # ---- estado ---------------------------------------------------------

    @property
    def group_id(self):
        return self.group_select.value

    @property
    def estimate_min(self):
        """Tempo previsto escolhido (chip ou digitado). None = sem previsão ou texto inválido."""
        text = self.time_entry.get_text().strip()
        if text:
            return parse_duration(text) or None
        return self.chips.value

    @property
    def estimate_text_valid(self):
        text = self.time_entry.get_text().strip()
        return not text or parse_duration(text) is not None

    def set_estimate(self, minutes):
        self._updating = True
        self.time_entry.set_text("")
        match = dict(TIME_CHIPS).get(minutes)
        if match:
            self.chips.set_value(minutes)
        else:
            self.chips.set_value(None)
            if minutes:
                self.time_entry.set_text(format_minutes(minutes))
        self._updating = False
        self._on_inputs_changed()

    def _on_chip_changed(self):
        if self._updating:
            return
        self._updating = True
        self.time_entry.set_text("")
        self._updating = False
        self._on_inputs_changed()

    def _on_time_text_changed(self):
        if self._updating:
            return
        style_context = self.time_entry.get_style_context()
        (style_context.remove_class if self.estimate_text_valid else style_context.add_class)("entry-error")
        if self.time_entry.get_text().strip():
            self._updating = True
            self.chips.set_value(None)
            self._updating = False
        self._on_inputs_changed()

    def _on_date_changed(self):
        old_rule = self.repeat_select.value
        day = self.date_picker.date or self.controller.today()
        options = recurrence.options_for(day)
        kind = (old_rule or "").partition(":")[0]
        new_rule = next((rule for rule, _t in options if rule and rule.partition(":")[0] == kind), None) \
            if kind in ("weekly", "monthly") else old_rule
        self.repeat_select.set_items(options, new_rule)

    def _on_inputs_changed(self):
        estimate = self.estimate_min
        pomodoros = pomodoros_estimate(estimate, self.controller.settings["work_min"])
        self.pomodoro_label.set_text(
            f"≈ {pomodoros} pomodoro{'s' if pomodoros != 1 else ''} de {self.controller.settings['work_min']} min"
            if pomodoros else "")
        group = self.controller.repo.get_group(self.group_id)
        self.require_label.set_visible(bool(group and group["require_estimate"]) and not estimate)
        self._update_sum()
        self._schedule_suggestion()

    # ---- sugestão da IA ---------------------------------------------------

    def _schedule_suggestion(self):
        if self._suggestion_source is not None:
            GLib.source_remove(self._suggestion_source)
        self._suggestion_source = GLib.timeout_add(SUGGESTION_DELAY_MS, self._refresh_suggestion)

    def _refresh_suggestion(self):
        self._suggestion_source = None
        title = self.title_entry.get_text().strip()
        estimate = self.estimate_min
        suggestion = self.controller.suggest_estimate(title, self.group_id, estimate)
        key = (title, self.group_id, estimate, suggestion["minutes"] if suggestion else None)
        if not suggestion or suggestion["minutes"] == estimate or key in self._dismissed:
            self._suggestion = None
            self.ai_card.hide()
            self._refresh_subtask_link()
            return False
        self._suggestion = (suggestion, key)
        self.ai_title.set_text(f"✦ A IA sugere {format_minutes(suggestion['minutes'])}")
        self.ai_note.set_text(suggestion.get("note", ""))
        self.ai_use.set_label(f"Usar {format_minutes(suggestion['minutes'])}")
        self.ai_keep.set_label(f"Manter {format_minutes(estimate)}" if estimate else "Dispensar")
        self.ai_card.show()
        self._refresh_subtask_link()
        return False

    def _refresh_subtask_link(self):
        has_ai = self.controller.ai_enabled
        self.ai_subs_link.set_visible(has_ai and bool(self.title_entry.get_text().strip()))

    def _use_suggestion(self):
        if self._suggestion:
            self.set_estimate(self._suggestion[0]["minutes"])

    def _dismiss_suggestion(self):
        if self._suggestion:
            self._dismissed.add(self._suggestion[1])
        self.ai_card.hide()

    def _fill_ai_subtasks(self):
        title = self.title_entry.get_text().strip()
        self.ai_subs_link.set_sensitive(False)

        def finished(suggested, error):
            self.ai_subs_link.set_sensitive(True)
            if not suggested:
                self.error_label.set_text(error or "A IA não encontrou uma divisão para esta tarefa.")
                self.error_label.show()
                return
            for row in list(self._rows):
                self.remove_subtask_row(row)
            for sub_title, minutes in suggested:
                self.add_subtask_row(title=sub_title, minutes=minutes, focus=False)

        self.controller.suggest_subtasks_async(title, self.group_id, finished)

    # ---- subtarefas ---------------------------------------------------------

    def add_subtask_row(self, after=None, title="", minutes=None, focus=True):
        row = _DraftRow(self, title, minutes)
        index = self._rows.index(after) + 1 if after in self._rows else len(self._rows)
        self._rows.insert(index, row)
        self.sub_box.pack_start(row, False, True, 0)
        self.sub_box.reorder_child(row, index)
        row.show_all()
        if focus:
            row.title_entry.grab_focus()
        self._update_sum()
        return row

    def remove_subtask_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
            self.sub_box.remove(row)
            row.destroy()
            self._update_sum()

    def on_subtasks_changed(self):
        self._update_sum()

    def subtask_values(self):
        return [row.value() for row in self._rows if row.title_entry.get_text().strip()]

    def _update_sum(self):
        total = sum(m or 0 for _t, m, _ok in self.subtask_values())
        context = self.sum_label.get_style_context()
        estimate = self.estimate_min
        if not total:
            self.sum_label.set_text("")
            return
        if estimate and total != estimate:
            self.sum_label.set_text(f"Soma {format_minutes(total)} · diferente do previsto ({format_minutes(estimate)})  ⚠")
            context.remove_class("muted")
            context.add_class("text-danger")
        else:
            self.sum_label.set_text(f"Soma {format_minutes(total)}")
            context.remove_class("text-danger")
            context.add_class("muted")

    # ---- envio ----------------------------------------------------------------

    def _fail(self, message, focus=None):
        self.error_label.set_text(message)
        self.error_label.show()
        if focus is not None:
            focus.grab_focus()
        return False

    def submit(self):
        """Valida e cria a tarefa. Devolve True se criou (e fecha o diálogo com OK)."""
        self.error_label.hide()
        title = self.title_entry.get_text().strip()
        if not title:
            return self._fail("Dê um nome para a tarefa.", self.title_entry)
        if not self.estimate_text_valid:
            return self._fail("Não entendi o tempo previsto. Use 45, 1h20 ou 1:20.", self.time_entry)
        subtasks = []
        for index, (sub_title, minutes, valid) in enumerate(self.subtask_values(), start=1):
            if not valid:
                return self._fail(f"Não entendi o tempo da subtarefa {index}. Use 20, 1h ou 1:30.")
            subtasks.append((sub_title, minutes))
        try:
            self.created = self.controller.create_task_full(
                title, group_id=self.group_id, day=self.date_picker.date, estimate_min=self.estimate_min,
                repeat_rule=self.repeat_select.value, subtasks=subtasks, focus=self.focus_check.get_active(),
            )
        except (ValueError, KeyError) as error:
            return self._fail(str(error))
        self.response(Gtk.ResponseType.OK)
        return True

    def _on_key(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.submit()
            return True
        return False

    def destroy(self):
        if self._suggestion_source is not None:
            GLib.source_remove(self._suggestion_source)
            self._suggestion_source = None
        super().destroy()


def run_new_task_dialog(parent, controller, group_id=None, day=...):
    """Abre o modal e devolve a tarefa criada (ou None se o usuário cancelou)."""
    dialog = NewTaskDialog(parent, controller, group_id=group_id, day=day)
    dialog.run()
    created = dialog.created
    dialog.destroy()
    return created
