"""Janela de confirmação de um envio ao Jira: mostra exatamente o que vai e só envia se o usuário confirmar."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...jira import push
from ..format import format_real
from ..layout import button, expand, hbox, label, vbox
from ..theme import style, themed_window

TITLES = {push.COMMENT: "Enviar notas como comentário", push.STATUS: "Mudar o status no Jira",
          push.FIELDS: "Atualizar o Jira com os dados daqui", push.WORKLOG: "Lançar o tempo real no Jira",
          push.SUBTASKS: "Criar subtarefas no Jira"}
EXPLAIN = {
    push.COMMENT: "Entra como um comentário novo. Nada do que já existe na issue é alterado.",
    push.STATUS: "Escolha o novo status. Só as mudanças que o fluxo do seu projeto permite aparecem.",
    push.FIELDS: "Marque o que deve ser atualizado na issue. O que ficar desmarcado não é enviado.",
    push.WORKLOG: "Um lançamento por dia, com o tempo cronometrado aqui. O que for lançado não será lançado de novo.",
    push.SUBTASKS: "Cada subtarefa marcada vira uma sub-tarefa nova na issue. As que ficarem desmarcadas continuam só aqui.",
}


class JiraPushDialog(Gtk.Dialog):
    def __init__(self, parent, preview):
        super().__init__(title=TITLES[preview["kind"]], transient_for=parent, modal=True)
        themed_window(self)
        self.preview = preview
        self.checks = []                 # (caixa, alteração) no envio de título/previsão
        self.radios = []                 # (botão, opção) na mudança de status
        self.day_checks = []             # (caixa, dia) no lançamento de tempo
        self.sub_checks = []             # (caixa, subtarefa) na criação de subtarefas
        self.type_radios = []            # (botão, tipo) do tipo de sub-tarefa
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
        {push.COMMENT: self._comment, push.STATUS: self._status, push.FIELDS: self._fields,
         push.WORKLOG: self._worklog, push.SUBTASKS: self._subtasks}[preview["kind"]](box)
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

    def _worklog(self, box):
        for day in self.preview["days"]:
            check = Gtk.CheckButton()
            check.set_active(day["selected"])
            check.connect("toggled", lambda *_: self._update_button())
            self.day_checks.append((check, day))
            text = vbox(label(f"{day['day'][8:10]}/{day['day'][5:7]}/{day['day'][:4]} · {format_real(day['seconds'])}",
                              "bold"),
                        label(f"{day['sessions']} sessão(ões) · começa às {day['started'][11:16]}", "small", "muted"),
                        spacing=2)
            box.add(hbox(check, expand(text), spacing=10, valign=Gtk.Align.START))
        if self.preview["skipped_seconds"]:
            box.add(label("Ficou de fora o tempo de dias com menos de 1 minuto.", "caption", "muted", wrap=True))

    def _subtasks(self, box):
        types = self.preview["types"]
        if len(types) == 1:
            box.add(label(f"Tipo: {types[0]['name']}", "small", "muted"))
        else:
            box.add(label("Tipo de sub-tarefa", "caption", "muted"))
            group = None
            for kind in types:
                radio = Gtk.RadioButton.new_with_label_from_widget(group, kind["name"])
                group = group or radio
                radio.set_active(kind["id"] == self.preview["type_id"])
                self.type_radios.append((radio, kind))
                box.add(radio)
        for item in self.preview["items"]:
            check = Gtk.CheckButton()
            check.set_active(item["selected"])
            check.connect("toggled", lambda *_: self._update_button())
            self.sub_checks.append((check, item))
            estimate = f" · previsão {item['estimate_min']} min" if item["estimate_min"] else ""
            box.add(hbox(check, expand(label(item["title"] + estimate, wrap=True)), spacing=10))

    def _update_button(self):
        kind = self.preview["kind"]
        if kind == push.WORKLOG:
            ok = any(check.get_active() for check, _d in self.day_checks)
        elif kind == push.SUBTASKS:
            ok = any(check.get_active() for check, _i in self.sub_checks)
        elif kind == push.FIELDS:
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
        for check, day in self.day_checks:
            day["selected"] = check.get_active()
        for check, item in self.sub_checks:
            item["selected"] = check.get_active()
        for radio, kind in self.type_radios:
            if radio.get_active():
                self.preview["type_id"] = kind["id"]
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


class JiraPullDialog(Gtk.Dialog):
    """Escolher quais sub-tarefas do Jira trazer para cá. Só lê do Jira."""

    def __init__(self, parent, issue_key, found):
        super().__init__(title="Trazer subtarefas do Jira", transient_for=parent, modal=True)
        themed_window(self)
        self.found, self.checks = found, []
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.import_button = self.add_button("Trazer", Gtk.ResponseType.OK)
        style(self.import_button, "btn", "btn-primary")
        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(8)
        box.add(label(f"Sub-tarefas de {issue_key} que ainda não estão aqui", "card-title", wrap=True))
        box.add(label("Viram subtarefas locais ligadas à do Jira. Nada é alterado no Jira.", "small", "muted", wrap=True))
        for item in found:
            check = Gtk.CheckButton()
            check.set_active(True)
            check.connect("toggled", lambda *_: self.import_button.set_sensitive(
                any(c.get_active() for c, _i in self.checks)))
            self.checks.append((check, item))
            box.add(hbox(check, label(f"{item['key']} · {item['title']}" + ("  (concluída)" if item["done"] else ""),
                                      wrap=True), spacing=10))
        self.show_all()

    def chosen(self):
        return [item for check, item in self.checks if check.get_active()]


def ask_pull(parent, issue_key, found):
    """Devolve as sub-tarefas escolhidas ([] se cancelou)."""
    dialog = JiraPullDialog(parent, issue_key, found)
    response = dialog.run()
    chosen = dialog.chosen() if response == Gtk.ResponseType.OK else []
    dialog.destroy()
    return chosen
