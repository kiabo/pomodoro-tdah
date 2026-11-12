"""Pré-visualização da janela principal com dados de exemplo (para conferir o visual).

  scripts/preview.sh                  abre a janela com os dados de exemplo (num banco temporário)
  scripts/preview.sh --png saida.png  gera uma imagem, sem abrir janela
  scripts/preview.sh --screen editor|new-task|groups|analysis|plan|settings[-compact|-sound|-ai] [--png saida.png]
"""

import argparse
import tempfile
from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .. import settings as settings_store
from ..controller import Controller
from .compact_window import CompactWindow
from .dialogs.new_task import NewTaskDialog
from ..ai.estimator import Estimator
from .main_window import MainWindow
from .theme import load_theme, themed_window


class PreviewEstimator(Estimator):
    """Estimador fictício, só para mostrar os cartões da IA na pré-visualização."""

    def suggest_estimate(self, repo, title, group_id, user_estimate_min, **_kwargs):
        if user_estimate_min and "apresent" in title.lower():
            return {"minutes": 80, "note": "Tarefas parecidas (“Montar slides”, “Apresentação trimestral”) "
                                           "levaram em média 1h 20m. Você costuma subestimar apresentações em ~40%."}
        if "relat" in title.lower():
            return {"minutes": 102, "note": "Baseado em 6 relatórios anteriores (média +14%)."}
        return None

    def suggest_subtasks(self, repo, title, group_id=None, limit=8):
        return [("Definir 3 mensagens principais", 20), ("Montar os slides no modelo", 40), ("Ensaiar em voz alta", 20)]


def _fill_history(controller, work, home):
    """Tarefas concluídas nos últimos dias, para a tela de análise ter o que mostrar."""
    repo = controller.repo
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    rows = ((work, "Escrever relatório semanal", 40, 56, 1), (work, "Escrever relatório de vendas", 30, 44, 2),
            (work, "Escrever relatório de projeto", 60, 80, 3), (work, "Revisar contrato", 30, 33, 3),
            (home, "Lavar roupa", 30, 26, 2), (home, "Arrumar a casa", 45, 40, 4), (home, "Lavar louça", 15, 15, 1))
    for group, title, estimate, real, days_ago in rows:
        started = today - timedelta(days=days_ago)
        task = repo.create_task(group["id"], title, estimate_min=estimate, scheduled_for=started.date().isoformat())
        session = repo.start_session("work", task_id=task["id"], started_at=started)
        repo.end_session(session, real * 60, completed_phase=True, ended_at=started + timedelta(minutes=real))
        repo.set_task_status(task["id"], "done")
        repo.conn.execute("UPDATE tasks SET done_at = ? WHERE id = ?", (started.isoformat(timespec="seconds"), task["id"]))
    repo.conn.commit()


