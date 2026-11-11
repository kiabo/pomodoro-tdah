"""Janela de confirmação de um envio ao Jira: mostra exatamente o que vai e só envia se o usuário confirmar."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...jira import push
from ..layout import expand, hbox, label, vbox
from ..theme import style, themed_window

TITLES = {push.COMMENT: "Enviar notas como comentário", push.STATUS: "Mudar o status no Jira",
          push.FIELDS: "Atualizar o Jira com os dados daqui"}
EXPLAIN = {
    push.COMMENT: "Entra como um comentário novo. Nada do que já existe na issue é alterado.",
    push.STATUS: "Escolha o novo status. Só as mudanças que o fluxo do seu projeto permite aparecem.",
    push.FIELDS: "Marque o que deve ser atualizado na issue. O que ficar desmarcado não é enviado.",
}


class JiraPushDialog(Gtk.Dialog):
    def __init__(self, parent, preview):
        super().__init__(title=TITLES[preview["kind"]], transient_for=parent, modal=True)
        themed_window(self)
        self.preview = preview
        self.checks = []                 # (caixa, alteração) no envio de título/previsão
        self.radios = []                 # (botão, opção) na mudança de status
        self.set_default_size(560, -1)
        self.cancel_button = self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.send_button = self.add_button("Enviar ao Jira", Gtk.ResponseType.OK)
        style(self.send_button, "btn", "btn-primary")
        self.set_default_response(Gtk.ResponseType.CANCEL)       # Enter não envia por acidente

        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(10)
        box.add(label(f"{TITLES[preview['kind']]} · {preview['issue_key']}", "card-title", wrap=True))
        box.add(label(EXPLAIN[preview["kind"]], "small", "muted", wrap=True))
        {push.COMMENT: self._comment, push.STATUS: self._status, push.FIELDS: self._fields}[preview["kind"]](box)
        box.add(label("Só isso será enviado, e só agora.", "caption", "faint"))
        self.show_all()
        self._update_button()

    def _comment(self, box):
        view = Gtk.TextView()
        style(view, "notes-view")
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD)
        view.get_buffer().set_text(self.preview["text"])
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(260)
        scroll.set_propagate_natural_height(True)
        scroll.add(view)
        box.add(scroll)
        self.text_view = view

    def _fields(self, box):
        for change in self.preview["changes"]:
            check = Gtk.CheckButton()
            check.set_active(change["selected"])
            check.connect("toggled", lambda *_: self._update_button())
            self.checks.append((check, change))
            text = vbox(label(change["label"], "bold"),
                        label(f"No Jira: {change['before'] or '—'}", "small", "muted", wrap=True),
                        label(f"Vai para: {change['after']}", "small", wrap=True), spacing=2)
            box.add(hbox(check, expand(text), spacing=10, valign=Gtk.Align.START))

    def _status(self, box):
        box.add(label(f"Agora no Jira: {self.preview['current'] or '—'}", "small", "muted"))
        anchor = Gtk.RadioButton()          # fora da tela: deixa todas as opções desmarcadas no início
        for option in self.preview["options"]:
            radio = Gtk.RadioButton.new_with_label_from_widget(anchor, f"{option['name']}  →  {option['to_status']}")
            radio.connect("toggled", lambda *_: self._update_button())
            self.radios.append((radio, option))
            box.add(radio)

    def _update_button(self):
        kind = self.preview["kind"]
        if kind == push.FIELDS:
            ok = any(check.get_active() for check, _c in self.checks)
        elif kind == push.STATUS:
            ok = any(radio.get_active() for radio, _o in self.radios)
        else:
            ok = True
        self.send_button.set_sensitive(ok)

    def confirm(self):
        """Marca no preview o que o usuário escolheu e o confirma."""
        for check, change in self.checks:
            change["selected"] = check.get_active()
        for radio, option in self.radios:
            if radio.get_active():
                self.preview["transition_id"] = option["id"]
        self.preview["confirmed"] = True
        return self.preview


def ask_push(parent, preview):
    """Mostra a janela. Devolve o preview confirmado, ou None se o usuário cancelou."""
    dialog = JiraPushDialog(parent, preview)
    response = dialog.run()
    confirmed = dialog.confirm() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    return confirmed


def send(parent, controller, preview, on_result):
    """Pergunta e, só se confirmado, envia. on_result(mensagem, erro) é chamado ao terminar."""
    confirmed = ask_push(parent, preview)
    if confirmed is not None:
        controller.jira_push(confirmed, on_result)
