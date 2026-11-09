"""Tela Grupos (D4): cartões com os números de cada grupo e painel para criar/editar."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk

from ... import recurrence
from ...stats import bias_note
from .. import dialogs
from ..format import format_minutes, format_real
from ..layout import FixedWidthBox, button, expand, flow, hbox, label, vbox
from ..theme import GROUP_COLORS, style
from ..widgets import ChoiceGroup, ColorPalette, GroupDot, TimeStepper, make_toggle

CARD_WIDTH = 348
PANEL_WIDTH = 380
LONG_CYCLE = (50, 10)
NOTICE_MS = 5000
INSIGHT_CLASSES = {"under": "text-amber", "over": "text-amber", "good": "text-green-dark", "none": "faint"}


def effective_cycle(card, settings):
    """(foco, pausa curta) que o grupo usa de fato: o próprio ou o padrão do app."""
    return card.work_min or settings["work_min"], card.short_break_min or settings["short_break_min"]


def cycle_choice(work_min, short_break_min):
    """Qual opção do seletor de ciclo descreve esses valores: default, long ou custom."""
    if work_min is None and short_break_min is None:
        return "default"
    return "long" if (work_min, short_break_min) == LONG_CYCLE else "custom"


class _GroupCardWidget(Gtk.EventBox):
    def __init__(self, page, card, selected):
        super().__init__()
        self.set_visible_window(False)
        self.card = card
        settings = page.controller.settings
        work, short = effective_cycle(card, settings)

        menu_button = Gtk.MenuButton()
        style(menu_button, "btn", "btn-ghost")
        menu_button.add(label("⋯", "muted"))
        menu_button.set_tooltip_text("Mais ações")
        menu = Gtk.Menu()
        for text, callback in (
            ("Editar", lambda: page.select(card.id)),
            ("Restaurar" if card.archived else "Arquivar", lambda: page.archive(card.id, not card.archived)),
            ("Excluir…", lambda: page.delete(card.id)),
        ):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _i, cb=callback: cb())
            menu.append(item)
        menu.show_all()
        menu_button.set_popup(menu)

        top = hbox(GroupDot(card.color, size=14, radius=4), expand(label(card.name, "card-title", ellipsize=True)),
                   label("arquivado", "caption", "muted") if card.archived else None, menu_button, spacing=10)
        meta = label(
            f"{card.today_count} tarefa{'s' if card.today_count != 1 else ''} hoje · {card.week_count} na semana · "
            f"pomodoro {work}/{short}", "small", "muted", wrap=True)
        numbers = hbox(
            label(f"Prev {format_minutes(card.planned_min) if card.planned_min else '—'}", "small", "text2"),
            expand(label(f"Real {format_minutes(round(card.real_seconds / 60))}", "small", "text2", xalign=0.5)),
            label(f"Precisão {round(card.accuracy * 100)}%" if card.accuracy is not None else "Precisão —",
                  "small", "bold"), spacing=8)
        text, level = bias_note(card.bias_ratio)
        insight = label(text, "caption", INSIGHT_CLASSES[level], wrap=True)
        classes = ("card", "card-selected") if selected else ("card",)
        body = vbox(top, meta, numbers, insight, spacing=10, classes=classes)
        body.set_size_request(CARD_WIDTH, -1)
        if card.archived:
            body.set_opacity(0.7)
        self.add(body)
        self.connect("button-press-event", lambda _w, event: page.select(card.id) if event.button == 1 else None)


class GroupPanel(FixedWidthBox):
    """Painel de edição. Emite "saved"(id), "closed", "archive"(id, bool), "delete"(id) e "add-recurring"(id)."""

    __gsignals__ = {
        "saved": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "closed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "archive": (GObject.SignalFlags.RUN_FIRST, None, (str, bool)),
        "delete": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "add-recurring": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, controller):
        super().__init__(PANEL_WIDTH, orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.controller = controller
        self.card = None            # GroupCard em edição; None = grupo novo
        self.mode = "empty"         # empty | edit | new
        self._snapshot = None
        self._loading = False
        self._notice_source = None

        self.title_label = label("Editar grupo", "title-md")
        close = button("✕", "btn-ghost", tooltip="Fechar", on_click=lambda: self.emit("closed"))
        self.name_entry = style(Gtk.Entry(), "input")
        self.name_entry.set_placeholder_text("Ex.: Trabalho, Casa, Estudos")
        self.name_entry.connect("activate", lambda *_: self.save())
        self.palette = ColorPalette(GROUP_COLORS[0])
        defaults = controller.settings
        self.cycle = ChoiceGroup([("default", f"Padrão {defaults['work_min']}/{defaults['short_break_min']}"),
                                  ("long", "Longo 50/10"), ("custom", "Personalizar")], "default")
        self.cycle.connect("changed", lambda *_: self._on_cycle_changed())
        self.custom_work = TimeStepper(defaults["work_min"], step=5, minimum=1, maximum=180, small=True)
        self.custom_short = TimeStepper(defaults["short_break_min"], step=1, minimum=1, maximum=60, small=True)
        custom = vbox(hbox(expand(label("Foco")), self.custom_work, spacing=10),
                      hbox(expand(label("Pausa curta")), self.custom_short, spacing=10), spacing=8)
        self.custom_revealer = Gtk.Revealer()
        self.custom_revealer.add(custom)
        self.custom_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.require_toggle = make_toggle(False)
        require = hbox(expand(vbox(label("Exigir previsão de tempo", "setting-title"),
                                   label("Toda tarefa nova pede o tempo estimado", "setting-hint"), spacing=2)),
                       self.require_toggle, spacing=12)
        self.recurring_box = vbox(spacing=6)
        self.add_recurring_button = button("＋ Adicionar recorrente", "btn-link",
                                           on_click=lambda: self.card and self.emit("add-recurring", self.card.id))
        self.notice_label = label("", "small", wrap=True)
        self.notice_label.set_no_show_all(True)

        self.delete_button = button("Excluir", "btn-link", on_click=lambda: self.card and self.emit("delete", self.card.id))
        self.delete_button.get_style_context().add_class("text-danger")
        self.archive_button = button("Arquivar", "btn-link", on_click=self._on_archive)
        self.archive_button.get_style_context().add_class("muted")
        self.save_button = button("Salvar grupo", "btn-primary", on_click=self.save)
        footer = hbox(self.delete_button, expand(self.archive_button), self.save_button, spacing=10)

        self.empty_label = label("Escolha um grupo para editar ou crie um novo.", "text2", wrap=True)
        self.form = vbox(
            hbox(expand(self.title_label), close),
            self._field("Nome do grupo", self.name_entry),
            self._field("Cor", self.palette),
            self._field("Ciclo de pomodoro neste grupo", vbox(self.cycle, self.custom_revealer, spacing=10)),
            require,
            self._field("Tarefas recorrentes do grupo", vbox(self.recurring_box, self.add_recurring_button, spacing=6)),
            self.notice_label, footer, spacing=18)
        self.holder = vbox(self.form, classes=("card", "card-lg"))
        self.pack_start(self.holder, True, True, 0)
        self.holder.pack_start(self.empty_label, False, True, 0)
        self.form.show_all()
        # Só mostrados por show_mode(): um show_all() de fora não pode revelá-los.
        for widget in (self.form, self.empty_label, self.delete_button, self.archive_button,
                       self.add_recurring_button):
            widget.set_no_show_all(True)
        self.show_mode("empty")

    @staticmethod
    def _field(text, widget):
        return vbox(label(text, "caption", "muted"), widget, spacing=8)

    # ---- estado ---------------------------------------------------------

    def show_mode(self, mode):
        self.mode = mode
        editing = mode != "empty"
        self.form.set_visible(editing)
        self.empty_label.set_visible(not editing)
        is_new = mode == "new"
        self.title_label.set_text("Novo grupo" if is_new else "Editar grupo")
        self.save_button.set_label("Criar grupo" if is_new else "Salvar grupo")
        for widget in (self.delete_button, self.archive_button, self.add_recurring_button):
            widget.set_visible(editing and not is_new)

    def load(self, card):
        """Mostra o grupo (GroupCard) para edição; None abre um grupo novo em branco."""
        self._loading = True
        try:
            self.card = card
            settings = self.controller.settings
            self.cycle._buttons["default"].set_label(f"Padrão {settings['work_min']}/{settings['short_break_min']}")
            if card is None:
                self.name_entry.set_text("")
                self.palette.set_value(GROUP_COLORS[0])
                self.cycle.set_value("default")
                self.custom_work.set_minutes(settings["work_min"])
                self.custom_short.set_minutes(settings["short_break_min"])
                self.require_toggle.set_active(False)
                self._fill_recurring([])
                self.show_mode("new")
            else:
                self.name_entry.set_text(card.name)
                self.palette.set_value(card.color)
                self.cycle.set_value(cycle_choice(card.work_min, card.short_break_min))
                self.custom_work.set_minutes(card.work_min or settings["work_min"])
                self.custom_short.set_minutes(card.short_break_min or settings["short_break_min"])
                self.require_toggle.set_active(card.require_estimate)
                self._fill_recurring(card.recurring)
                self.archive_button.set_label("Restaurar" if card.archived else "Arquivar")
                self.show_mode("edit")
        finally:
            self._loading = False
        self.custom_revealer.set_reveal_child(self.cycle.value == "custom")
        self._snapshot = self.draft()
        self.notice_label.hide()

    def clear(self):
        self.card = None
        self._snapshot = None
        self.show_mode("empty")

    def _fill_recurring(self, items):
        for child in self.recurring_box.get_children():
            self.recurring_box.remove(child)
            child.destroy()
        if not items:
            self.recurring_box.pack_start(label("Nenhuma ainda. Tarefas que se repetem aparecem aqui.", "small",
                                                "faint", wrap=True), False, True, 0)
        for item in items:
            when = recurrence.describe(item["rule"]).lower()
            detail = f"{when} · {format_minutes(item['estimate_min'])}" if item["estimate_min"] else when
            row = hbox(expand(label(f"↻  {item['title']}", "small", ellipsize=True)),
                       label(detail, "caption", "muted"), spacing=8, classes=("recurring-row",))
            self.recurring_box.pack_start(row, False, True, 0)
        self.recurring_box.show_all()

    def draft(self):
        choice = self.cycle.value
        work, short = {"default": (None, None), "long": LONG_CYCLE}.get(
            choice, (self.custom_work.minutes, self.custom_short.minutes))
        return {"name": self.name_entry.get_text().strip(), "color": self.palette.value,
                "work_min": work, "short_break_min": short, "require_estimate": self.require_toggle.get_active()}

    def is_dirty(self):
        if self.mode == "empty":
            return False
        if self.mode == "new":
            return bool(self.name_entry.get_text().strip()) or self.draft() != self._snapshot
        return self.draft() != self._snapshot

    def _on_cycle_changed(self):
        self.custom_revealer.set_reveal_child(self.cycle.value == "custom")

    # ---- ações ----------------------------------------------------------

    def notice(self, message, error=True):
        context = self.notice_label.get_style_context()
        context.remove_class("text-danger")
        context.remove_class("text-green-dark")
        context.add_class("text-danger" if error else "text-green-dark")
        self.notice_label.set_text(message)
        self.notice_label.show()
        if self._notice_source is not None:
            GLib.source_remove(self._notice_source)
        self._notice_source = GLib.timeout_add(NOTICE_MS, self._clear_notice)

    def _clear_notice(self):
        self._notice_source = None
        self.notice_label.hide()
        return False

    def save(self):
        draft = self.draft()
        if not draft["name"]:
            self.notice("Dê um nome ao grupo.")
            self.name_entry.grab_focus()
            return False
        try:
            if self.card is None:
                group = self.controller.create_group(**draft)
            else:
                group = self.controller.update_group(self.card.id, **draft)
        except (ValueError, KeyError) as error:
            self.notice(str(error))
            return False
        self._snapshot = draft
        self.emit("saved", group["id"])
        return True

    def _on_archive(self):
        if self.card is not None:
            self.emit("archive", self.card.id, not self.card.archived)

    def destroy(self):
        if self._notice_source is not None:
            GLib.source_remove(self._notice_source)
            self._notice_source = None
        super().destroy()


class GroupsPage(Gtk.Box):
    """Emite "add-recurring"(id do grupo) para o botão ＋ Adicionar recorrente."""

    __gsignals__ = {"add-recurring": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.controller = controller
        self.selected = None            # id do grupo, "new" ou None
        self._cards = []
        self._show_archived = False
        self._auto_selected = False
        self.set_margin_top(28)
        self.set_margin_bottom(20)
        self.set_margin_start(32)
        self.set_margin_end(32)

        titles = vbox(label("ORGANIZAÇÃO", "eyebrow"), label("Grupos de tarefas", "title-xl"), spacing=2)
        new = button("＋  Novo grupo", "btn-primary", on_click=lambda: self.select("new"))
        self.pack_start(hbox(expand(titles), new), False, True, 0)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(3)
        self.flow.set_column_spacing(16)
        self.flow.set_row_spacing(16)
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_homogeneous(False)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.flow)
        self.archived_toggle = button("", "btn-link", on_click=self._toggle_archived)
        self.archived_toggle.set_no_show_all(True)
        left = vbox(spacing=10)
        left.pack_start(scroll, True, True, 0)
        left.pack_start(hbox(self.archived_toggle, spacing=0), False, True, 0)

        self.panel = GroupPanel(controller)
        self.panel.connect("saved", lambda _p, group_id: self._on_saved(group_id))
        self.panel.connect("closed", lambda *_: self.select(None))
        self.panel.connect("archive", lambda _p, group_id, archived: self.archive(group_id, archived))
        self.panel.connect("delete", lambda _p, group_id: self.delete(group_id))
        self.panel.connect("add-recurring", lambda _p, group_id: self.emit("add-recurring", group_id))
        panel_scroll = Gtk.ScrolledWindow()
        panel_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panel_scroll.set_size_request(PANEL_WIDTH + 10, -1)
        panel_scroll.add(self.panel)

        row = hbox(valign=Gtk.Align.FILL, spacing=20)
        row.pack_start(left, True, True, 0)
        row.pack_start(panel_scroll, False, True, 0)
        self.pack_start(row, True, True, 0)
        self.refresh()

    # ---- cartões --------------------------------------------------------

    def refresh(self):
        """Refaz os cartões a partir do banco; o painel só é recarregado se não houver edição pendente."""
        self._cards = self.controller.group_cards(include_archived=True)
        active = [c for c in self._cards if not c.archived]
        archived = [c for c in self._cards if c.archived]
        if not self._auto_selected and self.selected is None and active:
            self.selected = active[0].id
            self._auto_selected = True
        self.archived_toggle.set_visible(bool(archived))
        self.archived_toggle.set_label(
            "Ocultar arquivados" if self._show_archived else f"Ver arquivados ({len(archived)})")
        if not archived:
            self._show_archived = False

        for child in self.flow.get_children():
            self.flow.remove(child)
            child.destroy()
        shown = active + (archived if self._show_archived else [])
        for card in shown:
            self.flow.add(_GroupCardWidget(self, card, selected=card.id == self.selected))
        self.flow.add(self._create_card())
        for holder in self.flow.get_children():
            holder.set_can_focus(False)
        self.flow.show_all()
        self._sync_panel()

    def _create_card(self):
        card = vbox(label("＋", "text-primary", "title-lg", center=True),
                    label("Criar novo grupo", "text-primary", "bold", center=True),
                    label("ex.: Projeto X, Finanças, Hobbies", "caption", "faint", center=True),
                    spacing=4, classes=("card-dashed",))
        card.set_size_request(CARD_WIDTH, 150)
        card.set_valign(Gtk.Align.CENTER)
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.add(card)
        box.connect("button-press-event", lambda _w, event: self.select("new") if event.button == 1 else None)
        return box

    def _sync_panel(self):
        if self.selected == "new":
            if self.panel.mode != "new":
                self.panel.load(None)
            return
        card = next((c for c in self._cards if c.id == self.selected), None)
        if card is None:
            self.selected = None
            self.panel.clear()
        elif not self.panel.is_dirty() or self.panel.card is None or self.panel.card.id != card.id:
            self.panel.load(card)

    def _toggle_archived(self):
        self._show_archived = not self._show_archived
        self.refresh()

    # ---- ações ----------------------------------------------------------

    def select(self, key):
        """Seleciona um grupo ("new" abre um em branco; None fecha o painel). Pergunta antes de descartar edições."""
        if key == self.selected and key != "new":
            return True
        if self.panel.is_dirty() and not dialogs.confirm(
                self.get_toplevel(), "Descartar as alterações do grupo?",
                "O que você mudou neste painel ainda não foi salvo.", yes="Descartar"):
            return False
        self.selected = key
        if key == "new":
            self.panel.load(None)
        elif key is None:
            self.panel.clear()
        self.refresh()
        if key == "new":
            self.panel.name_entry.grab_focus()
        return True

    def _on_saved(self, group_id):
        self.selected = group_id
        self.refresh()
        self.panel.load(next(c for c in self._cards if c.id == group_id))
        self.panel.notice("Grupo salvo.", error=False)

    def archive(self, group_id, archived):
        self.controller.archive_group(group_id, archived)
        if archived and self.selected == group_id:
            self.selected = None
            self.panel.clear()
        self.refresh()

    def delete(self, group_id):
        card = next((c for c in self._cards if c.id == group_id), None)
        count = self.controller.group_task_count(group_id)
        detail = (f"As {count} tarefa{'s' if count != 1 else ''} deste grupo também serão excluídas, com o histórico de tempo."
                  if count else "O grupo não tem tarefas.")
        if not dialogs.confirm(self.get_toplevel(), f"Excluir o grupo “{card.name if card else ''}”?", detail):
            return False
        self.controller.delete_group(group_id)
        if self.selected == group_id:
            self.selected = None
            self.panel.clear()
        self.refresh()
        return True

    def on_data(self, kind):
        self.refresh()