def fill_sample_data(controller):
    """Cenário do design: manhã de trabalho, subtarefas, tempos reais e um foco em andamento."""
    repo = controller.repo
    work = repo.update_group(repo.default_group_id(), name="Trabalho", color="#5B5BD6")
    home = repo.create_group("Casa", color="#3DAA7D")
    repo.create_group("Estudos", color="#F2B33D")
    repo.create_group("Saúde", color="#E879A6")

    def worked(task, seconds, subtask=None):
        session = repo.start_session("work", task_id=task["id"], subtask_id=subtask["id"] if subtask else None)
        repo.end_session(session, seconds, completed_phase=True)

    emails = controller.add_task("Responder e-mails do cliente", 20, work["id"])
    worked(emails, 15 * 60)
    controller.set_task_done(emails["id"], True)

    report = controller.add_task("Escrever relatório mensal", 90, work["id"])
    numbers = controller.add_subtask(report["id"], "Levantar números do mês", 25)
    charts = controller.add_subtask(report["id"], "Montar gráficos", 30)
    controller.add_subtask(report["id"], "Revisar texto e enviar", 35)
    worked(report, 20 * 60, numbers)
    controller.set_subtask_done(numbers["id"], True)
    worked(report, 30 * 60, charts)

    controller.add_task("Preparar apresentação para o cliente", 80, work["id"])
    controller.add_task("Lavar roupa", 30, home["id"])
    # Histórico antigo (já concluído em outros dias): alimenta precisão e viés dos grupos.
    for group, history in ((work, ((30, 39), (30, 33), (30, 36))), (home, ((40, 30), (30, 22), (20, 15)))):
        for index, (estimate, real) in enumerate(history):
            old = repo.create_task(group["id"], f"{group['name']} antiga {index}", estimate_min=estimate,
                                   scheduled_for="2026-11-02")
            worked(old, real * 60)
            repo.set_task_status(old["id"], "done")
            repo.conn.execute("UPDATE tasks SET done_at = '2026-11-02T18:00:00' WHERE id = ?", (old["id"],))
    # Recorrentes (agendadas para depois, para não aparecerem em Hoje).
    tomorrow = (controller.today() + timedelta(days=1)).isoformat()
    controller.create_task_full("Responder e-mails", group_id=work["id"], day=tomorrow, estimate_min=20,
                                repeat_rule="weekdays")
    controller.create_task_full("Escrever relatório mensal", group_id=work["id"], day="2026-12-09", estimate_min=90,
                                repeat_rule="monthly:9")
    repo.update_group(work["id"], work_min=50, short_break_min=10, require_estimate=True)
    legacy = repo.create_group("Projeto antigo", color="#8A857C")
    repo.archive_group(legacy["id"])
    controller.add_task("Marcar dentista", 10, home["id"])
    # Fim do dia: o que já está para amanhã, uma tarefa adiada e o humor do dia.
    study = next(g for g in repo.list_groups() if g["name"] == "Estudos")
    health = next(g for g in repo.list_groups() if g["name"] == "Saúde")
    controller.add_to_tomorrow("Estudar capítulo 4", 60, study["id"])
    controller.add_to_tomorrow("Caminhada", 30, health["id"])
    pitch = next(t for t in repo.list_tasks() if t["title"] == "Preparar apresentação para o cliente")
    repo.postpone_task(pitch["id"], controller.today().isoformat())
    controller.set_day_mood("ok")

    # Histórico do relatório: manhã com uma sessão interrompida por distração.
    base = datetime.now().replace(hour=14, minute=5, second=0, microsecond=0)
    for kind_start, minutes, sub, interrupted in ((0, 25, numbers, False), (35, 5, numbers, True)):
        started = base + timedelta(minutes=kind_start)
        session = repo.start_session("work", task_id=report["id"], subtask_id=sub["id"], started_at=started)
        repo.end_session(session, minutes * 60, interrupted=interrupted, completed_phase=not interrupted,
                         ended_at=started + timedelta(minutes=minutes))
    repo.add_distraction("ligar para o banco", task_id=report["id"])
    _fill_history(controller, work, home)
    controller.estimator = PreviewEstimator()

    controller.focus(report["id"], charts["id"])
    timer = controller.timer           # 15:32 restantes do foco 3 de 4, rodando
    timer.cycle = 3
    timer.remaining = 15 * 60 + 32
    timer.phase_elapsed = timer.phase_total - timer.remaining
    timer.running = True
    controller._emit("data")


def link_sample_jira(controller):
    """Liga a tarefa do relatório a uma issue de exemplo (para ver o selo e o cartão do Jira)."""
    report = next(t for t in controller.repo.list_tasks() if t["title"] == "Escrever relatório mensal")
    controller.repo.save_jira_link(
        report["id"], "FIN-142", project_key="FIN", url="https://empresa.atlassian.net/browse/FIN-142",
        remote_title="Relatório mensal de custos", remote_status="Em andamento",
        remote_description="Consolidar os custos do mês e enviar ao financeiro até sexta.",
        remote_estimate_min=120, remote_updated="2026-11-10T10:00:00.000-0300", issue_type="Tarefa",
        epic_key="DDSG-43")
    controller._changed()
    return report


def build_preview():
    data_dir = tempfile.mkdtemp(prefix="pomodoro-preview-")
    settings = settings_store.sanitize({"free_minutes_per_day": 360})
    controller = Controller(data_dir=data_dir, settings=settings)
    fill_sample_data(controller)
    load_theme()
    return controller, MainWindow(controller)


COMPACT_SCREENS = ("compact-focus", "compact-expanded", "compact-break", "compact-mini", "compact-alert",
                   "compact-rating")
SCREENS = ("today", "editor", "new-task", "groups", "analysis", "plan", "settings", "settings-compact", "settings-sound",
           "settings-ai", "settings-jira", "editor-jira") + COMPACT_SCREENS


def _pump():
    for _ in range(6):
        while Gtk.events_pending():
            Gtk.main_iteration()


