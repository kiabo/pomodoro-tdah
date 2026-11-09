"""Diálogos simples: confirmação e pedido de texto, já com o tema do app."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .theme import style, themed_window


def confirm(parent, text, secondary=None, yes="Excluir"):
    """Pergunta sim/não. Devolve True se o usuário confirmou."""
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE, text=text,
    )
    themed_window(dialog)
    if secondary:
        dialog.format_secondary_text(secondary)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button(yes, Gtk.ResponseType.YES)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.YES


def ask_text(parent, title, initial="", ok="Salvar"):
    """Pede um texto. Devolve o texto (sem espaços nas pontas) ou None se cancelou/ficou vazio."""
    dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    themed_window(dialog)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button(ok, Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    entry = style(Gtk.Entry(), "input")
    entry.set_text(initial)
    entry.set_activates_default(True)
    entry.set_width_chars(36)
    box = dialog.get_content_area()
    box.set_border_width(16)
    box.add(entry)
    dialog.show_all()
    entry.select_region(0, -1)
    response = dialog.run()
    text = entry.get_text().strip()
    dialog.destroy()
    return text if response == Gtk.ResponseType.OK and text else None
