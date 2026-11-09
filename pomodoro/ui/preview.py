"""Pré-visualização da janela principal com dados de exemplo (para conferir o visual).

  scripts/preview.sh                  abre a janela com os dados de exemplo (num banco temporário)
  scripts/preview.sh --png saida.png  gera uma imagem, sem abrir janela
  scripts/preview.sh --screen editor|new-task|groups|settings[-compact|-sound|-ai] [--png saida.png]
"""

import argparse
import tempfile
from datetime import datetime, timedelta

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .. import settings as settings_store
from ..controller import Controller
from .dialogs.new_task import NewTaskDialog
from .main_window import MainWindow
from .theme import load_theme, themed_window


class PreviewEstimator:
    """Estimador fictício, só para mostrar os cartões da IA na pré-visualização."""

    def suggest_estimate(self, repo, title, group_id, user_estimate_min):
        if user_estimate_min and "apresent" in title.lower():
            return {"minutes": 80, "note": "Tarefas parecidas (“Montar slides”, “Apresentação trimestral”) "
                                           "levaram em média 1h 20m. Você costuma subestimar apresentações em ~40%."}
        if "relat" in title.lower():
            return {"minutes": 102, "note": "Baseado em 6 relatórios anteriores (média +14%)."}
        return None

    def suggest_subtasks(self, repo, title, group_id):
        return [("Definir 3 mensagens principais", 20), ("Montar os slides no modelo", 40), ("Ensaiar em voz alta", 20)]


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
    controller.create_task_full("Responder e-mails", group_id=work["id"], day="2026-11-10", estimate_min=20,
                                repeat_rule="weekdays")
    controller.create_task_full("Escrever relatório mensal", group_id=work["id"], day="2026-12-09", estimate_min=90,
                                repeat_rule="monthly:9")
    repo.update_group(work["id"], work_min=50, short_break_min=10, require_estimate=True)
    legacy = repo.create_group("Projeto antigo", color="#8A857C")
    repo.archive_group(legacy["id"])
    controller.add_task("Marcar dentista", 10, home["id"])

    # Histórico do relatório: manhã com uma sessão interrompida por distração.
    base = datetime.now().replace(hour=14, minute=5, second=0, microsecond=0)
    for kind_start, minutes, sub, interrupted in ((0, 25, numbers, False), (35, 5, numbers, True)):
        started = base + timedelta(minutes=kind_start)
        session = repo.start_session("work", task_id=report["id"], subtask_id=sub["id"], started_at=started)
        repo.end_session(session, minutes * 60, interrupted=interrupted, completed_phase=not interrupted,
                         ended_at=started + timedelta(minutes=minutes))
    repo.add_distraction("ligar para o banco", task_id=report["id"])
    controller.estimator = PreviewEstimator()

    controller.focus(report["id"], charts["id"])
    timer = controller.timer           # 15:32 restantes do foco 3 de 4, rodando
    timer.cycle = 3
    timer.remaining = 15 * 60 + 32
    timer.phase_elapsed = timer.phase_total - timer.remaining
    timer.running = True
    controller._emit("data")


def build_preview():
    data_dir = tempfile.mkdtemp(prefix="pomodoro-preview-")
    settings = settings_store.sanitize({"free_minutes_per_day": 360})
    controller = Controller(data_dir=data_dir, settings=settings)
    fill_sample_data(controller)
    load_theme()
    return controller, MainWindow(controller)


SCREENS = ("today", "editor", "new-task", "groups", "settings", "settings-compact", "settings-sound", "settings-ai")


def _pump():
    for _ in range(6):
        while Gtk.events_pending():
            Gtk.main_iteration()


def render_png(path, width=1280, height=860, screen="today"):
    controller, window = build_preview()
    offscreen = Gtk.OffscreenWindow()
    themed_window(offscreen)
    if screen == "new-task":
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
        if screen == "editor":
            report = next(t for t in controller.repo.list_tasks() if t["title"] == "Escrever relatório mensal")
            window.open_task_editor(report["id"])
        elif screen == "groups":
            window.show_page("groups")
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
    if args.screen == "editor":
        report = next(t for t in controller.repo.list_tasks() if t["title"] == "Escrever relatório mensal")
        window.open_task_editor(report["id"])
    elif args.screen == "groups":
        window.show_page("groups")
    elif args.screen.startswith("settings"):
        window.show_page("settings")
        window.settings_page.tabs.set_value(args.screen.partition("-")[2] or "focus", emit=True)
    elif args.screen == "new-task":
        from gi.repository import GLib
        GLib.idle_add(lambda: window.open_new_task_dialog() and False)
    Gtk.main()


if __name__ == "__main__":
    main()