def prepare_compact(controller, screen):
    """Coloca o controlador no estado de cada cartão do modo compacto e devolve a janela compacta."""
    compact = CompactWindow(controller)
    controller.last_alert = {"task_id": controller.tracker.active_task_id, "title": "Escrever relatório mensal",
                             "real_seconds": 105 * 60, "estimate_seconds": 90 * 60}
    if screen == "compact-break":
        controller.timer.skip()
        controller.timer.remaining = 3 * 60 + 12
        controller.timer.phase_elapsed = 108
        controller.timer.running = True
    elif screen == "compact-mini":
        compact.mini = True
    elif screen == "compact-alert":
        compact.alert = dict(controller.last_alert)
    elif screen == "compact-rating":
        compact.rating = {"task_id": controller.tracker.active_task_id, "subtask_id": None,
                          "title": "Montar gráficos", "seconds": 25 * 60, "number": 3}
        controller.timer.skip()
        controller.timer.running = True
    elif screen == "compact-expanded":
        compact.focus_card.set_expanded(True)
    return compact


def render_png(path, width=1280, height=860, screen="today"):
    controller, window = build_preview()
    offscreen = Gtk.OffscreenWindow()
    themed_window(offscreen)
    if screen in COMPACT_SCREENS:
        compact = prepare_compact(controller, screen)
        compact.refresh()
        content = compact.frame
        compact.remove(content)
        offscreen.add(content)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(20)
        content.set_margin_bottom(28)
        backdrop = Gtk.CssProvider()
        backdrop.load_from_data(b"window.preview-backdrop { background-color: #55607F; }")
        Gtk.StyleContext.add_provider_for_screen(offscreen.get_screen(), backdrop,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        offscreen.get_style_context().remove_class("app-window")
        offscreen.get_style_context().add_class("preview-backdrop")
        offscreen.get_style_context().add_class("compact-window")
        width, height = 420, None
    elif screen == "new-task":
        dialog = NewTaskDialog(window, controller)
        dialog.title_entry.set_text("Preparar apresentação para o cliente")
        dialog.set_estimate(45)
        for title, minutes in (("Definir 3 mensagens principais", 20), ("Montar os slides no modelo", 40),
                               ("Ensaiar em voz alta", 20)):
            dialog.add_subtask_row(title=title, minutes=minutes, focus=False)
        dialog._refresh_suggestion()
        content = dialog.body
        content.get_parent().remove(content)
        offscreen.add(content)
        width, height = 720, None
    else:
        if screen in ("editor", "editor-jira"):
            report = next(t for t in controller.repo.list_tasks() if t["title"] == "Escrever relatório mensal")
            if screen == "editor-jira":
                link_sample_jira(controller)
            window.open_task_editor(report["id"])
        elif screen in ("groups", "analysis", "plan"):
            window.show_page(screen)
        elif screen.startswith("settings"):
            window.show_page("settings")
            window.settings_page.tabs.set_value(screen.partition("-")[2] or "focus", emit=True)
        content = window.get_child()
        window.remove(content)
        offscreen.add(content)
    offscreen.set_size_request(width, height or -1)
    offscreen.show_all()
    _pump()
    if height is None:
        height = offscreen.get_preferred_height_for_width(width)[1]
        offscreen.set_size_request(width, height)
        offscreen.resize(width, height)
        _pump()
    offscreen.get_pixbuf().savev(path, "png", [], [])
    return width, height


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", help="salva a janela neste arquivo PNG em vez de abri-la")
    parser.add_argument("--screen", choices=SCREENS, default="today")
    parser.add_argument("--width", type=int, default=1280, help="largura da imagem (com --png)")
    args = parser.parse_args()
    if args.png:
        print("PNG %dx%d -> %s" % (*render_png(args.png, width=args.width, screen=args.screen), args.png))
        return
    controller, window = build_preview()
    window.connect("destroy", Gtk.main_quit)
    window.present_today()
    if args.screen in ("editor", "editor-jira"):
        report = next(t for t in controller.repo.list_tasks() if t["title"] == "Escrever relatório mensal")
        if args.screen == "editor-jira":
            link_sample_jira(controller)
        window.open_task_editor(report["id"])
    elif args.screen in ("groups", "analysis", "plan"):
        window.show_page(args.screen)
    elif args.screen.startswith("settings"):
        window.show_page("settings")
        window.settings_page.tabs.set_value(args.screen.partition("-")[2] or "focus", emit=True)
    elif args.screen == "new-task":
        from gi.repository import GLib
        GLib.idle_add(lambda: window.open_new_task_dialog() and False)
    Gtk.main()


if __name__ == "__main__":
    main()
