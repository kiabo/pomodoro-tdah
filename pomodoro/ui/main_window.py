"""Janela principal (modo estendido): barra de título, barra lateral e as páginas do app."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from . import dialogs
from .layout import button
from .dialogs import new_task
from .pages.placeholder import BasicSettingsPage, PlaceholderPage
from .pages.task_editor import TaskEditorPage
from .pages.today import TodayPage
from .sidebar import Sidebar
from .theme import style, themed_window

TITLE = "Foco — Pomodoro para TDAH"


class MainWindow(Gtk.Window):
    def __init__(self, controller, on_compact=None):
        super().__init__(title=TITLE)
        themed_window(self)
        self.controller = controller
        self.set_default_size(1280, 860)
        self.set_size_request(1120, 600)
        self.set_icon_name("appointment-soon")

        self.header = Gtk.HeaderBar()
        style(self.header, "titlebar-custom")
        self.header.set_show_close_button(True)
        self.header.set_title(TITLE)
        self.compact_button = button("⤡  Modo compacto", "btn-secondary", tooltip="Modo compacto (em breve)",
                                     on_click=on_compact or (lambda: None))
        self.compact_button.set_sensitive(on_compact is not None)
        self.header.pack_end(self.compact_button)
        self.set_titlebar(self.header)

        self.sidebar = Sidebar(controller)
        self.today = TodayPage(controller)
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.editor = TaskEditorPage(controller)
        self.pages = {
            "today": self.today,
            "task": self.editor,
            "plan": PlaceholderPage("FIM DO DIA", "Revisar e planejar amanhã",
                                    "Aqui você vai revisar o que ficou e reanotar o dia seguinte. Chega na Fase 9."),
            "groups": PlaceholderPage("ORGANIZAÇÃO", "Grupos de tarefas",
                                      "Criar e editar grupos, cores e ciclos próprios. Chega na Fase 6."),
            "analysis": PlaceholderPage("✦ ANÁLISE DA IA", "Como foi sua semana",
                                        "Previsto contra real, padrões e previsões da IA. Chega na Fase 8."),
            "settings": BasicSettingsPage(controller),
        }
        for name, page in self.pages.items():
            self.stack.add_named(page, name)
            page.show_all()             # a pilha só escolhe páginas visíveis
        self.stack.show()
        self.stack.set_visible_child_name("today")

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(self.sidebar, False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.add(root)

        self.sidebar.connect("navigate", lambda _s, page: self.show_page(page))
        self.sidebar.connect("group-selected", lambda *_: self.refresh_tasks())
        self.today.connect("query-changed", lambda *_: self.refresh_tasks())
        self.today.connect("new-task", lambda *_: self.open_new_task_dialog())
        self.today.task_list.on_edit = self.open_task_editor
        self.editor.connect("back", lambda *_: self._leave_editor())
        self.editor.connect("open-task", lambda _e, task_id: self.editor.load(task_id))
        self.editor.connect("focus-started", lambda *_: self.show_page("today"))
        self.connect("delete-event", lambda *_: self.hide() or True)
        self.connect("key-press-event", self._on_key_press)
        self.connect("map", lambda *_: self.refresh_all())
        controller.subscribe(self._on_event)
        self.refresh_all()

    # ---- navegação ------------------------------------------------------

    def show_page(self, name):
        self.stack.set_visible_child_name(name)
        self.sidebar.set_page("today" if name == "task" else name)

    def open_task_editor(self, task_id):
        """Abre a tela Editar tarefa (D2) para a tarefa."""
        self.editor.load(task_id)
        if self.editor.task_id is not None:
            self.show_page("task")

    def _leave_editor(self):
        self.show_page("today")
        self.refresh_all()

    def open_new_task_dialog(self, group_id=None):
        """Abre o modal Nova tarefa (D3). Devolve a tarefa criada ou None."""
        group_id = group_id if group_id is not None else self.sidebar.group_filter
        return new_task.run_new_task_dialog(self, self.controller, group_id=group_id)

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.show_all()
            self.present()

    def present_today(self):
        """Mostra a janela na tela Hoje (a janela só aparece quando o app pede)."""
        self.show_all()
        self.show_page("today")
        self.present()

    def _on_key_press(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_k, Gdk.KEY_K):
            self.show_page("today")
            self.today.focus_search()
            return True
        if ctrl and event.keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self.open_new_task_dialog()
            return True
        return False

    # ---- atualização ----------------------------------------------------

    def _on_event(self, kind):
        if not self.get_visible():
            return                      # escondida na bandeja: refaz tudo ao reaparecer ("map")
        editing = self.stack.get_visible_child_name() == "task"
        if kind == "tick":
            self.refresh_timer()
        else:
            self.refresh_all()
            if editing:
                self.editor.on_data(kind)

    def refresh_all(self):
        self.refresh_tasks()
        self.refresh_timer()

    def refresh_tasks(self):
        """Refaz a lista e os totais a partir do banco (dados, filtros ou foco mudaram)."""
        controller = self.controller
        group_id = self.sidebar.group_filter
        query = self.today.query
        filtered = bool(query) or group_id is not None
        view = controller.today_view(query=query, group_id=group_id)
        full = controller.today_view() if filtered else view
        context = controller.focus_context(full)
        group_name = next((g["name"] for g in full.all_groups if g["id"] == group_id), None)
        self.today.new_task_group = group_id
        self.today.refresh(view, context, filtered, group_name)
        # Totais da barra lateral e do cabeçalho valem para o dia inteiro, não para o filtro.
        self.sidebar.set_data(full, controller.settings["free_minutes_per_day"])
        self.sidebar.set_focus_title(context["subtask_title"] or context["task_title"])

    def refresh_timer(self):
        self.sidebar.refresh_timer()
        self.today.refresh_live()
        if self.stack.get_visible_child_name() == "task":
            self.editor.refresh_live()

    # ---- diálogos -------------------------------------------------------

    def confirm_restart(self):
        if dialogs.confirm(self, "Reiniciar a sessão inteira?",
                           "O contador de turnos volta para o início.", yes="Reiniciar"):
            self.controller.restart_session()
