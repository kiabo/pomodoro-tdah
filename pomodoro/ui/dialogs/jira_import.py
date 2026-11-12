"""Pré-visualização da importação do Jira (D11): um bloco por épico, recolhido, e o que mudou nas já importadas.

Só lê do Jira. Nada é gravado até o usuário clicar em "Importar N itens".
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...jira.importer import EPIC, GROUP, NEW, SAME, SUBTASK, TASK, UPDATE
from ..layout import button, expand, hbox, label, vbox
from ..theme import style, themed_window
from ..widgets import Select, key_chip

NEW_GROUP = ""          # valor do Select: o grupo "Jira" padrão (criado se preciso)


class _Block:
    """Um bloco da lista: um épico, as tarefas sem épico de um projeto, ou as já importadas com mudanças."""

    def __init__(self, kind, key, title, known=False):
        self.kind, self.key, self.title, self.known = kind, key, title, known
        self.children = []            # ImportItem das linhas
        self.epic_item = None         # item EPIC (criar o grupo), quando o épico veio na busca
        self.header_check = None
        self.body = None
        self.toggle = None
        self.own_check = None         # caixa de um épico sem filhas: decide se o grupo é criado


class JiraImportDialog(Gtk.Dialog):
    def __init__(self, parent, controller, items):
        super().__init__(title="Importar do Jira", transient_for=parent, modal=True)
        themed_window(self)
        self.controller = controller
        self.items = items
        self.checks = {}                 # chave da issue -> caixa de marcar da linha
        self.group_selects = {}          # chave do projeto -> Select
        self.blocks = []
        self._syncing = False
        self.set_default_size(780, 640)
        self.cancel_button = self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.import_button = self.add_button("Importar", Gtk.ResponseType.OK)
        style(self.import_button, "btn", "btn-primary")
        self.set_default_response(Gtk.ResponseType.OK)
        self._build_blocks()

        box = self.get_content_area()
        box.set_border_width(22)
        box.set_spacing(12)
        box.add(label("Importar do Jira", "title-md"))
        box.add(label("Só lê do Jira. Suas subtarefas, notas e previsões não mudam, e nada é enviado de volta.",
                      "small", "muted", wrap=True))
        box.add(self._summary())
        if not getattr(items, "complete", True):
            box.add(label("Há mais issues do que o app lê de uma vez (1000). Só as primeiras apareceram; "
                          "refine a busca em Configurações → Jira para ver as outras.", "caption", "text-amber",
                          wrap=True))
        listing = vbox(spacing=12, classes=("import-list",))
        for block in self.blocks:
            listing.pack_start(self._block_widget(block), False, True, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(280)
        scroll.add(listing)
        self.empty_label = label("Nada novo para importar.", "faint", center=True)
        self.empty_label.set_no_show_all(True)
        box.pack_start(scroll, True, True, 0)
        box.add(self.empty_label)
        same = sum(1 for i in items if i.action == SAME and i.kind == TASK)
        self.footnote = label((f"{same} já estão em dia. " if same else "") + "Você pode desmarcar o que não quer trazer.",
                              "small", "muted")
        box.add(self.footnote)
        self.show_all()
        self.empty_label.set_visible(not self.blocks)
        scroll.set_visible(bool(self.blocks))
        self._update_button()

    # ---- montagem ---------------------------------------------------------------

    def _build_blocks(self):
        epics, projects, changes = {}, {}, None
        by_key = {}
        for item in self.items:
            if item.kind == EPIC and item.action == GROUP:
                block = epics.setdefault(item.issue["key"], _Block("epic", item.issue["key"], item.issue["title"]))
                block.epic_item = item
        for item in self.items:
            if item.kind == TASK and item.action == NEW:
                if item.epic:
                    known = item.group_id is not None
                    block = epics.setdefault(item.epic["key"], _Block("epic", item.epic["key"], item.epic["title"], known))
                    block.known = block.known or known
                else:
                    block = projects.setdefault(item.issue["project_key"], _Block(
                        "project", item.issue["project_key"], f"Sem épico · projeto {item.issue['project_key']}"))
                block.children.append(item)
                by_key[item.issue["key"]] = block
            elif item.kind == TASK and item.action == UPDATE:
                changes = changes or _Block("changes", "mudancas", "Já importadas, com mudanças no Jira")
                changes.children.append(item)
        for item in self.items:
            if item.kind == SUBTASK and item.action == NEW:
                block = by_key.get(item.parent_key)
                if block is None:
                    changes = changes or _Block("changes", "mudancas", "Já importadas, com mudanças no Jira")
                    block = changes
                block.children.append(item)
        self.blocks = [b for b in list(epics.values()) + list(projects.values()) + ([changes] if changes else [])
                       if b.children or b.epic_item]

    def _summary(self):
        tasks = sum(1 for i in self.items if i.kind == TASK and i.action == NEW)
        subs = sum(1 for i in self.items if i.kind == SUBTASK and i.action == NEW)
        groups = sum(1 for b in self.blocks if b.kind == "epic" and not b.known)
        updates = sum(1 for i in self.items if i.kind == TASK and i.action == UPDATE)
        from ..widgets import badge
        row = hbox(spacing=8)
        for count, text, kind in ((tasks, ("tarefa nova", "tarefas novas"), "primary"),
                                  (groups, ("grupo de épico", "grupos de épico"), "green"),
                                  (subs, ("subtarefa", "subtarefas"), "gray"),
                                  (updates, ("com mudanças", "com mudanças"), "amber")):
            if count:
                chip = badge(f"{count} {text[0] if count == 1 else text[1]}", kind)
                chip.set_halign(Gtk.Align.START)
                row.pack_start(chip, False, False, 0)
        return row

    def _block_widget(self, block):
        outer = vbox(classes=("changes-block",) if block.kind == "changes" else ("epic-block",))
        header = hbox(spacing=10, classes=() if block.kind == "changes" else ("epic-head",))
        if block.kind != "changes":
            block.header_check = Gtk.CheckButton()
            block.header_check.set_active(True)
            block.header_check.connect("toggled", lambda check, b=block: self._on_header_toggled(b, check))
            header.pack_start(block.header_check, False, False, 0)
        title = label(block.title, "bold", ellipsize=True)
        if block.kind == "changes":
            title.get_style_context().add_class("text-amber-dark")
        header.pack_start(expand(title), True, True, 0)
        if block.kind == "epic":
            tag = label("ÉPICO · GRUPO JÁ EXISTE" if block.known else "ÉPICO · VIRA GRUPO NOVO", "tag-epic")
            if block.known:
                tag.get_style_context().add_class("tag-epic-known")
            header.pack_start(tag, False, False, 0)
        if block.kind == "project":
            options = [(NEW_GROUP, "Jira (grupo padrão)")] + [(g["id"], g["name"])
                                                               for g in self.controller.repo.list_groups()]
            current = next((i.group_id for i in block.children if i.group_id), None)
            select = Select(options, current if current in dict(options) else NEW_GROUP, width=200)
            self.group_selects[block.key] = select
            header.pack_start(select, False, False, 0)
        count = len(block.children)
        header.pack_start(label(f"{count} " + ("item" if count == 1 else "itens"), "small", "muted"), False, False, 0)
        body = vbox(spacing=0)
        block.body = body
        if block.kind != "changes":
            block.toggle = button("▸", "btn-link")
            block.toggle.set_tooltip_text("Mostrar ou ocultar as tarefas deste bloco")
            block.toggle.connect("clicked", lambda *_, b=block: self._toggle_block(b))
            header.pack_start(block.toggle, False, False, 0)
        outer.pack_start(header, False, True, 0)
        for item in block.children:
            body.pack_start(self._row(item, block), False, True, 0)
        outer.pack_start(body, False, True, 0)
        body.show_all()                                    # as linhas já ficam visíveis; só o bloco recolhe
        body.set_no_show_all(True)
        body.set_visible(block.kind == "changes")          # épicos e projetos começam recolhidos
        if not block.children and block.epic_item:
            block.own_check = block.header_check
        return outer

    def _row(self, item, block):
        issue = item.issue
        check = Gtk.CheckButton()
        check.set_active(item.selected)
        check.connect("toggled", lambda *_: self._on_row_toggled(block))
        self.checks[issue["key"]] = check
        kind = "subtarefa" if item.kind == SUBTASK else (issue.get("issue_type") or "")
        detail = ", ".join(item.changes) if item.action == UPDATE else ""
        meta = " · ".join(part for part in (kind, detail) if part)
        row = hbox(check, key_chip(issue["key"], soft=True), expand(label(issue["title"], ellipsize=True)),
                   label(meta, "caption", "muted", ellipsize=True) if meta else None, spacing=10,
                   classes=("epic-row",) if block.kind != "changes" else ())
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        return row

    # ---- interação --------------------------------------------------------------

    def _toggle_block(self, block):
        show = not block.body.get_visible()
        block.body.set_visible(show)
        block.toggle.set_label("▾" if show else "▸")

    def _on_header_toggled(self, block, check):
        if self._syncing:
            return
        self._syncing = True
        for item in block.children:
            self.checks[item.issue["key"]].set_active(check.get_active())
        self._syncing = False
        self._update_button()

    def _on_row_toggled(self, block):
        if not self._syncing and block.header_check is not None and block.children:
            states = [self.checks[i.issue["key"]].get_active() for i in block.children]
            self._syncing = True
            block.header_check.set_inconsistent(any(states) and not all(states))
            block.header_check.set_active(all(states) if all(states) or not any(states) else True)
            self._syncing = False
        self._update_button()

    def _chosen_count(self):
        rows = sum(1 for check in self.checks.values() if check.get_active())
        groups = sum(1 for b in self.blocks if b.own_check is not None and b.own_check.get_active())
        return rows + groups

    def _update_button(self):
        count = self._chosen_count()
        self.import_button.set_label(f"Importar {count} " + ("item" if count == 1 else "itens"))
        self.import_button.set_sensitive(count > 0)

    # ---- resultado --------------------------------------------------------------

    def selected_items(self):
        epic_selected = {}
        for block in self.blocks:
            for item in block.children:
                if self.checks[item.issue["key"]].get_active() and item.epic:
                    epic_selected[item.epic["key"]] = True
        for item in self.items:
            if item.issue["key"] in self.checks:
                item.selected = self.checks[item.issue["key"]].get_active() and item.action != SAME
            elif item.kind == EPIC and item.action == GROUP:
                block = next((b for b in self.blocks if b.epic_item is item), None)
                own = block.own_check.get_active() if block and block.own_check is not None else False
                item.selected = epic_selected.get(item.issue["key"], False) or own
            elif item.action == SAME:
                item.selected = False
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
