"""Lista de tarefas da tela Hoje: grupos → tarefas → subtarefas, com previsto, real e status."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .tokens import COLORS
from .format import delta_text, format_minutes, format_real
from .layout import button, expand, hbox, label, make_check, vbox
from .theme import style
from .widgets import GroupDot, QuickEntry, StatusPill

COL_EST, COL_REAL, COL_STATUS = 80, 80, 100
SUBTASK_INDENT = 32

REAL_COLORS = {"under": COLORS["green"], "over": COLORS["danger"], "active": COLORS["primary"]}


def real_cell(real_seconds, estimate_min, done, active, running):
    """Conteúdo da coluna "Real": (texto, delta, tipo) com tipo em plain | under | over | active."""
    text = format_real(real_seconds)
    if done:
        delta, kind = delta_text(real_seconds, estimate_min)
        return text, delta, kind if kind != "even" else "plain"
    if active:
        return text + (" ⏵" if running else ""), "", "active"
    return text, "", "plain"


def set_real_label(widget, real_seconds, estimate_min, done, active, running):
    text, delta, kind = real_cell(real_seconds, estimate_min, done, active, running)
    escaped = GLib.markup_escape_text(text)
    if kind == "plain" and not delta:
        widget.set_markup(f'<span foreground="{COLORS["gray"]}">{escaped}</span>')
        return
    color = REAL_COLORS[kind]
    extra = f"  {GLib.markup_escape_text(delta)}" if delta else ""
    widget.set_markup(f'<span foreground="{color}" weight="bold">{escaped}{extra}</span>')


def summary_text(planned_min, real_seconds):
    parts = []
    if planned_min:
        parts.append(f"prev {format_minutes(planned_min)}")
    if real_seconds:
        parts.append(f"real {format_real(real_seconds)}")
    return " · ".join(parts)


class TaskList(Gtk.Box):
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.controller = controller
        self._view = None
        self._active = (None, None)
        self._filtered = False
        self._expanded = set()      # tarefas que o usuário abriu
        self._collapsed = set()     # tarefa em foco que o usuário fechou
        self._adding = None         # tarefa que está recebendo uma subtarefa nova
        self._task_cells = {}       # task_id -> (label, TaskView)
        self._subtask_cells = {}    # subtask_id -> (label, SubtaskView, TaskView)
        self._group_cells = {}      # group_id -> (label, GroupView)

    # ---- montagem -------------------------------------------------------

    def render(self, view, active_task_id=None, active_subtask_id=None, filtered=False):
        self._view = view
        self._active = (active_task_id, active_subtask_id)
        self._filtered = filtered
        self._task_cells, self._subtask_cells, self._group_cells = {}, {}, {}
        for child in self.get_children():
            self.remove(child)
            child.destroy()
        if not view.groups:
            self.pack_start(self._empty_state(), False, False, 0)
        for group in view.groups:
            self.pack_start(self._group_header(group), False, False, 0)
            for task in group.tasks:
                self.pack_start(self._task_row(task), False, False, 0)
        self.show_all()

    def _empty_state(self):
        text = ("Nenhuma tarefa encontrada." if self._filtered
                else "Nada por aqui ainda. Despeje a primeira tarefa no campo acima.")
        return vbox(label(text, "faint", center=True), classes=("card-dashed",))

    def _group_header(self, group):
        summary = label(summary_text(group.planned_min, group.real_seconds), "small", "muted")
        self._group_cells[group.id] = (summary, group)
        count = len(group.tasks)
        box = hbox(
            GroupDot(group.color),
            label(group.name, "card-title"),
            expand(label(f"{count} tarefa" + ("s" if count != 1 else ""), "small", "faint")),
            summary, spacing=8,
        )
        box.set_margin_top(10)
        box.set_margin_start(14)
        box.set_margin_end(14)
        return box

    def _is_expanded(self, task, is_active):
        if not task.subtasks and not is_active:
            return False
        if task.id in self._expanded:
            return True
        return is_active and task.id not in self._collapsed

    def _task_row(self, task):
        is_active = task.id == self._active[0]
        expanded = self._is_expanded(task, is_active)
        classes = ["task-row"]
        if task.done:
            classes.append("task-row-done")
        elif is_active:
            classes.append("task-row-focus")

        check = make_check(task.done, focus=is_active and not task.done, tooltip="Concluir",
                           on_toggled=lambda value, tid=task.id: self.controller.set_task_done(tid, value))
        name_parts = []
        if task.subtasks:
            arrow = button("▾" if expanded else "▸", "btn-link")
            arrow.set_tooltip_text("Mostrar/ocultar subtarefas")
            arrow.connect("clicked", lambda *_: self._toggle_expanded(task.id, is_active, expanded))
            name_parts.append(arrow)
        title_classes = ["muted", "strike"] if task.done else (["bold"] if is_active else [])
        name_parts.append(expand(label(task.title, *title_classes, ellipsize=True)))
        if task.subtasks:
            name_parts.append(label(f"{task.subtasks_done}/{len(task.subtasks)} subtarefas", "caption", "muted"))

        est = label(format_minutes(task.estimate_min) if task.estimate_min else "—", "text2", width=COL_EST)
        if not task.estimate_min:
            style(est, "faint")
        real = label("", width=COL_REAL)
        timer = self.controller.timer
        running = timer.running and timer.phase.value == "work"
        set_real_label(real, task.real_seconds, task.estimate_min, task.done, is_active, running)
        self._task_cells[task.id] = (real, task)
        status = self._status_pill(task, is_active)

        top = hbox(check, expand(hbox(*name_parts, spacing=8)), est, real, status, spacing=12)
        rows = [top]
        if expanded:
            for sub in task.subtasks:
                rows.append(self._subtask_row(task, sub))
            rows.append(self._add_subtask_area(task))
        outer = vbox(*rows, spacing=6, classes=classes)
        return self._clickable(outer, lambda: self.controller.focus(task.id),
                               lambda event: self._task_menu(task, event))

    def _status_pill(self, task, is_active):
        status = "done" if task.done else ("doing" if is_active else "todo")
        holder = hbox(StatusPill(status), spacing=0)
        holder.set_size_request(COL_STATUS, -1)
        return holder

    def _subtask_row(self, task, sub):
        is_active = task.id == self._active[0] and sub.id == self._active[1]
        check = make_check(sub.done, square=True, focus=is_active and not sub.done, tooltip="Concluir subtarefa",
                           on_toggled=lambda value, sid=sub.id: self.controller.set_subtask_done(sid, value))
        title_classes = ["muted", "strike"] if sub.done else (["bold"] if is_active else [])
        est = label(format_minutes(sub.estimate_min) if sub.estimate_min else "—", "small", "text2", width=COL_EST)
        if not sub.estimate_min:
            style(est, "faint")
        real = label("", "small", width=COL_REAL)
        timer = self.controller.timer
        running = timer.running and timer.phase.value == "work"
        set_real_label(real, sub.real_seconds, sub.estimate_min, sub.done, is_active, running)
        self._subtask_cells[sub.id] = (real, sub, task)
        if sub.done:
            status = label("Concluída", "caption", "text-green-dark", width=COL_STATUS)
        elif is_active:
            status = label("Em foco", "caption", "text-focus", "bold", width=COL_STATUS)
        else:
            status = label("A fazer", "caption", "muted", width=COL_STATUS)
        row = hbox(check, expand(label(sub.title, "small", *title_classes, ellipsize=True)), est, real, status,
                   spacing=12)
        row.set_margin_start(SUBTASK_INDENT)
        return self._clickable(row, lambda: self.controller.focus(task.id, sub.id),
                               lambda event: self._subtask_menu(task, sub, event))

    def _add_subtask_area(self, task):
        if self._adding == task.id:
            entry = QuickEntry("Nova subtarefa…  (Enter adiciona, Esc cancela)", ghost=False)
            entry.connect("submitted", lambda _e, title, minutes: self._submit_subtask(entry, task, title, minutes))
            entry.connect("cancelled", lambda *_: self._stop_adding())
            GLib.idle_add(entry.grab_title)
            area = hbox(entry, spacing=0)
            expand(entry)
        else:
            link = button("＋ Subtarefa", "btn-link")
            link.connect("clicked", lambda *_: self._start_adding(task.id))
            area = hbox(link, spacing=0)
        area.set_margin_start(SUBTASK_INDENT)
        return area

    # ---- interação ------------------------------------------------------

    @staticmethod
    def _clickable(widget, on_left, on_right):
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(widget)

        def pressed(_w, event):
            if event.button == 1:
                on_left()
            elif event.button == 3:
                on_right(event)
            return False

        box.connect("button-press-event", pressed)
        return box

    def _toggle_expanded(self, task_id, is_active, expanded):
        if expanded:
            self._expanded.discard(task_id)
            if is_active:
                self._collapsed.add(task_id)
        else:
            self._expanded.add(task_id)
            self._collapsed.discard(task_id)
        self.rerender()

    def rerender(self):
        if self._view is not None:
            self.render(self._view, *self._active, filtered=self._filtered)

    def _start_adding(self, task_id):
        self._adding = task_id
        self._expanded.add(task_id)
        self.rerender()

    def _stop_adding(self):
        self._adding = None
        self.rerender()

    def _submit_subtask(self, entry, task, title, minutes):
        try:
            self.controller.add_subtask(task.id, title, minutes)
        except ValueError as error:
            entry.show_error(str(error))

    def _menu(self, items, event):
        menu = Gtk.Menu()
        for text, callback in items:
            if text is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _i, cb=callback: cb())
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return menu

    def _task_menu(self, task, event):
        from . import dialogs
        window = self.get_toplevel()
        return self._menu([
            ("Focar nesta tarefa", lambda: self.controller.focus(task.id)),
            ("Reabrir" if task.done else "Concluir", lambda: self.controller.set_task_done(task.id, not task.done)),
            ("Adicionar subtarefa", lambda: self._start_adding(task.id)),
            (None, None),
            ("Renomear…", lambda: self._rename_task(window, task)),
            ("Excluir…", lambda: self._delete_task(window, task)),
        ], event)

    def _subtask_menu(self, task, sub, event):
        window = self.get_toplevel()
        return self._menu([
            ("Focar nesta subtarefa", lambda: self.controller.focus(task.id, sub.id)),
            ("Reabrir" if sub.done else "Concluir",
             lambda: self.controller.set_subtask_done(sub.id, not sub.done)),
            (None, None),
            ("Renomear…", lambda: self._rename_subtask(window, sub)),
            ("Excluir…", lambda: self._delete_subtask(window, sub)),
        ], event)

    def _rename_task(self, window, task):
        from . import dialogs
        title = dialogs.ask_text(window, "Renomear tarefa", task.title)
        if title:
            self.controller.rename_task(task.id, title)

    def _delete_task(self, window, task):
        from . import dialogs
        if dialogs.confirm(window, f"Excluir “{task.title}”?",
                           "As subtarefas e o histórico de tempo desta tarefa também saem da lista."):
            self.controller.delete_task(task.id)

    def _rename_subtask(self, window, sub):
        from . import dialogs
        title = dialogs.ask_text(window, "Renomear subtarefa", sub.title)
        if title:
            self.controller.rename_subtask(sub.id, title)

    def _delete_subtask(self, window, sub):
        from . import dialogs
        if dialogs.confirm(window, f"Excluir a subtarefa “{sub.title}”?"):
            self.controller.delete_subtask(sub.id)

    # ---- atualização ao vivo (a cada segundo, sem refazer a lista) --------

    def update_live(self):
        tracker = self.controller.tracker
        timer = self.controller.timer
        running = timer.running and timer.phase.value == "work"
        task_id, sub_id = self._active
        live_task = None
        if task_id in self._task_cells:
            widget, task = self._task_cells[task_id]
            live_task = tracker.live_real_seconds(task_id)
            set_real_label(widget, live_task, task.estimate_min, task.done, True, running)
        if sub_id in self._subtask_cells:
            widget, sub, _task = self._subtask_cells[sub_id]
            set_real_label(widget, tracker.live_real_seconds_subtask(sub_id), sub.estimate_min, sub.done, True, running)
        if live_task is not None:
            task = self._task_cells[task_id][1]
            for widget, group in self._group_cells.values():
                if task in group.tasks:
                    widget.set_text(summary_text(group.planned_min, group.real_seconds - task.real_seconds + live_task))

    def live_total_seconds(self):
        """Soma do tempo real das tarefas do dia, com o pomodoro em andamento."""
        if self._view is None:
            return 0
        total = self._view.real_seconds
        task_id = self._active[0]
        if task_id in self._view.real_by_task:
            total += self.controller.tracker.live_real_seconds(task_id) - self._view.real_by_task[task_id]
        return max(total, 0)
