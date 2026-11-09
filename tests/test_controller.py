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


class EditTaskTest(ControllerTest):
    def setUp(self):
        super().setUp()
        self.repo = self.controller.repo
        self.work = self.repo.create_group("Trabalho", work_min=50)
        self.home = self.repo.create_group("Casa")
        self.task = self.controller.add_task("Relatório", estimate_min=90, group_id=self.work["id"])

    def test_update_fields_and_estimate_clears_with_zero(self):
        self.controller.update_task(self.task["id"], notes="usar o modelo", energy="high",
                                    repeat_rule="monthly:9", scheduled_for="2026-11-12", estimate_min=0)
        row = self.repo.get_task(self.task["id"])
        self.assertEqual((row["notes"], row["energy"], row["repeat_rule"], row["scheduled_for"], row["estimate_min"]),
                         ("usar o modelo", "high", "monthly:9", "2026-11-12", None))
        with self.assertRaises(ValueError):
            self.controller.update_task(self.task["id"], repeat_rule="quinzenal")
        with self.assertRaises(KeyError):
            self.controller.update_task("nao-existe", notes="x")

    def test_group_requiring_estimate_blocks_removing_it(self):
        strict = self.repo.create_group("Rígido", require_estimate=True)
        task = self.controller.add_task("Com previsão", estimate_min=20, group_id=strict["id"])
        with self.assertRaises(ValueError):
            self.controller.update_task(task["id"], estimate_min=0)
        self.assertEqual(self.repo.get_task(task["id"])["estimate_min"], 20)
        loose = self.controller.add_task("Sem previsão", group_id=self.home["id"])
        with self.assertRaises(ValueError):
            self.controller.update_task(loose["id"], group_id=strict["id"])         # mover exige previsão
        self.assertEqual(self.repo.get_task(loose["id"])["group_id"], self.home["id"])
        self.controller.update_task(loose["id"], group_id=strict["id"], estimate_min=15)
        self.assertEqual(self.repo.get_task(loose["id"])["group_id"], strict["id"])

    def test_moving_the_focused_task_updates_timer_duration(self):
        self.controller.focus(self.task["id"])
        self.assertEqual(self.controller.timer.remaining, 50 * 60)
        self.controller.update_task(self.task["id"], group_id=self.home["id"])
        self.assertEqual(self.controller.timer.remaining, 25 * 60)
        self.assertEqual(self.repo.get_task(self.task["id"])["group_id"], self.home["id"])

    def test_estimate_change_rearms_hyperfocus_math(self):
        self.controller.update_task(self.task["id"], estimate_min=1)
        self.controller.focus(self.task["id"])
        self.controller.toggle_timer()
        self.tick(90)
        self.assertTrue(any("Passou do previsto" in n for n in self.notes))
        self.controller.update_task(self.task["id"], estimate_min=10)            # sobe o previsto: sem novo alerta
        before = len(self.notes)
        self.tick(30)
        self.assertEqual(len(self.notes), before)

    def test_update_and_reorder_subtasks(self):
        s1 = self.controller.add_subtask(self.task["id"], "A", 10)
        s2 = self.controller.add_subtask(self.task["id"], "B")
        self.controller.update_subtask(s2["id"], estimate_min=25, title="B2")
        self.controller.update_subtask(s1["id"], estimate_min=0)
        row1, row2 = self.repo.get_subtask(s1["id"]), self.repo.get_subtask(s2["id"])
        self.assertEqual((row1["estimate_min"], row2["estimate_min"], row2["title"]), (None, 25, "B2"))
        self.controller.reorder_subtasks(self.task["id"], [s2["id"], s1["id"]])
        self.assertEqual([s["id"] for s in self.repo.list_subtasks(self.task["id"])], [s2["id"], s1["id"]])

    def test_adjust_real_time(self):
        sub = self.controller.add_subtask(self.task["id"], "A")
        self.controller.adjust_real_time(self.task["id"], 30)
        self.controller.adjust_real_time(self.task["id"], -10, subtask_id=sub["id"])
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 20 * 60)
        self.assertEqual(self.repo.real_seconds_subtask(sub["id"]), 0)
        with self.assertRaises(ValueError):
            self.controller.adjust_real_time(self.task["id"], -21)
        self.controller.adjust_real_time(self.task["id"], 0)                     # sem efeito
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 20 * 60)

    def test_adjust_updates_live_numbers(self):
        self.controller.focus(self.task["id"])
        self.controller.toggle_timer()
        self.tick(60)
        self.controller.adjust_real_time(self.task["id"], 10)
        self.assertEqual(self.controller.tracker.live_real_seconds(self.task["id"]), 60 + 600)

    def test_duplicate_defaults_to_tomorrow(self):
        sub = self.controller.add_subtask(self.task["id"], "Gráficos", 30)
        copy = self.controller.duplicate_task(self.task["id"])
        self.assertEqual((copy["scheduled_for"], copy["title"]), ("2026-11-10", "Relatório"))
        self.assertEqual([s["title"] for s in self.repo.list_subtasks(copy["id"])], ["Gráficos"])
        again = self.controller.duplicate_task(self.task["id"], day=None)
        self.assertIsNone(again["scheduled_for"])
        self.assertEqual(sub["title"], "Gráficos")

    def test_task_detail(self):
        s1 = self.controller.add_subtask(self.task["id"], "Números", 25)
        self.controller.add_subtask(self.task["id"], "Gráficos", 30)
        self.controller.focus(self.task["id"], s1["id"])
        self.controller.toggle_timer()
        self.tick(50 * 60)                                                       # o grupo usa foco de 50 min
        self.controller.skip_phase()                                             # conclui o 1º pomodoro
        self.controller.tracker.add_distraction("ligar para o banco")
        self.controller.adjust_real_time(self.task["id"], 5)
        detail = self.controller.task_detail(self.task["id"])
        self.assertEqual(detail["group"]["name"], "Trabalho")
        self.assertEqual((detail["real_seconds"], detail["pomodoros"], detail["estimate_sum"]), (3300, 1, 55))
        self.assertEqual([(s["title"], s["real_seconds"], s["done"]) for s in detail["subtasks"]],
                         [("Números", 3000, False), ("Gráficos", 0, False)])
        kinds = [(s["kind"], s["subtask_title"]) for s in detail["sessions"]]
        self.assertEqual(kinds, [("work", "Números"), ("manual", None)])
        self.assertEqual([d["text"] for d in detail["distractions"]], ["ligar para o banco"])
        self.assertIsNone(self.controller.task_detail("nao-existe"))


