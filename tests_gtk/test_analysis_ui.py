import tempfile
import unittest
from datetime import datetime

from tests_gtk._support import make_controller, pump, require_gtk, walk

require_gtk()

from pomodoro.ui.pages.analysis import AnalysisPage  # noqa: E402


def texts(widget):
    from gi.repository import Gtk
    return [w.get_text() for w in walk(widget) if isinstance(w, Gtk.Label)]


class AnalysisPageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        self.repo = self.controller.repo
        self.page = AnalysisPage(self.controller)
        self.page.show_all()

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def add_history(self):
        group = self.repo.default_group_id()
        for index in range(4):
            task = self.repo.create_task(group, f"Escrever relatório {index}", estimate_min=30, scheduled_for="2026-11-09")
            session = self.repo.start_session("work", task_id=task["id"], started_at=datetime(2026, 11, 9, 10))
            self.repo.end_session(session, 45 * 60, completed_phase=True, ended_at=datetime(2026, 11, 9, 11))
            self.repo.set_task_status(task["id"], "done")
        return self.repo.create_task(group, "Escrever relatório novo", estimate_min=40, scheduled_for="2026-11-09")

    def test_empty_state(self):
        self.page.refresh()
        self.assertTrue(self.page.empty.get_visible())
        self.assertFalse(self.page.charts_row.get_visible())
        self.assertFalse(self.page.pred_card.get_visible())
        self.assertEqual(self.page.kpi_accuracy.get_text(), "—")

    def test_with_history_and_period_switch(self):
        task = self.add_history()
        self.page.refresh()
        self.assertFalse(self.page.empty.get_visible())
        self.assertEqual(self.page.kpi_done.get_text(), "4")
        self.assertEqual(self.page.kpi_accuracy.get_text(), "50%")
        self.assertTrue(self.page.pred_card.get_visible())
        self.assertTrue(self.page.apply_button.get_sensitive())
        self.page.set_period("month")
        self.assertEqual(len(self.page.chart.days), 30)
        self.page.apply_button.clicked()
        self.assertEqual(self.repo.get_task(task["id"])["estimate_min"], 60)
        self.assertIn("1 previsões atualizadas.", texts(self.page.pred_card)[1:3] + [self.page.pred_status.get_text()])
        self.assertFalse(self.page.pred_card.get_visible())

    def test_question_answered_locally_without_cloud(self):
        self.add_history()
        self.page.ask_entry.set_text("quanto tempo levo para escrever relatório?")
        self.page._on_ask()
        self.assertIn("Com base em 4 tarefas parecidas", self.page.answer_label.get_text())
        self.page.ask_entry.set_text("viajar para a lua")
        self.page._on_ask()
        self.assertIn("Ligue o Claude", self.page.answer_label.get_text())
        self.assertFalse(self.page.claude_button.get_visible())


if __name__ == "__main__":
    unittest.main()
