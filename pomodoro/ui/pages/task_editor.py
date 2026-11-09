"""Tela "Editar tarefa" (D2): campos, previsto × real × IA, subtarefas editáveis, notas e histórico.

Tudo é salvo na hora (sem botão Salvar). O editor guarda as próprias mudanças sem se redesenhar
(para não roubar o foco de quem digita) e só reconstrói tudo quando algo de fora altera a tarefa.
"""

from datetime import date, datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from ... import recurrence
from .. import dialogs
from ..format import (describe_day, estimate_note, format_minutes, format_real, parse_duration,
                      parse_signed_minutes, session_line)
from ..layout import button, expand, flow, hbox, label, make_check, vbox
from ..ordering import reorder_ids
from ..theme import style
from ..widgets import ChoiceGroup, DatePicker, GroupDot, Select, TimeStepper

ENERGY_ITEMS = [("low", "Baixa"), ("medium", "Média"), ("high", "Alta")]
LIST_WIDTH = 260
NOTES_DELAY_MS = 800
NOTICE_MS = 5000
DRAG_TARGET = Gtk.TargetEntry.new("pomodoro/subtask", Gtk.TargetFlags.SAME_APP, 0)
COL_EST, COL_REAL = 84, 70


class _SubtaskRow(Gtk.EventBox):
    """Uma linha da tabela de subtarefas. sub=None é uma linha nova, ainda não gravada."""

    def __init__(self, editor, sub):
        super().__init__()
        self.set_visible_window(False)
        self.editor = editor
        self.sub = sub
        controller = editor.controller
        active = sub is not None and controller.tracker.active_subtask_id == sub["id"]

        self.handle = Gtk.EventBox()
        self.handle.set_visible_window(False)
        self.handle.add(label("⋮⋮", "faint"))
        self.handle.set_tooltip_text("Arraste para reordenar")
        self.check = make_check(bool(sub and sub["done"]), square=True, focus=active,
                                tooltip="Concluir subtarefa",
                                on_toggled=lambda value: editor.on_subtask_done(self, value))
        self.check.set_sensitive(sub is not None)
        self.title_entry = style(Gtk.Entry(), "sub-entry")
        self.title_entry.set_hexpand(True)
        self.title_entry.set_placeholder_text("Nova subtarefa — Enter adiciona, Esc cancela" if sub is None else "")
        self.title_entry.set_text(sub["title"] if sub else "")
        self.time_entry = style(Gtk.Entry(), "sub-entry")
        self.time_entry.set_width_chars(8)
        self.time_entry.set_size_request(COL_EST, -1)
        self.time_entry.set_placeholder_text("tempo")
        self.time_entry.set_text(format_minutes(sub["estimate_min"]) if sub and sub["estimate_min"] else "")
        self.real_label = label("", "small", width=COL_REAL)
        self.update_real()
        self.play = button("▶", "btn-ghost", tooltip="Focar nesta subtarefa")
        self.play.set_sensitive(sub is not None)
        self.play.connect("clicked", lambda *_: editor.on_focus_subtask(self))
        remove = button("✕", "btn-ghost", tooltip="Excluir subtarefa")
        remove.connect("clicked", lambda *_: editor.on_delete_subtask(self))

        row = hbox(self.handle, self.check, self.title_entry, self.time_entry, self.real_label, self.play, remove,
                   spacing=10, classes=("sub-row-active",) if active else ())
        row.set_margin_start(4)
        self.add(row)

        self.title_entry.connect("activate", lambda *_: editor.on_subtask_enter(self))
        self.title_entry.connect("focus-out-event", lambda *_: editor.on_subtask_title_commit(self) or False)
        self.time_entry.connect("activate", lambda *_: editor.on_subtask_time_commit(self))
        self.time_entry.connect("focus-out-event", lambda *_: editor.on_subtask_time_commit(self) or False)
        self.title_entry.connect("key-press-event", self._on_key)

        if sub is not None:
            self.handle.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [DRAG_TARGET], Gdk.DragAction.MOVE)
            self.handle.connect("drag-data-get", self._on_drag_get)
            self.drag_dest_set(Gtk.DestDefaults.ALL, [DRAG_TARGET], Gdk.DragAction.MOVE)
            self.connect("drag-data-received", self._on_drag_received)
            self.connect("drag-motion", self._on_drag_motion)
            self.connect("drag-leave", lambda *_: self._clear_marker())

    def update_real(self, seconds=None):
        if self.sub is None:
            self.real_label.set_text("")
            return
        if seconds is None:
            seconds = self.sub["real_seconds"]
        self.real_label.set_text(format_real(seconds))

    def _on_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape and self.sub is None:
            self.editor.cancel_draft()
            return True
        return False

    def _on_drag_get(self, _widget, _context, data, _info, _time):
        data.set(data.get_target(), 8, self.sub["id"].encode())

    def _clear_marker(self):
        context = self.get_style_context()
        context.remove_class("drop-before")
        context.remove_class("drop-after")

    def _on_drag_motion(self, widget, _context, _x, y, _time):
        self._clear_marker()
        after = y > widget.get_allocated_height() / 2
        self.get_style_context().add_class("drop-after" if after else "drop-before")
        return True

    def _on_drag_received(self, widget, _context, _x, y, data, _info, _time):
        self._clear_marker()
        dragged = data.get_data().decode()
        self.editor.on_subtask_dropped(dragged, self.sub["id"], y > widget.get_allocated_height() / 2)