class CreateTaskFullTest(ControllerTest):
    def test_creates_everything_at_once(self):
        group = self.controller.repo.create_group("Trabalho")
        task = self.controller.create_task_full(
            "Preparar apresentação", group_id=group["id"], day="2026-11-12", estimate_min=80,
            repeat_rule="weekly:3", energy="high", notes="slides do modelo",
            subtasks=[("Definir tópicos", 20), (" Criar slides ", 40), ("Ensaiar", None)])
        row = self.controller.repo.get_task(task["id"])
        self.assertEqual((row["scheduled_for"], row["estimate_min"], row["repeat_rule"], row["energy"], row["notes"]),
                         ("2026-11-12", 80, "weekly:3", "high", "slides do modelo"))
        subs = self.controller.repo.list_subtasks(task["id"])
        self.assertEqual([(s["title"], s["estimate_min"]) for s in subs],
                         [("Definir tópicos", 20), ("Criar slides", 40), ("Ensaiar", None)])
        self.assertIn("data", self.events)

    def test_default_day_is_today_and_none_means_no_date(self):
        self.assertEqual(self.controller.create_task_full("Hoje")["scheduled_for"], "2026-11-09")
        self.assertIsNone(self.controller.create_task_full("Sem data", day=None)["scheduled_for"])

    def test_invalid_input_leaves_nothing_behind(self):
        with self.assertRaises(ValueError):
            self.controller.create_task_full("A", subtasks=[("ok", 5), ("  ", 5)])
        with self.assertRaises(ValueError):
            self.controller.create_task_full("   ")
        with self.assertRaises(ValueError):
            self.controller.create_task_full("B", repeat_rule="quinzenal")
        strict = self.controller.repo.create_group("Rígido", require_estimate=True)
        with self.assertRaises(ValueError):
            self.controller.create_task_full("C", group_id=strict["id"])
        self.assertEqual(self.controller.repo.list_tasks(), [])

    def test_focus_option_starts_the_timer(self):
        task = self.controller.create_task_full("Já começar", focus=True)
        self.assertEqual(self.controller.tracker.active_task_id, task["id"])
        self.assertTrue(self.controller.timer.running)

    def test_focus_and_start(self):
        task = self.controller.add_task("A")
        self.controller.focus_and_start(task["id"])
        self.assertTrue(self.controller.timer.running)
        self.controller.focus_and_start(task["id"])                              # já rodando: não pausa
        self.assertTrue(self.controller.timer.running)


class EstimatorHookTest(ControllerTest):
    class FakeEstimator:
        def suggest_estimate(self, repo, title, group_id, user_estimate_min):
            return {"minutes": 80, "note": f"para {title}"} if user_estimate_min == 45 else None

        def suggest_subtasks(self, repo, title, group_id):
            return [("Definir tópicos", 20), ("Criar slides", 40)]

    def test_without_estimator(self):
        self.assertIsNone(self.controller.suggest_estimate("Qualquer", None, 45))
        self.assertEqual(self.controller.suggest_subtasks("Qualquer"), [])

    def test_with_estimator(self):
        self.controller.estimator = self.FakeEstimator()
        self.assertEqual(self.controller.suggest_estimate("Apresentação", None, 45),
                         {"minutes": 80, "note": "para Apresentação"})
        self.assertIsNone(self.controller.suggest_estimate("Apresentação", None, 30))
        self.assertIsNone(self.controller.suggest_estimate("   ", None, 45))
        self.assertEqual(len(self.controller.suggest_subtasks("Apresentação")), 2)
        self.assertEqual(self.controller.suggest_subtasks(""), [])


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
