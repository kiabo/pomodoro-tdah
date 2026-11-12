"""Peças visuais do Jira (D8–D12): selo da chave, selos de contagem, avisos e o botão-menu "Enviar ao Jira"."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from ..layout import button, expand, hbox, label, vbox
from ..theme import style

BANNER_KINDS = ("amber", "gray", "green", "red")
BADGE_KINDS = ("primary", "gray", "green", "amber")


def key_chip(text, soft=False):
    """Selo com a chave da issue (ex.: DDSG-109): cheio no cabeçalho, claro dentro de listas."""
    widget = label(text, "key-chip-soft" if soft else "key-chip")
    widget.set_halign(Gtk.Align.START)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def badge(text, kind="primary"):
    if kind not in BADGE_KINDS:
        raise ValueError(f"tipo de selo desconhecido: {kind}")
    widget = label(text, "badge", f"badge-{kind}")
    widget.set_halign(Gtk.Align.END)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def banner(kind, title, text="", actions=()):
    """Aviso colorido. actions: [(texto, callback)] viram botões pequenos embaixo."""
    if kind not in BANNER_KINDS:
        raise ValueError(f"tipo de aviso desconhecido: {kind}")
    box = vbox(spacing=6, classes=("banner", f"banner-{kind}"))
    if title:
        box.pack_start(label(title, "bold", wrap=True), False, True, 0)
    if text:
        box.pack_start(label(text, wrap=True), False, True, 0)
    if actions:
        row = hbox(spacing=8)
        for caption, callback in actions:
            row.pack_start(button(caption, "banner-btn", on_click=callback), False, False, 0)
        box.pack_start(row, False, True, 0)
    return box


class JiraMenuButton(Gtk.MenuButton):
    """Botão "Enviar ao Jira ▾" que abre um menu em seções.

    set_sections([(título da seção, [item, ...]), ...]) com item = dict(title, sub, callback,
    badge=None, badge_kind="primary", sensitive=True). Clicar fecha o menu e chama o callback.
    """

    def __init__(self, text="Enviar ao Jira"):
        super().__init__()
        style(self, "btn", "btn-menu")
        self.set_use_popover(True)
        self.add(hbox(label(text, "bold"), label("▾", "small"), spacing=6))
        self.popover = Gtk.Popover()
        self.set_popover(self.popover)
        self.items = []                      # [(botão, dict)] na ordem exibida (para os testes)
        self.show_all()

    def set_sections(self, sections):
        box = vbox(spacing=2)
        box.set_border_width(8)
        box.set_size_request(380, -1)
        self.items = []
        for index, (title, items) in enumerate(sections):
            if index:
                box.pack_start(Gtk.Separator(), False, True, 4)
            box.pack_start(label(title, "menu-section"), False, True, 0)
            for item in items:
                widget = self._item(item)
                self.items.append((widget, item))
                box.pack_start(widget, False, True, 0)
        box.pack_start(label("Você revê tudo antes de enviar.", "caption", "faint"), False, True, 6)
        box.show_all()
        old = self.popover.get_child()
        if old is not None:
            self.popover.remove(old)
        self.popover.add(box)

    def _item(self, item):
        texts = vbox(label(item["title"], "bold"), label(item.get("sub", ""), "caption", "muted", wrap=True), spacing=1)
        row = hbox(expand(texts), badge(item["badge"], item.get("badge_kind", "primary")) if item.get("badge") else None,
                   spacing=8)
        widget = style(Gtk.Button(), "menu-item")
        widget.add(row)
        widget.set_sensitive(item.get("sensitive", True))
        widget.connect("clicked", lambda *_: self._chosen(item))
        return widget

    def _chosen(self, item):
        self.popover.popdown()
        GLib.idle_add(lambda: item["callback"]() and False)      # abre a janela depois que o menu fechar