class TaskEditorPage(Gtk.Box):
    """Emite "back" (voltar ao Hoje), "open-task"(id) (trocou de tarefa na lista) e "focus-started"."""

    __gsignals__ = {
        "back": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "open-task": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "focus-started": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.controller = controller
        self.task_id = None
        self._detail = None
        self._loading = False
        self._own = False
        self._draft = False
        self._focus_request = None
        self._ai_suggestion = None
        self._notes_source = None
        self._notice_source = None
        self.set_margin_top(24)
        self.set_margin_bottom(20)
        self.set_margin_start(24)
        self.set_margin_end(24)

        self.pack_start(self._build_breadcrumb(), False, True, 0)
        row = hbox(valign=Gtk.Align.FILL, spacing=20)
        row.pack_start(self._build_list(), False, True, 0)
        row.pack_start(self._build_editor_scroll(), True, True, 0)
        self.pack_start(row, True, True, 0)

    # ---- montagem -------------------------------------------------------

    def _build_breadcrumb(self):
        back = button("Hoje", "btn-link", on_click=lambda: self.go_back())
        self.group_crumb = label("", "muted")
        return hbox(back, label("›", "faint"), self.group_crumb, label("›", "faint"),
                    label("Editar tarefa", "bold"), spacing=8)

    def _build_list(self):
        self.list_box = vbox(spacing=6)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list_box)
        scroll.set_size_request(LIST_WIDTH, -1)
        column = vbox(label("TAREFAS DE HOJE", "eyebrow"), spacing=8)
        column.pack_start(scroll, True, True, 0)
        return column

    def _build_editor_scroll(self):
        self.editor = vbox(spacing=18, classes=("card", "card-lg"))
        self.editor.pack_start(self._build_title_row(), False, True, 0)
        self.editor.pack_start(self._build_notice(), False, True, 0)
        self.editor.pack_start(self._build_fields_row(), False, True, 0)
        self.editor.pack_start(self._build_time_cards(), False, True, 0)
        self.editor.pack_start(self._build_subtasks(), False, True, 0)
        self.editor.pack_start(self._build_notes_history(), False, True, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.editor)
        return scroll

    def _build_title_row(self):
        self.done_check = make_check(False, tooltip="Concluída", on_toggled=self._on_done_toggled)
        self.title_entry = style(Gtk.Entry(), "title-entry")
        self.title_entry.set_hexpand(True)
        self.title_entry.connect("activate", lambda *_: self._commit_title())
        self.title_entry.connect("focus-out-event", lambda *_: self._commit_title() or False)
        self.postponed_label = label("", "caption", "text-amber")
        delete = button("Excluir", "btn-danger", on_click=self._on_delete)
        duplicate = button("Duplicar p/ amanhã", "btn-secondary", on_click=self._on_duplicate)
        focus = button("▶  Focar nesta tarefa", "btn-focus", on_click=self._on_focus)
        self.title_entry.set_width_chars(10)
        head = hbox(self.done_check, expand(self.title_entry), spacing=10)
        actions = hbox(expand(self.postponed_label), delete, duplicate, focus, spacing=10)
        actions.set_margin_start(30)
        return vbox(head, actions, spacing=8)

    def _build_notice(self):
        self.notice_label = label("", "small", wrap=True)
        self.notice_label.set_no_show_all(True)
        return self.notice_label

    def _build_fields_row(self):
        self.group_select = Select([("", "—")])
        self.group_select.connect("changed", lambda _s, value: self._on_group_changed(value))
        self.date_picker = DatePicker(None, today=self.controller.today)
        self.date_picker.connect("changed", lambda _p, day: self._on_date_changed(day))
        self.repeat_select = Select([(None, recurrence.NO_REPEAT_LABEL)])
        self.repeat_select.connect("changed", lambda _s, value: self._on_repeat_changed(value))
        self.energy = ChoiceGroup(ENERGY_ITEMS, None, "segmented", allow_empty=True)
        self.energy.connect("changed", lambda _c, value: self._on_energy_changed(value))

        def field(text, widget):
            return vbox(label(text, "caption", "muted"), widget, spacing=6)

        return flow(field("Grupo", self.group_select), field("Quando", self.date_picker),
                    field("Repetir", self.repeat_select), field("Energia necessária", self.energy),
                    max_per_line=4)

    def _build_time_cards(self):
        self.stepper = TimeStepper(0, step=5)
        self.stepper.connect("value-changed", lambda _s, minutes: self._on_estimate_changed(minutes))
        self.estimate_note_label = label("", "caption", "muted", wrap=True)
        self.estimate_note_label.set_max_width_chars(26)
        planned = vbox(label("⏱ PREVISTO (sua estimativa)", "eyebrow", "text-primary"), self.stepper,
                       self.estimate_note_label, spacing=8, classes=("card", "card-primary"))

        self.real_value = label("0m", "stat-value")
        self.real_note = label("", "caption", "text-green-dark")
        adjust = button("Ajustar manualmente", "btn-link", on_click=self._on_adjust)
        real = vbox(label("◷ REAL (cronometrado)", "eyebrow", "text-green-dark"), self.real_value,
                    self.real_note, hbox(adjust, spacing=0), spacing=6, classes=("card", "card-green"))

        self.ai_value = label("—", "stat-value", "text-amber-dark")
        self.ai_note = label("", "caption", "text-amber-dark", wrap=True)
        self.ai_note.set_max_width_chars(26)
        self.ai_use = button("Usar esta estimativa", "btn-link", on_click=self._on_use_ai)
        ai = vbox(label("✦ IA ESTIMA", "eyebrow", "text-amber"), self.ai_value, self.ai_note,
                  hbox(self.ai_use, spacing=0), spacing=6, classes=("card", "card-ai"))
        return flow(planned, real, ai, max_per_line=3)

    def _build_subtasks(self):
        self.ai_subs_button = button("✦ Quebrar em passos menores com IA", "btn-ghost", on_click=self._on_ai_subtasks)
        self.ai_subs_button.set_no_show_all(True)
        header = hbox(expand(label("Subtarefas", "section-title")), self.ai_subs_button)
        columns = hbox(expand(label("PASSO", "eyebrow")), label("PREVISTO", "eyebrow", width=COL_EST),
                       label("REAL", "eyebrow", width=COL_REAL), spacing=10)
        columns.set_margin_start(64)
        columns.set_margin_end(96)
        self.sub_rows_box = vbox(spacing=4)
        self.add_sub_button = button("＋ Adicionar subtarefa", "btn-link", on_click=self.start_draft)
        hint = label("Enter cria a próxima · Tab vai para o tempo", "caption", "faint")
        return vbox(header, columns, self.sub_rows_box, hbox(self.add_sub_button, hint, spacing=12), spacing=6)

    def _build_notes_history(self):
        self.notes_view = Gtk.TextView()
        style(self.notes_view, "notes-view")
        self.notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.notes_view.set_left_margin(2)
        self.notes_view.get_buffer().connect("changed", lambda *_: self._on_notes_changed())
        self.notes_view.connect("focus-out-event", lambda *_: self._commit_notes() or False)
        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        notes_scroll.set_min_content_height(120)
        notes_scroll.add(self.notes_view)
        notes = vbox(label("NOTAS", "eyebrow"), notes_scroll, spacing=8, classes=("card-soft",))

        self.history_box = vbox(spacing=6)
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        history_scroll.set_min_content_height(120)
        history_scroll.set_max_content_height(220)
        history_scroll.set_propagate_natural_height(True)
        history_scroll.add(self.history_box)
        history = vbox(label("HISTÓRICO DE SESSÕES", "eyebrow"), history_scroll, spacing=8, classes=("card-soft",))
        return flow(notes, history, max_per_line=2, spacing=14)

    # ---- carregar e preencher -------------------------------------------

    def load(self, task_id):
        """Abre a tarefa no editor (grava o que estava sendo digitado na anterior)."""
        self.flush()
        self.task_id = task_id
        self._draft = False
        self._reload()

    def _reload(self):
        detail = self.controller.task_detail(self.task_id) if self.task_id else None
        if detail is None:
            self.task_id = None
            self.emit("back")
            return
        self._fill(detail)

    def _fill(self, detail):
        """Preenche tudo a partir do banco (descarta o que estiver pendente nos campos)."""
        self._detail = detail
        task, today = detail["task"], self.controller.today()
        self._loading = True
        try:
            self.done_check.set_active(task["status"] == "done")
            self.title_entry.set_text(task["title"])
            groups = [(g["id"], g["name"]) for g in self.controller.repo.list_groups()]
            if task["group_id"] not in dict(groups):
                groups.append((task["group_id"], detail["group"]["name"]))
            self.group_select.set_items(groups, task["group_id"])
            day = date.fromisoformat(task["scheduled_for"]) if task["scheduled_for"] else None
            self.date_picker.set_date(day)
            self._set_repeat_options(day or today, task["repeat_rule"])
            self.energy.set_value(task["energy"])
            self.stepper.set_minutes(task["estimate_min"] or 0)
            self.notes_view.get_buffer().set_text(task["notes"] or "")
        finally:
            self._loading = False
        self._fill_derived(detail)
        self._fill_subtasks(detail)

    def _set_repeat_options(self, day, rule):
        options = recurrence.options_for(day)
        if rule not in dict(options):
            options.append((rule, recurrence.describe(rule)))
        self.repeat_select.set_items(options, rule)

    def _fill_derived(self, detail):
        """Atualiza o que é calculado (cartões, histórico, lista), sem mexer nos campos de digitação."""
        self._detail = detail
        task = detail["task"]
        self.group_crumb.set_text(detail["group"]["name"])
        self.postponed_label.set_text(
            f"adiada {task['postponed_count']} vez{'es' if task['postponed_count'] != 1 else ''}"
            if task["postponed_count"] else "")
        note, ok = estimate_note(task["estimate_min"], detail["estimate_sum"], self.controller.settings["work_min"])
        self.estimate_note_label.set_text(note)
        note_style = self.estimate_note_label.get_style_context()
        note_style.remove_class("text-danger")
        note_style.remove_class("muted")
        note_style.add_class("muted" if ok else "text-danger")
        self._fill_real(detail)
        self._fill_ai(detail)
        self._fill_history(detail)
        self._fill_list()
        self.ai_subs_button.set_visible(self.controller.ai_enabled)

    def _fill_real(self, detail, live_seconds=None):
        seconds = detail["real_seconds"] if live_seconds is None else live_seconds
        self.real_value.set_text(format_minutes(round(seconds / 60)))
        count = detail["pomodoros"]
        self.real_note.set_text(f"{count} pomodoro{'s' if count != 1 else ''} concluído{'s' if count != 1 else ''}")

    def _fill_ai(self, detail):
        task = detail["task"]
        suggestion = self.controller.suggest_estimate(task["title"], task["group_id"], task["estimate_min"],
                                                      task_id=task["id"])
        self._ai_suggestion = suggestion
        if suggestion:
            self.ai_value.set_text(format_minutes(suggestion["minutes"]))
            self.ai_note.set_text(suggestion.get("note", ""))
        else:
            self.ai_value.set_text("—")
            self.ai_note.set_text("Ainda não há histórico parecido para estimar."
                                  if self.controller.settings.get("ai_enabled", True)
                                  else "A IA está desligada em Configurações.")
        self.ai_use.set_visible(bool(suggestion and suggestion["minutes"] != task["estimate_min"]))

    def _fill_history(self, detail):
        for child in self.history_box.get_children():
            self.history_box.remove(child)
            child.destroy()
        entries = []
        for session in detail["sessions"]:
            when, text, kind = session_line(session)
            entries.append((session["started_at"], when, text, kind))
        for item in detail["distractions"]:
            moment = datetime.fromisoformat(item["created_at"])
            entries.append((item["created_at"], f"{moment:%H:%M}", f"✎ {item['text']}", "distraction"))
        if not entries:
            self.history_box.pack_start(label("Nenhuma sessão ainda. Clique em ▶ Focar nesta tarefa.", "small", "faint",
                                              wrap=True), False, True, 0)
        for _key, when, text, kind in sorted(entries, key=lambda e: e[0], reverse=True)[:40]:
            text_classes = {"interrupted": ("small", "text-danger"), "open": ("small", "text-primary", "bold"),
                            "manual": ("small", "muted"), "distraction": ("small", "text-amber-dark")}.get(kind, ("small", "text2"))
            self.history_box.pack_start(
                hbox(label(when, "small", "muted", width=92), expand(label(text, *text_classes, wrap=True)),
                     spacing=8, valign=Gtk.Align.START), False, True, 0)
        self.history_box.show_all()

    def _fill_list(self):
        for child in self.list_box.get_children():
            self.list_box.remove(child)
            child.destroy()
        view = self.controller.today_view()
        for group in view.groups:
            for task in group.tasks:
                self.list_box.pack_start(self._list_item(group, task), False, True, 0)
        self.list_box.show_all()

    def _list_item(self, group, task):
        selected = task.id == self.task_id
        meta = f"{format_real(task.real_seconds)}/{format_minutes(task.estimate_min)}" if task.estimate_min \
            else (format_real(task.real_seconds) if task.real_seconds else "")
        title_classes = ["muted", "strike"] if task.done else (["bold"] if selected else [])
        row = hbox(GroupDot(group.color), expand(label(task.title, "small", *title_classes, ellipsize=True)),
                   label(meta, "caption", "muted"), spacing=10,
                   classes=("task-row", "task-row-focus") if selected else ("task-row",))
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(row)
        box.connect("button-press-event", lambda _w, event, tid=task.id: self._on_list_clicked(tid, event))
        return box

    def _fill_subtasks(self, detail):
        for child in self.sub_rows_box.get_children():
            self.sub_rows_box.remove(child)
            child.destroy()
        for sub in detail["subtasks"]:
            self.sub_rows_box.pack_start(_SubtaskRow(self, sub), False, True, 0)
        draft = None
        if self._draft:
            draft = _SubtaskRow(self, None)
            self.sub_rows_box.pack_start(draft, False, True, 0)
        self.sub_rows_box.show_all()
        request, self._focus_request = self._focus_request, None
        if request == "draft" and draft is not None:
            GLib.idle_add(draft.title_entry.grab_focus)

    # ---- atualização vinda de fora --------------------------------------

    def refresh_live(self):
        """A cada segundo: tempo real ao vivo (cartão e subtarefas)."""
        if self.task_id is None or self._detail is None:
            return
        tracker = self.controller.tracker
        self._fill_real(self._detail, tracker.live_real_seconds(self.task_id))
        for row in self.sub_rows_box.get_children():
            if isinstance(row, _SubtaskRow) and row.sub is not None:
                row.update_real(tracker.live_real_seconds_subtask(row.sub["id"]))

    def on_data(self, kind):
        """Os dados mudaram: reconstrói tudo, ou só o calculado se o usuário estiver digitando aqui."""
        if self.task_id is None or self._own:
            return
        detail = self.controller.task_detail(self.task_id)
        if detail is None:
            self.task_id = None
            self.emit("back")
            return
        if self._typing_here():
            self._fill_derived(detail)
        else:
            self._fill(detail)

    def _typing_here(self):
        window = self.get_toplevel()
        focus = window.get_focus() if isinstance(window, Gtk.Window) else None
        return focus is not None and isinstance(focus, (Gtk.Entry, Gtk.TextView)) and focus.is_ancestor(self)

    # ---- gravar mudanças --------------------------------------------------

    def _try(self, action, structure=False, full=False):
        """Executa uma mudança do usuário. Em caso de erro, mostra a mensagem e volta ao valor salvo."""
        self._own = True
        try:
            action()
        except (ValueError, KeyError) as error:
            self._own = False
            self.notice(str(error), error=True)
            self._reload()
            return False
        finally:
            self._own = False
        detail = self.controller.task_detail(self.task_id)
        if detail is None:
            self.emit("back")
            return True
        if full:
            self._fill(detail)
        else:
            self._fill_derived(detail)
            if structure:
                self._fill_subtasks(detail)
        return True

    def notice(self, message, error=False):
        classes = self.notice_label.get_style_context()
        classes.remove_class("text-danger")
        classes.remove_class("text-green-dark")
        classes.add_class("text-danger" if error else "text-green-dark")
        self.notice_label.set_text(message)
        self.notice_label.show()
        if self._notice_source is not None:
            GLib.source_remove(self._notice_source)
        self._notice_source = GLib.timeout_add(NOTICE_MS, self._clear_notice)

    def _clear_notice(self):
        self._notice_source = None
        self.notice_label.hide()
        return False

    def flush(self):
        """Grava o que estiver pendente (título, notas, subtarefa sendo digitada)."""
        if self.task_id is None:
            return
        self._commit_title()
        self._commit_notes()
        for row in self.sub_rows_box.get_children():
            if isinstance(row, _SubtaskRow) and row.sub is not None:
                self.on_subtask_title_commit(row)
                self.on_subtask_time_commit(row)

    # campos da tarefa
    def _commit_title(self):
        if self._loading or self.task_id is None or self._detail is None:
            return
        text = self.title_entry.get_text().strip()
        current = self._detail["task"]["title"]
        if not text:
            self.title_entry.set_text(current)
        elif text != current:
            self._try(lambda: self.controller.rename_task(self.task_id, text))

    def _on_done_toggled(self, value):
        if not self._loading:
            self._try(lambda: self.controller.set_task_done(self.task_id, value), full=True)

    def _on_group_changed(self, group_id):
        if not self._loading:
            self._try(lambda: self.controller.update_task(self.task_id, group_id=group_id), full=True)

    def _on_date_changed(self, day):
        if self._loading:
            return
        iso = day.isoformat() if day else None
        self._try(lambda: self.controller.update_task(self.task_id, scheduled_for=iso), full=True)

    def _on_repeat_changed(self, rule):
        if not self._loading:
            self._try(lambda: self.controller.update_task(self.task_id, repeat_rule=rule))

    def _on_energy_changed(self, value):
        if not self._loading:
            self._try(lambda: self.controller.update_task(self.task_id, energy=value))

    def _on_estimate_changed(self, minutes):
        if not self._loading:
            self._try(lambda: self.controller.update_task(self.task_id, estimate_min=minutes))

    def _on_notes_changed(self):
        if self._loading:
            return
        if self._notes_source is not None:
            GLib.source_remove(self._notes_source)
        self._notes_source = GLib.timeout_add(NOTES_DELAY_MS, self._commit_notes)

    def _commit_notes(self):
        if self._notes_source is not None:
            GLib.source_remove(self._notes_source)
            self._notes_source = None
        if self._loading or self.task_id is None or self._detail is None:
            return False
        buffer = self.notes_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        if text != (self._detail["task"]["notes"] or ""):
            self._try(lambda: self.controller.update_task(self.task_id, notes=text))
        return False

    # ações
    def _on_adjust(self):
        text = dialogs.ask_text(
            self.get_toplevel(), "Ajustar o tempo real", "", ok="Ajustar",
            hint="Quanto somar ou tirar? Ex.: +10, -5m, 1h, -1h30")
        if text is None:
            return
        minutes = parse_signed_minutes(text)
        if minutes is None:
            self.notice("Não entendi o ajuste. Use +10, -5m ou 1h.", error=True)
            return
        self._try(lambda: self.controller.adjust_real_time(self.task_id, minutes))

    def _on_use_ai(self):
        if self._ai_suggestion:
            minutes = self._ai_suggestion["minutes"]
            self._try(lambda: self.controller.update_task(self.task_id, estimate_min=minutes), full=True)

    def _on_ai_subtasks(self):
        task = self._detail["task"]
        task_id = self.task_id
        self.ai_subs_button.set_sensitive(False)

        def finished(suggested, error):
            self.ai_subs_button.set_sensitive(True)
            if task_id != self.task_id:
                return
            if not suggested:
                self.notice(error or "A IA não encontrou uma divisão para esta tarefa.", error=True)
                return

            def add_all():
                for title, minutes in suggested:
                    self.controller.add_subtask(task_id, title, minutes)

            self._try(add_all, structure=True)

        self.controller.suggest_subtasks_async(task["title"], task["group_id"], finished)

    def _on_duplicate(self):
        copy = self.controller.duplicate_task(self.task_id)
        self.notice(f"Cópia criada para amanhã: “{copy['title']}”.")
        self._fill_list()

    def _on_delete(self):
        title = self._detail["task"]["title"] if self._detail else "esta tarefa"
        if dialogs.confirm(self.get_toplevel(), f"Excluir “{title}”?",
                           "As subtarefas e o histórico de tempo desta tarefa também saem."):
            task_id, self.task_id = self.task_id, None
            self.controller.delete_task(task_id)
            self.emit("back")

    def _on_focus(self):
        self.flush()
        self.controller.focus_and_start(self.task_id)
        self.emit("focus-started")

    def go_back(self):
        self.flush()
        self.emit("back")

    def _on_list_clicked(self, task_id, event):
        if event.button == 1 and task_id != self.task_id:
            self.emit("open-task", task_id)
        return False

    # subtarefas
    def start_draft(self):
        self._draft = True
        self._focus_request = "draft"
        self._fill_subtasks(self._detail)

    def cancel_draft(self):
        self._draft = False
        self._fill_subtasks(self._detail)

    def on_subtask_done(self, row, value):
        if row.sub is not None and bool(row.sub["done"]) != value:
            self._try(lambda: self.controller.set_subtask_done(row.sub["id"], value), structure=True)

    def on_focus_subtask(self, row):
        if row.sub is not None:
            self.flush()
            self.controller.focus_and_start(self.task_id, row.sub["id"])
            self.emit("focus-started")

    def on_delete_subtask(self, row):
        if row.sub is None:
            self.cancel_draft()
        elif dialogs.confirm(self.get_toplevel(), f"Excluir a subtarefa “{row.sub['title']}”?"):
            self._try(lambda: self.controller.delete_subtask(row.sub["id"]), structure=True)

    def on_subtask_enter(self, row):
        """Enter no título: grava e abre a próxima linha para digitar."""
        if row.sub is None:
            title = row.title_entry.get_text().strip()
            if not title:
                self.cancel_draft()
                return
            minutes = self._parse_time(row.time_entry.get_text())
            if minutes is False:
                return
            self._draft = True
            self._focus_request = "draft"
            self._try(lambda: self.controller.add_subtask(self.task_id, title, minutes), structure=True)
        else:
            self.on_subtask_title_commit(row)
            self.start_draft()

    def on_subtask_title_commit(self, row):
        if self._loading or row.sub is None:
            return
        text = row.title_entry.get_text().strip()
        if not text:
            row.title_entry.set_text(row.sub["title"])
        elif text != row.sub["title"]:
            sub_id = row.sub["id"]
            self._own = True
            try:
                self.controller.rename_subtask(sub_id, text)
                row.sub = dict(row.sub, title=text)
            finally:
                self._own = False

    def on_subtask_time_commit(self, row):
        if self._loading:
            return
        minutes = self._parse_time(row.time_entry.get_text())
        if row.sub is None:
            return
        if minutes is False:
            row.time_entry.set_text(format_minutes(row.sub["estimate_min"]) if row.sub["estimate_min"] else "")
            return
        if (minutes or None) != row.sub["estimate_min"]:
            sub_id = row.sub["id"]
            self._try(lambda: self.controller.update_subtask(sub_id, estimate_min=minutes))
            row.sub = dict(row.sub, estimate_min=minutes or None)

    def _parse_time(self, text):
        """Minutos, None (vazio) ou False (texto inválido, já avisado)."""
        text = text.strip()
        if not text:
            return None
        minutes = parse_duration(text)
        if minutes is None:
            self.notice("Não entendi o tempo. Use 20, 1h ou 1:30.", error=True)
            return False
        return minutes

    def on_subtask_dropped(self, dragged_id, target_id, after):
        ids = [s["id"] for s in self._detail["subtasks"]]
        new_order = reorder_ids(ids, dragged_id, target_id, after)
        if new_order != ids:
            self._try(lambda: self.controller.reorder_subtasks(self.task_id, new_order), structure=True)

    def destroy(self):
        for source in (self._notes_source, self._notice_source):
            if source is not None:
                GLib.source_remove(source)
        self._notes_source = self._notice_source = None
        super().destroy()
