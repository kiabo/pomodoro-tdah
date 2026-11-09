import tempfile
import unittest
from datetime import date, datetime

from pomodoro.controller import Controller
from pomodoro.timer import Phase

from .test_repository import FakeClock
from .test_timer import FakeScheduler


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.notes, self.sounds, self.events = [], [], []
        self.scheduler = FakeScheduler()
        self.make()

    def make(self, **settings):
        base = {"work_min": 25, "short_break_min": 5, "long_break_min": 15, "warn_before_end_min": 2}
        base.update(settings)
        from pomodoro import settings as settings_mod
        self.controller = Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize(base), scheduler=self.scheduler,
            notify=self.notes.append, play_sound=self.sounds.append,
            now=self.clock, today=lambda: date(2026, 11, 9),
        )
        self.controller.subscribe(self.events.append)
        return self.controller

    def tearDown(self):
        self.controller.shutdown()
        self._tmp.cleanup()

    def tick(self, n):
        for _ in range(n):
            self.controller.timer.tick()


class TaskActionsTest(ControllerTest):
    def test_add_task_defaults_to_today_in_default_group(self):
        task = self.controller.add_task("  Responder e-mails ", estimate_min=20)
        self.assertEqual((task["title"], task["scheduled_for"], task["estimate_min"]),
                         ("Responder e-mails", "2026-11-09", 20))
        self.assertEqual(task["group_id"], self.controller.repo.default_group_id())
        self.assertIn("data", self.events)

    def test_add_task_validation_bubbles_up(self):
        with self.assertRaises(ValueError):
            self.controller.add_task("   ")
        group = self.controller.repo.create_group("Rígido", require_estimate=True)
        with self.assertRaises(ValueError):
            self.controller.add_task("Sem previsão", group_id=group["id"])

    def test_rename_done_delete(self):
        task = self.controller.add_task("A")
        self.controller.rename_task(task["id"], "B")
        self.controller.set_task_done(task["id"], True)
        self.assertEqual(self.controller.repo.get_task(task["id"])["status"], "done")
        self.controller.set_task_done(task["id"], False)
        self.assertEqual(self.controller.repo.get_task(task["id"])["status"], "todo")
        self.controller.delete_task(task["id"])
        self.assertIsNone(self.controller.repo.get_task(task["id"]))

    def test_deleting_the_focused_task_clears_focus(self):
        task = self.controller.add_task("A")
        self.controller.focus(task["id"])
        self.controller.delete_task(task["id"])
        self.assertIsNone(self.controller.tracker.active_task_id)

    def test_subtask_actions(self):
        task = self.controller.add_task("Relatório")
        sub = self.controller.add_subtask(task["id"], "Gráficos", 30)
        self.controller.rename_subtask(sub["id"], "Gráficos de vendas")
        self.controller.set_subtask_done(sub["id"], True)
        row = self.controller.repo.get_subtask(sub["id"])
        self.assertEqual((row["title"], row["done"]), ("Gráficos de vendas", 1))
        self.controller.focus(task["id"], sub["id"])
        self.controller.delete_subtask(sub["id"])
        self.assertEqual(self.controller.tracker.active_task_id, task["id"])
        self.assertIsNone(self.controller.tracker.active_subtask_id)

    def test_today_view_and_pomodoro_count(self):
        task = self.controller.add_task("Relatório", estimate_min=50)
        self.controller.focus(task["id"])
        self.controller.toggle_timer()
        self.tick(25 * 60)
        self.assertEqual(self.controller.timer.phase, Phase.WORK)       # tempo extra: ainda no foco
        self.controller.skip_phase()
        self.assertEqual(self.controller.pomodoros_today(), 1)
        view = self.controller.today_view()
        self.assertEqual((view.planned_min, view.real_seconds), (50, 1500))


class FocusContextTest(ControllerTest):
    def test_context_for_task_and_subtask(self):
        task = self.controller.add_task("Relatório", estimate_min=90)
        s1 = self.controller.add_subtask(task["id"], "Números")
        s2 = self.controller.add_subtask(task["id"], "Gráficos")
        other = self.controller.add_task("E-mails")
        ctx = self.controller.focus_context(self.controller.today_view())
        self.assertEqual((ctx["task_id"], ctx["task_title"]), (None, None))
        self.assertEqual(ctx["next_title"], "Relatório")
        self.controller.focus(task["id"], s1["id"])
        ctx = self.controller.focus_context(self.controller.today_view())
        self.assertEqual((ctx["task_title"], ctx["subtask_title"], ctx["estimate_min"], ctx["next_title"]),
                         ("Relatório", "Números", 90, "Gráficos"))
        self.assertEqual(s2["title"], "Gráficos")
        self.assertEqual(other["title"], "E-mails")

    def test_estimate_falls_back_to_subtasks_and_no_view(self):
        task = self.controller.add_task("Relatório")
        self.controller.add_subtask(task["id"], "A", 20)
        self.controller.add_subtask(task["id"], "B", 30)
        self.controller.focus(task["id"])
        ctx = self.controller.focus_context()
        self.assertEqual((ctx["estimate_min"], ctx["next_title"]), (50, None))


