"""Pré-visualização da janela principal com dados de exemplo (para conferir o visual).

  scripts/preview.sh                  abre a janela com os dados de exemplo (num banco temporário)
  scripts/preview.sh --png saida.png  gera uma imagem, sem abrir janela
"""

import argparse
import tempfile

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .. import settings as settings_store
from ..controller import Controller
from .main_window import MainWindow
from .theme import load_theme, themed_window


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
    controller.add_task("Marcar dentista", 10, home["id"])

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


def render_png(path, width=1280, height=860):
    controller, window = build_preview()
    content = window.get_child()
    window.remove(content)
    offscreen = Gtk.OffscreenWindow()
    themed_window(offscreen)
    offscreen.add(content)
    offscreen.set_size_request(width, height)
    offscreen.show_all()
    for _ in range(5):
        while Gtk.events_pending():
            Gtk.main_iteration()
    offscreen.get_pixbuf().savev(path, "png", [], [])
    return width, height


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", help="salva a janela neste arquivo PNG em vez de abri-la")
    args = parser.parse_args()
    if args.png:
        print("PNG %dx%d -> %s" % (*render_png(args.png), args.png))
        return
    _controller, window = build_preview()
    window.connect("destroy", Gtk.main_quit)
    window.present_today()
    Gtk.main()


if __name__ == "__main__":
    main()
