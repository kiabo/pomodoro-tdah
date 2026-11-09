"""Páginas que ainda não têm a tela completa."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..layout import label, vbox


class PlaceholderPage(Gtk.Box):
    def __init__(self, eyebrow, title, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(32)
        self.pack_start(vbox(label(eyebrow, "eyebrow"), label(title, "title-xl"), spacing=2), False, False, 0)
        card = vbox(label(message, "text2", wrap=True), classes=("card-dashed",))
        self.pack_start(card, False, False, 0)