class CompleteCurrentTest(ControllerTest):
    def test_subtask_then_next_pending(self):
        task = self.controller.add_task("Relatório")
        s1 = self.controller.add_subtask(task["id"], "Um")
        s2 = self.controller.add_subtask(task["id"], "Dois")
        self.controller.focus(task["id"], s1["id"])
        self.assertEqual(self.controller.complete_current(), "subtask")
        self.assertEqual(self.controller.tracker.active_subtask_id, s2["id"])
        self.assertEqual(self.controller.complete_current(), "subtask")
        self.assertEqual((self.controller.tracker.active_task_id, self.controller.tracker.active_subtask_id),
                         (task["id"], None))
        self.assertEqual(self.controller.repo.get_task(task["id"])["status"], "todo")   # tarefa não conclui sozinha

    def test_task_without_subtask(self):
        task = self.controller.add_task("Lavar roupa")
        self.controller.focus(task["id"])
        self.assertEqual(self.controller.complete_current(), "task")
        self.assertEqual(self.controller.repo.get_task(task["id"])["status"], "done")
        self.assertIsNone(self.controller.tracker.active_task_id)

    def test_nothing_in_focus(self):
        self.assertIsNone(self.controller.complete_current())


class TimerWiringTest(ControllerTest):
    def test_phase_change_notifies_plays_sound_and_emits(self):
        self.controller.toggle_timer()
        self.tick(25 * 60)                           # tempo extra ligado: só avisa o estouro
        self.assertEqual(self.sounds, ["complete"])
        self.assertIn("O tempo do foco acabou. Termine o que está fazendo ou faça uma pausa.", self.notes)
        self.controller.skip_phase()
        self.assertIn("Hora de: Pausa curta", self.notes)
        self.assertIn("phase", self.events)
        self.assertEqual(len(self.sounds), 2)

    def test_warning_notification(self):
        self.controller.toggle_timer()
        self.tick(23 * 60)
        self.assertEqual(self.notes, ["Faltam 2 min para o fim do foco"])

    def test_tick_events_reach_subscribers(self):
        self.controller.toggle_timer()
        self.tick(3)
        self.assertGreaterEqual(self.events.count("tick"), 3)

    def test_hyperfocus_notification_names_the_task(self):
        task = self.controller.add_task("Relatório", estimate_min=1)
        self.controller.focus(task["id"])
        self.controller.toggle_timer()
        self.tick(90)
        self.assertTrue(any("Passou do previsto em “Relatório”: 2 min de 1 min" in n for n in self.notes))
        self.assertIn("alert", self.events)

    def test_group_duration_follows_focus(self):
        group = self.controller.repo.create_group("Estudos", work_min=50)
        task = self.controller.add_task("Capítulo 4", group_id=group["id"])
        self.controller.focus(task["id"])
        self.assertEqual(self.controller.timer.remaining, 50 * 60)

    def test_broken_subscriber_does_not_break_others(self):
        def boom(kind):
            raise RuntimeError("defeito")

        self.controller.subscribe(boom)
        with self.assertLogs("pomodoro.controller", level="ERROR"):
            self.controller.add_task("A")
        self.assertIn("data", self.events)


class SettingsAndLifecycleTest(ControllerTest):
    def test_apply_settings_merges_validates_and_persists(self):
        self.controller.apply_settings({"work_min": 50, "short_break_min": 0, "desconhecida": 1})
        self.assertEqual(self.controller.settings["work_min"], 50)
        self.assertEqual(self.controller.settings["short_break_min"], 5)       # inválido: mantém o padrão
        self.assertEqual(self.controller.timer.remaining, 50 * 60)
        self.assertIn("settings", self.events)
        self.controller.shutdown()
        again = Controller(data_dir=self._tmp.name, scheduler=FakeScheduler(), now=self.clock)  # lê do disco
        self.assertEqual(again.settings["work_min"], 50)
        again.shutdown()

    def test_shutdown_saves_running_session_as_interrupted(self):
        task = self.controller.add_task("A")
        self.controller.focus(task["id"])
        self.controller.toggle_timer()
        self.tick(45)
        self.controller.shutdown()
        again = self.make()
        sessions = again.repo.list_sessions()
        self.assertEqual([(s["seconds"], s["interrupted"]) for s in sessions], [(45, 1)])

    def test_restart_and_reset(self):
        self.controller.toggle_timer()
        self.tick(30)
        self.controller.reset_phase()
        self.assertEqual(self.controller.timer.remaining, 25 * 60)
        self.controller.skip_phase()
        self.controller.restart_session()
        self.assertEqual(self.controller.timer.phase, Phase.WORK)


if __name__ == "__main__":
    unittest.main()
