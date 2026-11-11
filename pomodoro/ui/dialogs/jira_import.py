"""Pré-visualização da importação do Jira: o que vai entrar, em qual grupo, e o que fica de fora.

Só lê do Jira. Nada é gravado até o usuário clicar em "Importar".
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...jira.importer import EPIC, GROUP, NEW, SAME, SUBTASK, TASK, UPDATE
from ..layout import expand, hbox, label, vbox
from ..theme import style, themed_window
from ..widgets import Select

NEW_GROUP = ""          # valor do Select: o grupo "Jira" padrão (criado se preciso)


class JiraImportDialog(Gtk.Dialog):
    def __init__(self, parent, controller, items):
        super().__init__(title="Importar do Jira", transient_for=parent, modal=True)
        themed_window(self)
        self.controller = controller
        self.items = items
        self.checks = {}                 # chave da issue -> caixa de marcar
        self.group_selects = {}          # chave do projeto -> Select
        self.set_default_size(620, 520)
        self.cancel_button = self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.import_button = self.add_button("Importar", Gtk.ResponseType.OK)
        style(self.import_button, "btn", "btn-primary")
        self.set_default_response(Gtk.ResponseType.OK)

        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(12)
        tasks = [i for i in items if i.kind == TASK]
        subs = sum(1 for i in items if i.kind == SUBTASK and i.action == NEW)
        news = sum(1 for i in tasks if i.action == NEW)
        updates = sum(1 for i in tasks if i.action == UPDATE)
        same = sum(1 for i in tasks if i.action == SAME)
        extra = f" Mais {subs} subtarefa(s) do Jira viram subtarefas locais." if subs else ""
        box.add(label(f"{len(tasks)} tarefas em aberto: {news} novas, {updates} com mudanças, {same} sem mudança."
                      + extra, "text2", wrap=True))
        epics = self._epic_titles()
        if epics:
            box.add(label("Cada épico vira um grupo: " + ", ".join(epics) + ".", "small", wrap=True))
        box.add(label("Importar só lê do Jira. Suas subtarefas, notas e previsões não são alteradas, "
                      "e nada é enviado de volta.", "caption", "muted", wrap=True))
        if not getattr(items, "complete", True):
            box.add(label("Há mais issues do que o app lê de uma vez (1000). Só as primeiras apareceram; "
                          "refine a JQL em Configurações → Jira para ver as outras.", "caption", "text-amber", wrap=True))
        if self._projects():
            box.add(self._groups_section())
        rows = vbox(spacing=6)
        for item in items:
            rows.pack_start(self._row(item), False, True, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(rows)
        box.pack_start(scroll, True, True, 0)
        self.empty_label = label("Nada novo para importar.", "faint", center=True)
        box.add(self.empty_label)
        self.empty_label.set_no_show_all(True)
        self.empty_label.set_visible(not any(i.action != SAME for i in items))
        self.show_all()
        self.empty_label.set_visible(not any(i.action != SAME for i in items))
        self._update_button()

    def _epic_titles(self):
        titles = {}
        for item in self.items:
            if item.kind == EPIC and item.action == GROUP:
                titles[item.issue["key"]] = item.issue["title"]
            elif item.action == NEW and item.epic:
                titles.setdefault(item.epic["key"], item.epic["title"])
        return list(titles.values())

    def _projects(self):
        seen = {}
        for item in self.items:
            if item.action == NEW and item.kind == TASK and not item.epic:
                seen.setdefault(item.issue["project_key"], item.issue["project_name"])
        return seen

    def _groups_section(self):
        repo = self.controller.repo
        options = [(NEW_GROUP, "Jira (grupo padrão)")] + [(g["id"], g["name"]) for g in repo.list_groups()]
        rows = vbox(label("TAREFAS SEM ÉPICO: EM QUAL GRUPO COLOCAR CADA PROJETO", "eyebrow"), spacing=6)
        for key, name in self._projects().items():
            current = next((i.group_id for i in self.items if i.action == NEW and i.kind == TASK and not i.epic
                            and i.issue["project_key"] == key), None)
            select = Select(options, current or NEW_GROUP, width=200)
            self.group_selects[key] = select
            rows.pack_start(hbox(expand(label(f"{key} · {name}" if name else key, ellipsize=True)), select),
                            False, True, 0)
        return rows

    def _row(self, item):
        issue = item.issue
        check = Gtk.CheckButton()
        check.set_active(item.selected)
        check.set_sensitive(item.action != SAME)
        check.connect("toggled", lambda *_: self._update_button())
        self.checks[issue["key"]] = check
        state = {NEW: "nova", UPDATE: "atualizar", SAME: "sem mudança", GROUP: "grupo"}[item.action]
        if item.kind == SUBTASK:
            state = "subtarefa"
        detail = ", ".join(item.changes) if item.action in (UPDATE, NEW, GROUP) else issue["status"]
        kind = issue.get("issue_type") or ""
        return hbox(check, label(issue["key"], "bold", "text-primary", width=90),
                    expand(label(issue["title"], ellipsize=True)),
                    label(" · ".join(p for p in (kind, state, detail) if p), "caption", "muted", ellipsize=True),
                    spacing=10)

    def _update_button(self):
        self.import_button.set_sensitive(any(c.get_active() for c in self.checks.values()))

    def selected_items(self):
        for item in self.items:
            item.selected = self.checks[item.issue["key"]].get_active() and item.action != SAME
        return [i for i in self.items if i.selected]

    def group_choices(self):
        return {key: select.value for key, select in self.group_selects.items()}


def show_import(parent, controller, items):
    """Mostra a pré-visualização; se o usuário confirmar, importa e devolve o resultado (senão None)."""
    dialog = JiraImportDialog(parent, controller, items)
    response = dialog.run()
    result = None
    if response == Gtk.ResponseType.OK and dialog.selected_items():
        result = controller.jira_import(dialog.items, dialog.group_choices())
    dialog.destroy()
    return result
