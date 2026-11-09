import tempfile
import unittest
from datetime import date, datetime

from pomodoro import settings as settings_mod
from pomodoro.ai.claude_client import AIUnavailable
from pomodoro.controller import Controller

from .test_repository import FakeClock
from .test_timer import FakeScheduler


class FakeClaude:
    def __init__(self, key, model, error=None):
        self.key, self.model, self.error = key, model, error

    def _maybe(self):
        if self.error:
            raise AIUnavailable(self.error)

    def subtasks(self, title, summary=""):
        self._maybe()
        return [("Passo 1", 10), ("Passo 2", None)]

    def insights(self, summary):
        self._maybe()
        return ["Uma percepção"]

    def answer(self, question, summary):
        return "Resposta"

    def test_connection(self):
        self._maybe()
        return True


class ControllerAiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.made = []
        self.error = None

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def make(self, **settings):
        base = {"ai_cloud_enabled": True, "anthropic_api_key": "sk-x", "ai_model": "claude-sonnet-5-5"}
        base.update(settings)

        def factory(key, model):
            client = FakeClaude(key, model, self.error)
            self.made.append(client)
            return client

        self.controller = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize(base), scheduler=FakeScheduler(),
            now=FakeClock(datetime(2026, 11, 9, 14, 0, 0)), today=lambda: date(2026, 11, 9),
            run_async=lambda job, deliver: deliver(job()), claude_factory=factory)
        return self.controller

    def result_of(self, call, *args):
        box = []
        call(*args, lambda result, error: box.append((result, error)))
        return box[0]

    def test_cloud_is_off_without_toggle_or_key(self):
        c = self.make(ai_cloud_enabled=False)
        self.assertFalse(c.cloud_ready())
        result, error = self.result_of(c.cloud_insights)
        self.assertEqual(result, None)
        self.assertIn("Ligue a IA na nuvem", error)

    def test_subtasks_prefer_local_history_then_cloud(self):
        c = self.make()
        self.assertEqual(self.result_of(c.suggest_subtasks_async, "Planejar viagem", None),
                         ([("Passo 1", 10), ("Passo 2", None)], None))
        self.assertEqual(self.made[-1].model, "claude-sonnet-5-5")
        self.error = "Sem conexão com a API do Claude."
        self.assertEqual(self.result_of(c.suggest_subtasks_async, "Planejar viagem", None),
                         ([], "Sem conexão com a API do Claude."))

    def test_disabled_ai_gives_nothing(self):
        c = self.make(ai_enabled=False)
        self.assertEqual((c.suggest_estimate("x", None, 30), c.suggest_subtasks("x")), (None, []))
        self.assertFalse(c.cloud_ready())

    def test_insights_answer_and_connection(self):
        c = self.make()
        self.assertEqual(self.result_of(c.cloud_insights), (["Uma percepção"], None))
        self.assertEqual(self.result_of(c.cloud_answer, "quanto?"), ("Resposta", None))
        self.assertEqual(self.result_of(c.test_ai_connection), (True, None))

    def test_apply_predictions(self):
        c = self.make()
        group = c.repo.default_group_id()
        for index in range(4):
            task = c.repo.create_task(group, f"Escrever relatório {index}", estimate_min=30, scheduled_for="2026-11-05")
            session = c.repo.start_session("work", task_id=task["id"], started_at=datetime(2026, 11, 5, 10))
            c.repo.end_session(session, 45 * 60, completed_phase=True, ended_at=datetime(2026, 11, 5, 11))
            c.repo.set_task_status(task["id"], "done")
        today_task = c.repo.create_task(group, "Escrever relatório novo", estimate_min=40, scheduled_for="2026-11-09")
        analysis = c.analysis("week")
        self.assertEqual([(p.user_min, p.ai_min) for p in analysis.predictions], [(40, 60)])
        self.assertEqual(c.apply_ai_predictions(analysis.predictions), 1)
        self.assertEqual(c.repo.get_task(today_task["id"])["estimate_min"], 60)
        self.assertEqual(c.analysis("week").predictions, [])            # já ajustada: não empilha o fator
        self.assertEqual(c.apply_ai_predictions(c.analysis("week").predictions), 0)


if __name__ == "__main__":
    unittest.main()
