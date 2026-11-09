import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from .timer import Phase, PHASE_LABELS

CSS = b"""
.timer-label {
    font-size: 46px;
    font-weight: bold;
}
.phase-label {
    font-size: 15px;
    font-weight: bold;
}
.cycle-label {
    font-size: 12px;
    opacity: 0.7;
}
.active-task-label {
    font-size: 12px;
    opacity: 0.8;
}
row.active-task {
    font-weight: bold;
}
"""


class MainWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app

        self.set_title("Pomodoro")
        self.set_default_size(360, 540)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.get_style_context().add_class("app-window")
        self.set_border_width(0)

        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._saved_position = None
        self._dialog_open = False

        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", lambda *_: self.hide() or True)
        self.connect("configure-event", self._on_configure)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_border_width(1)
        self.add(outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.set_border_width(8)
        header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        header.connect("button-press-event", self._on_header_press)
        title_lbl = Gtk.Label(label="Pomodoro")
        title_lbl.set_halign(Gtk.Align.START)
        header.pack_start(title_lbl, True, True, 0)

        settings_btn = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        settings_btn.set_tooltip_text("Configurações")
        settings_btn.connect("clicked", self._on_settings_clicked)
        header.pack_start(settings_btn, False, False, 0)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.connect("clicked", lambda *_: self.hide())
        header.pack_start(close_btn, False, False, 0)

        outer.pack_start(header, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        timer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        timer_box.set_border_width(12)

        self.phase_label = Gtk.Label(label=PHASE_LABELS[Phase.WORK])
        self.phase_label.get_style_context().add_class("phase-label")
        timer_box.pack_start(self.phase_label, False, False, 0)

        self.timer_label = Gtk.Label(label="25:00")
        self.timer_label.get_style_context().add_class("timer-label")
        timer_box.pack_start(self.timer_label, False, False, 0)

        self.cycle_label = Gtk.Label(label="")
        self.cycle_label.get_style_context().add_class("cycle-label")
        timer_box.pack_start(self.cycle_label, False, False, 0)

        self.active_task_label = Gtk.Label(label="Nenhuma tarefa selecionada")
        self.active_task_label.set_line_wrap(True)
        self.active_task_label.set_justify(Gtk.Justification.CENTER)
        self.active_task_label.get_style_context().add_class("active-task-label")
        timer_box.pack_start(self.active_task_label, False, False, 4)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_halign(Gtk.Align.CENTER)

        self.toggle_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.toggle_btn.set_tooltip_text("Iniciar / Pausar")
        self.toggle_btn.connect("clicked", lambda *_: self.app.timer.toggle())
        controls.pack_start(self.toggle_btn, False, False, 0)

        skip_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        skip_btn.set_tooltip_text("Pular fase")
        skip_btn.connect("clicked", lambda *_: self.app.timer.skip())
        controls.pack_start(skip_btn, False, False, 0)

        reset_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        reset_btn.set_tooltip_text("Resetar relógio (fase atual)")
        reset_btn.connect("clicked", lambda *_: self.app.timer.reset_phase())
        controls.pack_start(reset_btn, False, False, 0)

        restart_btn = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        restart_btn.set_tooltip_text("Reiniciar sessão inteira")
        restart_btn.connect("clicked", self._on_restart_clicked)
        controls.pack_start(restart_btn, False, False, 0)

        timer_box.pack_start(controls, False, False, 6)

        outer.pack_start(timer_box, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        tasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tasks_box.set_border_width(10)

        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.new_task_entry = Gtk.Entry()
        self.new_task_entry.set_placeholder_text("Nova tarefa...")
        self.new_task_entry.connect("activate", self._on_add_task)
        add_row.pack_start(self.new_task_entry, True, True, 0)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        add_btn.connect("clicked", self._on_add_task)
        add_row.pack_start(add_btn, False, False, 0)

        tasks_box.pack_start(add_row, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.task_listbox = Gtk.ListBox()
        self.task_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.add(self.task_listbox)
        tasks_box.pack_start(scrolled, True, True, 0)

        outer.pack_start(tasks_box, True, True, 0)

        self.refresh_tasks()
        self.refresh_timer()

    # ---- window behaviour -------------------------------------------------

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.popup_near_pointer()

    def popup_near_pointer(self):
        self.show_all()

        if self._saved_position is not None:
            x, y = self._saved_position
        else:
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            _screen, px, py = pointer.get_position()

            width, height = self.get_size()
            monitor = display.get_monitor_at_point(px, py)
            geo = monitor.get_workarea()

            x = min(max(px - width // 2, geo.x), geo.x + geo.width - width)
            y = geo.y

        self.move(x, y)
        self.present()
        self.grab_focus()

    def _on_configure(self, _widget, _event):
        self._saved_position = self.get_position()
        return False

    def _on_header_press(self, _widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def _on_focus_out(self, *_args):
        if self._dialog_open:
            return False
        self.hide()
        return False

    def _on_key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    # ---- timer / phase display --------------------------------------------

    def refresh_timer(self):
        timer = self.app.timer
        remaining = max(timer.remaining, 0)
        mm, ss = divmod(remaining, 60)
        self.timer_label.set_text(f"{mm:02d}:{ss:02d}")
        self.phase_label.set_text(PHASE_LABELS[timer.phase])
        self.cycle_label.set_text(
            f"Turno {timer.cycle}/{timer.settings['cycles_before_long_break']}"
        )
        icon = "media-playback-pause-symbolic" if timer.running else "media-playback-start-symbolic"
        self.toggle_btn.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))

        task = self._active_task()
        if task:
            self.active_task_label.set_text(f"Tarefa atual: {task['title']}")
        else:
            self.active_task_label.set_text("Nenhuma tarefa selecionada")

    def _active_task(self):
        for task in self.app.tasks:
            if task["id"] == self.app.active_task_id:
                return task
        return None

    def _on_restart_clicked(self, *_args):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Reiniciar a sessão inteira?",
            secondary_text="O contador de turnos volta para o início.",
        )
        self._dialog_open = True
        response = dialog.run()
        dialog.destroy()
        self._dialog_open = False
        if response == Gtk.ResponseType.YES:
            self.app.timer.restart_all()

    def _on_settings_clicked(self, *_args):
        settings = self.app.settings
        dialog = Gtk.Dialog(title="Configurações", transient_for=self, modal=True)
        dialog.add_buttons(
            "Cancelar", Gtk.ResponseType.CANCEL,
            "Salvar", Gtk.ResponseType.OK,
        )
        content = dialog.get_content_area()
        content.set_border_width(10)
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        content.add(grid)

        def spin(value, lo, hi):
            adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=1)
            return Gtk.SpinButton(adjustment=adj, numeric=True)

        work_spin = spin(settings["work_min"], 1, 180)
        short_spin = spin(settings["short_break_min"], 1, 60)
        long_spin = spin(settings["long_break_min"], 1, 120)
        cycles_spin = spin(settings["cycles_before_long_break"], 1, 12)

        rows = [
            ("Foco (min)", work_spin),
            ("Pausa curta (min)", short_spin),
            ("Pausa longa (min)", long_spin),
            ("Turnos até pausa longa", cycles_spin),
        ]
        for i, (label_text, widget) in enumerate(rows):
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.START)
            grid.attach(label, 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)

        dialog.show_all()
        self._dialog_open = True
        response = dialog.run()
        self._dialog_open = False
        if response == Gtk.ResponseType.OK:
            new_settings = {
                "work_min": work_spin.get_value_as_int(),
                "short_break_min": short_spin.get_value_as_int(),
                "long_break_min": long_spin.get_value_as_int(),
                "cycles_before_long_break": cycles_spin.get_value_as_int(),
            }
            self.app.apply_settings(new_settings)
        dialog.destroy()

    # ---- task list ----------------------------------------------------

    def _on_add_task(self, *_args):
        title = self.new_task_entry.get_text().strip()
        if not title:
            return
        self.app.add_task(title)
        self.new_task_entry.set_text("")

    def refresh_tasks(self):
        for child in self.task_listbox.get_children():
            self.task_listbox.remove(child)

        for task in self.app.tasks:
            row = self._build_task_row(task)
            self.task_listbox.add(row)

        self.task_listbox.show_all()

    def _build_task_row(self, task):
        row = Gtk.ListBoxRow()
        if task["id"] == self.app.active_task_id:
            row.get_style_context().add_class("active-task")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(4)
        row.add(box)

        check = Gtk.CheckButton()
        check.set_active(task.get("done", False))
        check.connect("toggled", lambda _w, tid=task["id"]: self.app.toggle_task_done(tid))
        box.pack_start(check, False, False, 0)

        entry = Gtk.Entry()
        entry.set_text(task["title"])
        entry.set_editable(False)
        entry.set_has_frame(False)
        entry.set_hexpand(True)
        if task.get("done"):
            entry.get_style_context().add_class("dim-label")

        def commit_edit(widget, tid=task["id"]):
            widget.set_editable(False)
            widget.set_has_frame(False)
            new_title = widget.get_text().strip()
            if new_title and new_title != task["title"]:
                self.app.edit_task(tid, new_title)
            else:
                widget.set_text(task["title"])

        def select_task(_widget, _event, tid=task["id"]):
            if entry.get_editable():
                return False
            self.app.set_active_task(tid)
            return False

        entry.connect("activate", commit_edit)
        entry.connect("focus-out-event", lambda w, e, tid=task["id"]: (commit_edit(w), False)[1])
        entry.connect("button-press-event", select_task)
        box.pack_start(entry, True, True, 0)

        def start_edit(_btn, e=entry):
            e.set_editable(True)
            e.set_has_frame(True)
            e.grab_focus()
            e.select_region(0, -1)

        edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        edit_btn.set_relief(Gtk.ReliefStyle.NONE)
        edit_btn.connect("clicked", start_edit)
        box.pack_start(edit_btn, False, False, 0)

        delete_btn = Gtk.Button.new_from_icon_name("edit-delete-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        delete_btn.set_relief(Gtk.ReliefStyle.NONE)
        delete_btn.connect("clicked", self._on_delete_task, task["id"])
        box.pack_start(delete_btn, False, False, 0)

        return row

    def _on_delete_task(self, _btn, task_id):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Apagar esta tarefa?",
        )
        self._dialog_open = True
        response = dialog.run()
        dialog.destroy()
        self._dialog_open = False
        if response == Gtk.ResponseType.YES:
            self.app.delete_task(task_id)
