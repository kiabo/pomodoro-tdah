"""Tela Configurações (D5): ciclo, apoio para TDAH, modo compacto, sons e IA. Tudo é salvo na hora."""

import re
from datetime import date

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..format import cycle_summary
from ..layout import button, expand, flow, hbox, label, vbox
from ..theme import style
from ..widgets import ChoiceGroup, CycleBar, Select, TimeStepper, make_bar, make_toggle
from ...ai.claude_client import MODELS
from ...settings import COMPACT_FIELDS

TABS = [("focus", "Pomodoro e foco"), ("compact", "Modo compacto"), ("sound", "Sons e notificações"),
        ("jira", "Jira"), ("ai", "IA e dados")]
END_SOUNDS = [("complete", "Sino suave"), ("message", "Mensagem"), ("bell", "Sino"),
              ("alarm-clock-elapsed", "Despertador"), ("", "Mudo")]
THRESHOLDS = [(125, "125%"), (150, "150%"), (200, "200%")]
COMPACT_FIELD_NAMES = {
    "remaining": "Tempo restante", "current_task": "Tarefa atual", "next_break": "Próximo intervalo",
    "progress": "Barra de progresso", "estimate_vs_real": "Previsto vs real",
}
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def focos_formatter(value):
    return f"{value} foco{'s' if value != 1 else ''}"


def focos_parser(text):
    match = re.match(r"^\s*(\d+)\s*(?:focos?)?\s*$", text or "", re.I)
    return int(match.group(1)) if match else None


def setting_row(title, hint, control):
    texts = vbox(label(title, "setting-title"), label(hint, "setting-hint", wrap=True) if hint else None, spacing=2)
    return hbox(expand(texts), control, spacing=12)


def section(title, *rows, width=None):
    box = vbox(label(title, "card-title"), *rows, spacing=14, classes=("card", "card-lg"))
    box.set_valign(Gtk.Align.START)
    if width:
        box.set_size_request(width, -1)
    return box


