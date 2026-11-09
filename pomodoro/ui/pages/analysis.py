"""Tela Análise (D6): previsto × real, precisão por grupo, padrões e previsões da IA."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...ai.analysis import PERIOD_LABELS, PERIODS
from ...ai.estimator import Estimator
from ..format import format_minutes
from ..layout import button, expand, hbox, label, vbox
from ..theme import style
from ..widgets import BarChart, ChoiceGroup, make_bar

CONF_DOTS = {1: "●○○", 2: "●●○", 3: "●●●", 4: "●●●"}


class AnalysisPage(Gtk.ScrolledWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.period = "week"
        self._analysis = None
        self._cloud_insights = None
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for setter, value in ((self.body.set_margin_top, 28), (self.body.set_margin_bottom, 28),
                              (self.body.set_margin_start, 32), (self.body.set_margin_end, 32)):
            setter(value)
        self.add(self.body)

        self.title_label = label("", "title-xl")
        self.periods = ChoiceGroup([(p, PERIOD_LABELS[p]) for p in PERIODS], self.period)
        self.periods.connect("changed", lambda _g, value: self.set_period(value))
        self.body.pack_start(hbox(expand(vbox(label("✦ ANÁLISE DA IA", "eyebrow", "text-amber"), self.title_label,
                                              spacing=2)), self.periods, spacing=10), False, False, 0)

        self.kpis = hbox(spacing=14, valign=Gtk.Align.START)
        self.kpis.set_homogeneous(True)
        self.kpi_done = self._kpi("Tarefas concluídas")
        self.kpi_focus = self._kpi("Tempo focado", "text-green")
        self.kpi_accuracy = self._kpi("✦ Precisão das previsões", "text-amber-dark", ai=True)
        self.kpi_deviation = self._kpi("Desvio médio por tarefa", "text-focus")
        self.body.pack_start(self.kpis, False, False, 0)

        self.empty = vbox(label("Ainda não há dados para este período.", "bold"),
                          label("Conclua tarefas com tempo previsto e deixe o cronômetro rodar: a IA aprende com o "
                                "que você prevê e com o que realmente leva.", "text2", wrap=True),
                          spacing=4, classes=("card-dashed",))
        self.body.pack_start(self.empty, False, False, 0)

        self.chart = BarChart(height=200)
        self.chart_title = label("Previsto × real por dia", "card-title")
        legend = hbox(label("▇ previsto", "small", "text-primary"), label("▇ real", "small", "text-focus"), spacing=12)
        self.chart_card = vbox(hbox(expand(self.chart_title), legend), self.chart, spacing=10, classes=("card",))
        self.groups_box = vbox(spacing=10)
        self.groups_card = vbox(label("Precisão por grupo", "card-title"), self.groups_box, spacing=12,
                                classes=("card",))
        self.groups_card.set_size_request(340, -1)
        row = hbox(expand(self.chart_card), self.groups_card, spacing=14, valign=Gtk.Align.START)
        self.charts_row = row
        self.body.pack_start(row, False, False, 0)

        self.insights_box = vbox(spacing=6)
        self.claude_button = button("✦ Analisar com o Claude", "btn-dark", on_click=self._on_cloud_insights)
        self.ask_entry = style(Gtk.Entry(), "input")
        self.ask_entry.set_placeholder_text("Pergunte: quanto tempo levo para escrever um relatório?")
        self.ask_entry.connect("activate", lambda *_: self._on_ask())
        self.answer_label = label("", "small", "text-amber-dark", wrap=True)
        self.ai_status = label("", "small", "muted", wrap=True)
        self.insights_card = vbox(
            hbox(expand(label("✦ O que a IA percebeu", "card-title", "text-amber-dark")), self.claude_button),
            self.insights_box, self.ai_status,
            hbox(expand(self.ask_entry), button("Perguntar", "btn-secondary", on_click=self._on_ask)),
            self.answer_label, spacing=10, classes=("card", "card-ai"))
        self.body.pack_start(self.insights_card, False, False, 0)

        self.pred_rows = vbox(spacing=0)
        self.apply_button = button("Aplicar previsões da IA", "btn-primary", on_click=self._on_apply)
        self.pred_status = label("", "small", "text-green-dark")
        self.pred_card = vbox(
            hbox(expand(label("Previsões para as tarefas de hoje", "card-title")), self.pred_status, self.apply_button),
            self.pred_rows, spacing=10, classes=("card",))
        self.body.pack_start(self.pred_card, False, False, 0)
        for widget in (self.empty, self.charts_row, self.claude_button, self.pred_card):
            widget.show_all()
            widget.set_no_show_all(True)     # só aparecem quando refresh() decide
        self.refresh()

    def _kpi(self, title, value_class=None, ai=False):
        value = label("—", "stat-value", *((value_class,) if value_class else ()))
        card = vbox(label(title, "small", "text-amber" if ai else "muted"), value, spacing=2,
                    classes=("card", "card-ai") if ai else ("card",))
        self.kpis.pack_start(card, True, True, 0)
        return value

    # ---- dados ------------------------------------------------------------------

    def set_period(self, period):
        self.period = period
        self._cloud_insights = None
        self.periods.set_value(period) if self.periods.value != period else None
        self.refresh()

    def on_data(self, _kind=None):
        self.refresh()

    def refresh(self):
        a = self._analysis = self.controller.analysis(self.period)
        self.title_label.set_text(a.title)
        self.kpi_done.set_text(str(a.done_count))
        self.kpi_focus.set_text(format_minutes(a.focus_seconds / 60))
        self.kpi_accuracy.set_text(f"{round(a.accuracy * 100)}%" if a.accuracy is not None else "—")
        self.kpi_deviation.set_text(f"{format_minutes(a.mean_deviation_min)}" if a.mean_deviation_min is not None else "—")
        self.empty.set_visible(not a.has_data)
        self.charts_row.set_visible(a.has_data)
        self.chart.set_days([{"label": d.label, "planned": d.planned_min, "real": d.real_min} for d in a.days])
        self.chart_title.set_text("Previsto × real por dia" + (" (semana)" if a.period == "day" else ""))
        self._fill_groups(a.groups)
        self._fill_insights(self._cloud_insights or a.insights)
        self._fill_predictions(a.predictions)
        self.claude_button.set_visible(self.controller.cloud_ready())

    def _clear(self, box):
        for child in box.get_children():
            box.remove(child)
            child.destroy()

    def _fill_groups(self, groups):
        self._clear(self.groups_box)
        if not groups:
            self.groups_box.pack_start(label("Sem tarefas medidas neste período.", "small", "muted"), False, False, 0)
        for g in groups:
            percent = round((g.accuracy or 0) * 100)
            color = "green" if percent >= 80 else "primary" if percent >= 60 else "focus"
            self.groups_box.pack_start(vbox(
                hbox(expand(label(g.name, "bold")), label(f"{percent}%", "bold"), spacing=8),
                make_bar(percent / 100, color, thin=True), spacing=4), False, False, 0)
        self.groups_box.show_all()

    def _fill_insights(self, insights):
        self._clear(self.insights_box)
        if not insights:
            insights = ["Preciso de pelo menos 3 tarefas parecidas concluídas para enxergar padrões."]
        for text in insights:
            self.insights_box.pack_start(label("• " + text, "text", "text-amber-dark", wrap=True), False, False, 0)
        self.insights_box.show_all()

    def _fill_predictions(self, predictions):
        self._clear(self.pred_rows)
        self.pred_card.set_visible(bool(predictions))
        self.pred_status.set_text("")
        head = hbox(expand(label("TAREFA", "eyebrow")), label("VOCÊ", "eyebrow", width=90),
                    label("IA", "eyebrow", width=90), label("CONFIANÇA", "eyebrow", width=110), spacing=12)
        self.pred_rows.pack_start(head, False, False, 4)
        for p in predictions:
            row = hbox(expand(vbox(label(p.title, "bold", ellipsize=True), label(p.group_name, "small", "muted"))),
                       label(format_minutes(p.user_min) if p.user_min else "—", width=90),
                       label(format_minutes(p.ai_min), "bold", "text-amber-dark", width=90),
                       label(f"{CONF_DOTS[p.confidence]} {p.confidence_label}", "small", width=110), spacing=12)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            self.pred_rows.pack_start(row, False, False, 0)
        self.pred_rows.show_all()
        self.apply_button.set_sensitive(any(p.ai_min != p.current_estimate_min for p in predictions))

    # ---- ações ------------------------------------------------------------------

    def _on_apply(self):
        changed = self.controller.apply_ai_predictions(self._analysis.predictions)
        self.refresh()
        self.pred_status.set_text(f"{changed} previsões atualizadas." if changed else "Nada para atualizar.")

    def _on_cloud_insights(self):
        self.claude_button.set_sensitive(False)
        self.ai_status.set_text("Pensando…")

        def finished(result, error):
            self.claude_button.set_sensitive(True)
            self.ai_status.set_text(error or "")
            if result:
                self._cloud_insights = result
                self._fill_insights(result)

        self.controller.cloud_insights(finished)

    def _on_ask(self):
        question = self.ask_entry.get_text().strip()
        if not question:
            return
        local = Estimator().answer_duration(self.controller.repo, question)
        if local:
            self.answer_label.set_text(local)
            return
        if not self.controller.cloud_ready():
            self.answer_label.set_text("Não tenho tarefas parecidas no seu histórico para responder. "
                                       "Ligue o Claude em Configurações para perguntas livres.")
            return
        self.answer_label.set_text("Pensando…")
        self.controller.cloud_answer(question, lambda result, error: self.answer_label.set_text(result or error or ""))
