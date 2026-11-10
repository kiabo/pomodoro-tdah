"""Atalhos para montar telas: caixas, rótulos e botões já com as classes do tema."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from .theme import style


def hbox(*children, spacing=8, classes=(), valign=Gtk.Align.CENTER):
    box = style(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing), *classes)
    if valign is not None:
        box.set_valign(valign)
    for child in children:
        if child is not None:
            if valign is not None and child.get_valign() == Gtk.Align.FILL:
                child.set_valign(valign)            # sem isso, botões redondos viram elipses
            box.pack_start(child, False, True, 0)   # fill=True: filhos com hexpand ocupam o espaço extra
    return box


def vbox(*children, spacing=0, classes=()):
    box = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing), *classes)
    for child in children:
        if child is not None:
            box.pack_start(child, False, True, 0)
    return box


def flow(*children, max_per_line=4, spacing=12, homogeneous=True, halign=None):
    """Linha que quebra em várias quando falta largura (a largura mínima é a do maior filho)."""
    box = Gtk.FlowBox()
    box.set_selection_mode(Gtk.SelectionMode.NONE)
    box.set_homogeneous(homogeneous)
    box.set_min_children_per_line(1)
    box.set_max_children_per_line(max_per_line)
    box.set_column_spacing(spacing)
    box.set_row_spacing(spacing)
    box.set_activate_on_single_click(False)
    if halign is not None:
        box.set_halign(halign)
    for child in children:
        box.add(child)
    for holder in box.get_children():
        holder.set_can_focus(False)
    return box


def expand(widget):
    """Faz o widget ocupar o espaço que sobrar na caixa."""
    widget.set_hexpand(True)
    return widget


def label(text="", *classes, xalign=0.0, ellipsize=False, wrap=False, width=None, center=False):
    widget = style(Gtk.Label(label=text), *classes)
    widget.set_xalign(0.5 if center else xalign)
    if center:
        widget.set_justify(Gtk.Justification.CENTER)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if width:
        widget.set_size_request(width, -1)
    return widget


def button(text, *classes, tooltip=None, on_click=None):
    widget = style(Gtk.Button(label=text), "btn", *classes)
    if tooltip:
        widget.set_tooltip_text(tooltip)
        widget.get_accessible().set_name(tooltip)      # leitores de tela leem a dica em botões só de ícone
    if on_click:
        widget.connect("clicked", lambda *_: on_click())
    return widget


def make_check(active=False, square=False, focus=False, on_toggled=None, tooltip=None):
    """Caixa de marcar redonda (tarefa) ou quadrada (subtarefa). on_toggled recebe o novo valor."""
    widget = style(Gtk.ToggleButton(label="✓"), "check")
    if square:
        style(widget, "check-square")
    if focus:
        style(widget, "check-focus")
    widget.set_active(active)
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_focus_on_click(False)
    if tooltip:
        widget.set_tooltip_text(tooltip)
        widget.get_accessible().set_name(tooltip)
    if on_toggled:
        widget.connect("toggled", lambda w: on_toggled(w.get_active()))
    return widget


class FixedWidthBox(Gtk.Box):
    """Caixa de largura fixa: ignora a largura "natural" dos filhos (textos longos não a alargam)."""

    def __init__(self, width, **kwargs):
        super().__init__(**kwargs)
        self._fixed_width = width
        self.set_hexpand(False)     # não herda o "expandir" dos filhos: a largura é só a fixa

    def do_get_preferred_width(self):
        return self._fixed_width, self._fixed_width

    def do_get_preferred_width_for_height(self, _height):
        return self._fixed_width, self._fixed_width