class CompactPreview(Gtk.Box):
    """Miniatura do modo compacto que acompanha as opções de campos e de opacidade."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        style(self, "card-mini")
        self.time = label("15:32", "title-lg", "text-on-dark")
        self.task = label("Montar gráficos", "small", "text-on-dark", ellipsize=True)
        self.bar = make_bar(0.4, "focus", dark=True, thin=True)
        self.next = label("Pausa de 5 min às 15:48", "caption", "text-dark-muted")
        self.estimate = label("Real 50m de 1h 30m previstos", "caption", "text-dark-muted")
        for widget in (self.time, self.task, self.bar, self.next, self.estimate):
            widget.set_no_show_all(True)        # a visibilidade vem das opções, não de um show_all()
            self.pack_start(widget, False, True, 0)

    def update(self, settings):
        fields = settings["compact_fields"]
        for field, widget in (("remaining", self.time), ("current_task", self.task), ("progress", self.bar),
                              ("next_break", self.next), ("estimate_vs_real", self.estimate)):
            widget.set_visible(field in fields)
        self.set_opacity(settings["compact_idle_opacity"])


class SettingsPage(Gtk.Box):
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.controller = controller
        self.toggles = {}               # chave da configuração -> interruptor
        self.set_margin_top(28)
        self.set_margin_bottom(20)
        self.set_margin_start(32)
        self.set_margin_end(32)

        self.pack_start(vbox(label("PREFERÊNCIAS", "eyebrow"), label("Configurações", "title-xl"), spacing=2),
                        False, True, 0)
        self.tabs = ChoiceGroup(TABS, "focus", "segmented")
        self.tabs.set_halign(Gtk.Align.START)
        self.tabs.set_homogeneous(False)
        self.tabs.connect("changed", lambda _t, value: self.stack.set_visible_child_name(value))
        self.pack_start(self.tabs, False, True, 0)

        self.stack = Gtk.Stack()
        self.stack.add_named(self._wrap(self._build_focus_tab()), "focus")
        self.stack.add_named(self._wrap(self._build_compact_tab()), "compact")
        self.stack.add_named(self._wrap(self._build_sound_tab()), "sound")
        self.stack.add_named(self._wrap(self._build_jira_tab()), "jira")
        self.stack.add_named(self._wrap(self._build_ai_tab()), "ai")
        self.stack.show_all()
        self.stack.set_visible_child_name("focus")
        self.pack_start(self.stack, True, True, 0)

    @staticmethod
    def _wrap(content):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(content)
        return scroll

    @property
    def settings(self):
        return self.controller.settings

    def _toggle(self, key):
        toggle = make_toggle(bool(self.settings[key]), lambda value, k=key: self._apply({k: value}))
        self.toggles[key] = toggle
        return toggle

    def _apply(self, changes):
        self.controller.apply_settings(changes)
        self._after_change()

    def _after_change(self):
        self._refresh_cycle()
        self.compact_preview.update(self.settings)

    # ---- aba: Pomodoro e foco ---------------------------------------------------

    def _build_focus_tab(self):
        s = self.settings
        steppers = {}
        for key, lo, hi, step in (("work_min", 1, 180, 5), ("short_break_min", 1, 60, 1), ("long_break_min", 1, 120, 5)):
            stepper = TimeStepper(s[key], step=step, minimum=lo, maximum=hi, small=True)
            stepper.connect("value-changed", lambda _s, value, k=key: self._apply({k: value}))
            steppers[key] = stepper
        cycles = TimeStepper(s["cycles_before_long_break"], step=1, minimum=1, maximum=12,
                             formatter=focos_formatter, parser=focos_parser, hint="Digite um número: 4", small=True)
        cycles.connect("value-changed", lambda _s, value: self._apply({"cycles_before_long_break": value}))
        self.cycle_bar = CycleBar()
        self.cycle_text = label("", "caption", "muted", wrap=True)
        self.cycle_text.set_max_width_chars(60)
        cycle_card = section(
            "Ciclo do Pomodoro",
            setting_row("Foco", None, steppers["work_min"]),
            setting_row("Pausa curta", None, steppers["short_break_min"]),
            setting_row("Pausa longa", None, steppers["long_break_min"]),
            setting_row("Pausa longa a cada", None, cycles),
            self.cycle_bar, self.cycle_text,
            setting_row("Iniciar as pausas automaticamente", None, self._toggle("auto_start_breaks")),
            setting_row("Iniciar o próximo foco automaticamente", None, self._toggle("auto_start_work")),
            setting_row("Continuar contando se eu passar do tempo", "O tempo extra entra no tempo real da tarefa",
                        self._toggle("count_overtime")),
        )

        warn = self.warn_toggle = make_toggle(
            s["warn_before_end_min"] > 0, lambda value: self._apply({"warn_before_end_min": 2 if value else 0}))
        self.threshold = ChoiceGroup(THRESHOLDS, self._closest_threshold(s["hyperfocus_threshold_pct"]), "chips-pill")
        self.threshold.connect("changed", lambda _c, value: self._apply({"hyperfocus_threshold_pct": value}))
        self.threshold.set_sensitive(s["hyperfocus_alert"])
        hyper = self.hyper_toggle = make_toggle(s["hyperfocus_alert"], self._on_hyperfocus_toggled)
        tdah_card = section(
            "Apoio para TDAH",
            setting_row("Aviso suave antes do fim", "Um toque 2 min antes, para a transição não ser brusca", warn),
            setting_row("Alerta de hiperfoco", "Avisar quando uma tarefa passar do previsto", hyper),
            hbox(label("Avisar a partir de", "small", "muted"), self.threshold, spacing=10),
            setting_row("Levar pendências para amanhã", "No fim do dia, sugere reanotar o que ficou aberto",
                        self._toggle("carry_over_unfinished")),
            setting_row("Uma coisa por vez", "Durante o foco, esconde as outras tarefas da lista",
                        self._toggle("one_thing_at_a_time")),
            setting_row("Perguntar como foi ao concluir", "Fácil / ok / difícil — ajuda a IA a prever melhor",
                        self._toggle("ask_difficulty")),
        )

        free = TimeStepper(s["free_minutes_per_day"], step=30, minimum=0, maximum=24 * 60, small=True)
        free.connect("value-changed", lambda _s, value: self._apply({"free_minutes_per_day": value}))
        self.reminder = style(Gtk.Entry(), "input")
        self.reminder.set_width_chars(7)
        self.reminder.set_max_width_chars(7)
        self.reminder.set_placeholder_text("desligado")
        self.reminder.set_text(s["end_of_day_reminder"])
        self.reminder.set_tooltip_text("Horário no formato 18:00. Vazio desliga o lembrete.")
        self.reminder.connect("activate", lambda *_: self._commit_reminder())
        self.reminder.connect("focus-out-event", lambda *_: self._commit_reminder() or False)
        day_card = section(
            "Seu dia",
            setting_row("Tempo livre por dia", "Usado para avisar se o planejado cabe no dia", free),
            setting_row("Lembrete do fim do dia", "Hora de revisar e reanotar o dia seguinte", self.reminder),
        )
        self._refresh_cycle()
        return flow(cycle_card, tdah_card, day_card, max_per_line=2, spacing=16, homogeneous=False)

    @staticmethod
    def _closest_threshold(pct):
        return min((value for value, _t in THRESHOLDS), key=lambda value: abs(value - pct))

    def _on_hyperfocus_toggled(self, value):
        self.threshold.set_sensitive(value)
        self._apply({"hyperfocus_alert": value})

    def _commit_reminder(self):
        text = self.reminder.get_text().strip()
        context = self.reminder.get_style_context()
        if text == "" or CLOCK.match(text):
            context.remove_class("entry-error")
            if text != self.settings["end_of_day_reminder"]:
                self._apply({"end_of_day_reminder": text})
        else:
            context.add_class("entry-error")
            self.reminder.set_text(self.settings["end_of_day_reminder"])
            self.reminder.set_tooltip_text("Use o formato 18:00 (ou deixe vazio para desligar).")

    def _refresh_cycle(self):
        s = self.settings
        self.cycle_bar.set_cycle(s["work_min"], s["short_break_min"], s["long_break_min"],
                                 s["cycles_before_long_break"])
        self.cycle_text.set_text(cycle_summary(s["work_min"], s["short_break_min"], s["long_break_min"],
                                               s["cycles_before_long_break"]))

    # ---- aba: Modo compacto -----------------------------------------------------

    def _build_compact_tab(self):
        s = self.settings
        self.compact_preview = CompactPreview()
        self.opacity_label = label(f"{round(s['compact_idle_opacity'] * 100)}%", "small", "text-primary", "bold")
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 5)
        style(scale, "slider-opacity")
        scale.set_draw_value(False)
        scale.set_value(round(s["compact_idle_opacity"] * 100))
        scale.set_hexpand(True)
        scale.connect("value-changed", self._on_opacity_changed)
        self.opacity_scale = scale

        self.field_chips = {}
        chips = []
        for field in COMPACT_FIELDS:
            chip = style(Gtk.ToggleButton(label=COMPACT_FIELD_NAMES[field]), "chip", "chip-pill")
            chip.set_active(field in s["compact_fields"])
            chip.connect("toggled", self._on_field_toggled, field)
            self.field_chips[field] = chip
            chips.append(chip)
        self.field_flow = flow(*chips, max_per_line=5, spacing=6, homogeneous=False)

        card = section(
            "Modo compacto",
            self.compact_preview,
            setting_row("Sempre por cima das outras janelas", None, self._toggle("compact_always_on_top")),
            setting_row("Ir para o compacto ao iniciar um foco", None, self._toggle("compact_on_focus_start")),
            vbox(hbox(expand(label("Opacidade quando o mouse sai", "setting-title")), self.opacity_label), scale,
                 spacing=8),
            vbox(label("Mostrar no compacto", "setting-title"), self.field_flow, spacing=8),
            width=460,
        )
        self.compact_preview.show_all()
        self.compact_preview.update(s)
        return flow(card, max_per_line=1, homogeneous=False, halign=Gtk.Align.START)

    def _on_opacity_changed(self, scale):
        value = round(scale.get_value())
        self.opacity_label.set_text(f"{value}%")
        self._apply({"compact_idle_opacity": value / 100})

    def _on_field_toggled(self, chip, field):
        chosen = [f for f in COMPACT_FIELDS if self.field_chips[f].get_active()]
        if not chosen:                      # o compacto precisa mostrar algo: volta o último
            chip.set_active(True)
            return
        self._apply({"compact_fields": chosen})

    # ---- aba: Sons e notificações -----------------------------------------------

    def _build_sound_tab(self):
        s = self.settings
        sounds = list(END_SOUNDS)
        if s["end_sound"] not in dict(sounds):
            sounds.append((s["end_sound"], s["end_sound"]))
        self.end_sound = Select(sounds, s["end_sound"], width=190)
        self.end_sound.connect("changed", lambda _s, value: self._apply({"end_sound": value}))
        play = button("▶", "btn-secondary", tooltip="Ouvir este som",
                      on_click=lambda: self.controller.test_sound(self.end_sound.value))
        ambient = Select([("", "Nenhum")], "", width=190)
        ambient.set_sensitive(False)
        ticking = make_toggle(False)
        ticking.set_sensitive(False)
        ticking.set_tooltip_text("Em breve")
        card = section(
            "Sons e notificações",
            setting_row("Som ao terminar", None, hbox(self.end_sound, play, spacing=8)),
            setting_row("Som ambiente durante o foco", "Em breve", ambient),
            setting_row("Notificações do sistema", "Avisos de fim de foco, pausa e hiperfoco",
                        self._toggle("system_notifications")),
            setting_row("Tique-taque do relógio", "Em breve", ticking),
            width=460,
        )
        return flow(card, max_per_line=1, homogeneous=False, halign=Gtk.Align.START)

    # ---- aba: Jira --------------------------------------------------------------

    def _jira_entry(self, key, placeholder, secret=False, width=28):
        entry = style(Gtk.Entry(), "input")
        entry.set_placeholder_text(placeholder)
        entry.set_text(self.settings[key])
        entry.set_width_chars(width)
        entry.set_visibility(not secret)
        entry.connect("activate", lambda *_: self._commit_jira(key, entry))
        entry.connect("focus-out-event", lambda *_: self._commit_jira(key, entry) or False)
        return entry

    def _commit_jira(self, key, entry):
        text = entry.get_text().strip()
        if text != self.settings[key]:
            self._apply({key: text})

    def _build_jira_tab(self):
        self.jira_entries = {
            "jira_url": self._jira_entry("jira_url", "https://empresa.atlassian.net"),
            "jira_email": self._jira_entry("jira_email", "voce@empresa.com"),
            "jira_token": self._jira_entry("jira_token", "token da API", secret=True),
            "jira_jql": self._jira_entry("jira_jql", "padrão: minhas issues em aberto", width=34),
        }
        self.jira_status = label("", "small", "muted", wrap=True)
        self.jira_test_button = button("Testar conexão", "btn-secondary", on_click=self._on_jira_test)
        self.jira_import_button = button("Importar minhas issues…", "btn-secondary", on_click=self._on_jira_import)
        card = section(
            "Jira",
            label("O Jira é só um espelho: o app lê as suas issues e você organiza do seu jeito. "
                  "Nada é enviado ao Jira sem você pedir.", "text2", wrap=True),
            setting_row("Endereço", None, self.jira_entries["jira_url"]),
            setting_row("E-mail da conta", None, self.jira_entries["jira_email"]),
            setting_row("Token da API", "Crie em id.atlassian.com → Segurança → Tokens de API. "
                        "Fica só neste computador. Se vazio, usa JIRA_API_TOKEN.", self.jira_entries["jira_token"]),
            setting_row("Busca (JQL)", "Vazio traz só as suas issues em aberto.", self.jira_entries["jira_jql"]),
            hbox(self.jira_test_button, self.jira_import_button, spacing=10),
            self.jira_status,
            width=560,
        )
        column = vbox(card, spacing=16)
        column.set_halign(Gtk.Align.START)
        column.set_valign(Gtk.Align.START)
        return column

    def _commit_jira_all(self):
        for key, entry in self.jira_entries.items():
            self._commit_jira(key, entry)

    def _jira_busy(self, busy, text=""):
        self.jira_test_button.set_sensitive(not busy)
        self.jira_import_button.set_sensitive(not busy)
        self.jira_status.set_text(text)

    def _on_jira_test(self):
        self._commit_jira_all()
        self._jira_busy(True, "Testando…")

        def finished(name, error):
            self._jira_busy(False, f"✓ Conectado como {name}." if not error else error)

        self.controller.test_jira_connection(finished)

    def _on_jira_import(self):
        self._commit_jira_all()
        self._jira_busy(True, "Buscando suas issues…")

        def finished(items, error):
            self._jira_busy(False, error or "")
            if error:
                return
            from ..dialogs.jira_import import show_import
            result = show_import(self.get_toplevel(), self.controller, items)
            if result is not None:
                text = f"{result['created']} importadas, {result['updated']} atualizadas."
                if result["skipped"]:
                    text += " Não entraram: " + "; ".join(f"{k} ({why})" for k, why in result["skipped"]) + "."
                self.jira_status.set_text(text)

        self.controller.jira_preview(finished)

    # ---- aba: IA e dados --------------------------------------------------------

    def _build_ai_tab(self):
        s = self.settings
        self.key_entry = style(Gtk.Entry(), "input")
        self.key_entry.set_visibility(False)
        self.key_entry.set_placeholder_text("sk-ant-…")
        self.key_entry.set_text(s["anthropic_api_key"])
        self.key_entry.set_width_chars(26)
        self.key_entry.connect("activate", lambda *_: self._commit_key())
        self.key_entry.connect("focus-out-event", lambda *_: self._commit_key() or False)
        self.key_entry.set_sensitive(s["ai_cloud_enabled"])
        cloud = make_toggle(s["ai_cloud_enabled"], self._on_cloud_toggled)
        models = [(m, m) for m in MODELS]
        if s["ai_model"] not in MODELS:
            models.append((s["ai_model"], s["ai_model"]))
        self.model_select = Select(models, s["ai_model"], width=190)
        self.model_select.set_sensitive(s["ai_cloud_enabled"])
        self.model_select.connect("changed", lambda _s, value: self._apply({"ai_model": value}))
        self.ai_status = label("", "small", "muted", wrap=True)
        self.test_button = button("Testar conexão", "btn-secondary", on_click=self._on_test_connection)
        self.test_button.set_sensitive(s["ai_cloud_enabled"])
        ai_card = section(
            "Inteligência artificial",
            setting_row("Estimativas locais", "Calcula previsões a partir do seu histórico, sem internet",
                        self._toggle("ai_enabled")),
            setting_row("Usar o Claude (opcional)", "Textos da análise e quebra de tarefas em subtarefas. "
                        "Envia só títulos, grupos e tempos.", cloud),
            setting_row("Chave da API", "Fica só neste computador. Se vazia, usa a variável ANTHROPIC_API_KEY.",
                        self.key_entry),
            setting_row("Modelo", "O padrão é o mais capaz; troque por um menor para gastar menos.", self.model_select),
            hbox(self.test_button, expand(self.ai_status), spacing=12),
            width=520,
        )
        self.export_status = label("", "small", "muted", wrap=True)
        export_button = button("Exportar meus dados…", "btn-secondary", on_click=self._on_export)
        data_card = section(
            "Seus dados",
            label("Tudo fica no seu computador. Você pode levar tarefas, subtarefas e sessões num arquivo JSON "
                  "(as configurações e a chave da API não vão junto).", "text2", wrap=True),
            hbox(export_button, spacing=0), self.export_status,
            width=520,
        )
        column = vbox(ai_card, data_card, spacing=16)
        column.set_halign(Gtk.Align.START)
        column.set_valign(Gtk.Align.START)
        return column

    def _on_cloud_toggled(self, value):
        self.key_entry.set_sensitive(value)
        self.model_select.set_sensitive(value)
        self.test_button.set_sensitive(value)
        self._apply({"ai_cloud_enabled": value})

    def _on_test_connection(self):
        self._commit_key()
        self.ai_status.set_text("Testando…")
        self.test_button.set_sensitive(False)

        def finished(result, error):
            self.test_button.set_sensitive(True)
            self.ai_status.set_text("✓ Conectado ao Claude." if not error else error)

        self.controller.test_ai_connection(finished)

    def _commit_key(self):
        text = self.key_entry.get_text().strip()
        if text != self.settings["anthropic_api_key"]:
            self._apply({"anthropic_api_key": text})

    def _on_export(self):
        dialog = Gtk.FileChooserDialog(title="Exportar meus dados", transient_for=self.get_toplevel(),
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Exportar", Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(f"foco-dados-{date.today().isoformat()}.json")
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and path:
            self.export_to(path)

    def export_to(self, path):
        try:
            count = self.controller.export_data(path)
        except OSError as error:
            self.export_status.set_text(f"Não foi possível salvar: {error.strerror or error}")
            return False
        self.export_status.set_text(f"{count} registros exportados para {path}.")
        return True
