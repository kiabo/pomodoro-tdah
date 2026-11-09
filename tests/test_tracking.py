import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pomodoro import db, settings as settings_mod
from pomodoro.repository import Repository
from pomodoro.timer import Phase, PomodoroTimer
from pomodoro.tracking import Tracker

from .test_repository import FakeClock
from .test_timer import FakeScheduler, make_settings


class TrackingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.group = self.repo.create_group("Trabalho")
        self.task = self.repo.create_task(self.group["id"], "Escrever relatório", estimate_min=90)
        self.sub = self.repo.add_subtask(self.task["id"], "Montar gráficos", 30)
        self.alerts = []
        self.make_timer()

    def make_timer(self, **overrides):
        opts = dict(work_min=25, short_break_min=5, long_break_min=15, cycles_before_long_break=4,
                    count_overtime=True, warn_before_end_min=0)
        opts.update(overrides)
        self.settings = make_settings(**opts)
        self.scheduler = FakeScheduler()
        self.timer = PomodoroTimer(self.settings, lambda: None, lambda auto: None,
                                   scheduler=self.scheduler)
        self.tracker = Tracker(self.repo, self.timer, lambda: self.settings,
                               on_alert=lambda name, **d: self.alerts.append((name, d)))
        self.timer.add_listener(self.tracker.handle)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def run_seconds(self, n):
        for _ in range(n):
            self.timer.tick()

    def sessions(self, kind=None):
        rows = self.repo.list_sessions()
        return [r for r in rows if kind is None or r["kind"] == kind]


class SessionLifecycleTest(TrackingTest):
    def test_full_pomodoro_is_one_completed_session(self):
        self.tracker.set_active(self.task["id"], self.sub["id"])
        self.timer.start()
        self.run_seconds(25 * 60 + 30)             # estoura 30 s em tempo extra
        self.timer.skip()                           # conclui o foco
        work = self.sessions("work")
        self.assertEqual(len(work), 1)
        s = work[0]
        self.assertEqual((s["seconds"], s["completed_phase"], s["interrupted"]), (1530, 1, 0))
        self.assertEqual((s["task_id"], s["subtask_id"]), (self.task["id"], self.sub["id"]))
        self.assertIsNotNone(s["ended_at"])
        self.assertEqual(self.repo.count_work_sessions(), 1)
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 1530)
        self.assertEqual(self.repo.real_seconds_subtask(self.sub["id"]), 1530)

    def test_break_session_recorded_but_not_real_time(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(25 * 60 + 1)
        self.timer.skip()                           # foco concluído; pausa começa (continua rodando)
        self.run_seconds(5 * 60)                    # pausa termina sozinha
        kinds = [(s["kind"], s["seconds"], s["task_id"]) for s in self.sessions()]
        self.assertEqual(kinds, [("work", 1501, self.task["id"]), ("short_break", 300, None)])
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 1501)

    def test_pause_keeps_the_same_session(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(100)
        self.timer.pause()
        self.clock.advance(minutes=10)              # tempo parado não conta
        self.timer.start()
        self.run_seconds(50)
        self.timer.skip()
        work = self.sessions("work")
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["seconds"], 150)
        self.assertEqual(work[0]["interrupted"], 1)   # cortado antes do zero

    def test_skip_before_zero_is_interrupted_and_not_a_pomodoro(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(300)
        self.timer.skip()
        s = self.sessions("work")[0]
        self.assertEqual((s["seconds"], s["interrupted"], s["completed_phase"]), (300, 1, 0))
        self.assertEqual(self.repo.count_work_sessions(), 0)
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 300)   # o tempo trabalhado conta

    def test_reset_while_paused_closes_session(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(120)
        self.timer.pause()
        self.timer.reset_phase()
        s = self.sessions("work")[0]
        self.assertEqual((s["seconds"], s["interrupted"]), (120, 1))
        self.assertIsNone(self.tracker.session_id)

    def test_empty_sessions_are_not_kept(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.timer.pause()
        self.timer.skip()
        self.assertEqual(self.sessions(), [])

    def test_free_focus_without_task(self):
        self.timer.start()
        self.run_seconds(60)
        self.timer.skip()
        s = self.sessions("work")[0]
        self.assertEqual((s["task_id"], s["seconds"]), (None, 60))


class SwitchingTaskTest(TrackingTest):
    def test_switching_splits_the_session(self):
        other = self.repo.create_task(self.group["id"], "Lavar roupa")
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(200)
        self.tracker.set_active(other["id"])
        self.run_seconds(100)
        self.timer.skip()
        work = self.sessions("work")
        self.assertEqual([(s["task_id"], s["seconds"], s["interrupted"]) for s in work],
                         [(self.task["id"], 200, 0), (other["id"], 100, 1)])
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 200)
        self.assertEqual(self.repo.real_seconds(other["id"]), 100)

    def test_switching_at_zero_seconds_leaves_no_trace(self):
        other = self.repo.create_task(self.group["id"], "Outra")
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.tracker.set_active(other["id"])
        self.run_seconds(10)
        self.timer.skip()
        self.assertEqual([s["task_id"] for s in self.sessions("work")], [other["id"]])

    def test_switching_while_paused_starts_new_session_on_resume(self):
        other = self.repo.create_task(self.group["id"], "Outra")
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(60)
        self.timer.pause()
        self.tracker.set_active(other["id"])
        self.timer.start()
        self.run_seconds(30)
        self.timer.pause()
        self.assertEqual([(s["task_id"], s["seconds"]) for s in self.sessions("work")],
                         [(self.task["id"], 60), (other["id"], 30)])

    def test_switching_during_a_break_keeps_the_break(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(25 * 60 + 1)
        self.timer.skip()
        break_session = self.tracker.session_id
        other = self.repo.create_task(self.group["id"], "Outra")
        self.tracker.set_active(other["id"])
        self.assertEqual(self.tracker.session_id, break_session)

    def test_subtask_resolves_task_and_validates(self):
        self.tracker.set_active(None, self.sub["id"])
        self.assertEqual(self.tracker.active_task_id, self.task["id"])
        other = self.repo.create_task(self.group["id"], "Outra")
        with self.assertRaises(ValueError):
            self.tracker.set_active(other["id"], self.sub["id"])
        with self.assertRaises(KeyError):
            self.tracker.set_active("nao-existe")
        with self.assertRaises(KeyError):
            self.tracker.set_active(None, "nao-existe")

    def test_group_durations_applied_to_timer(self):
        casa = self.repo.create_group("Casa", work_min=50, short_break_min=10)
        chore = self.repo.create_task(casa["id"], "Lavar roupa")
        self.tracker.set_active(chore["id"])
        self.assertEqual(self.timer.remaining, 50 * 60)
        self.tracker.set_active(self.task["id"])
        self.assertEqual(self.timer.remaining, 25 * 60)
        self.tracker.set_active(chore["id"])
        self.tracker.set_active(None)
        self.assertEqual(self.timer.remaining, 25 * 60)


class CrashSafetyTest(TrackingTest):
    def test_checkpoint_every_30_seconds(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(29)
        self.assertEqual(self.repo.get_session(self.tracker.session_id)["seconds"], 0)
        self.run_seconds(1)
        row = self.repo.get_session(self.tracker.session_id)
        self.assertEqual((row["seconds"], row["ended_at"]), (30, None))
        self.run_seconds(10)
        self.timer.pause()
        self.assertEqual(self.repo.get_session(self.tracker.session_id)["seconds"], 40)

    def test_recover_orphans_after_crash(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(95)                        # último checkpoint: 90 s; o app "cai" aqui
        crashed = self.tracker.session_id
        self.make_timer()                           # novo processo
        self.assertEqual(self.tracker.recover_orphans(), 1)
        row = self.repo.get_session(crashed)
        self.assertEqual((row["seconds"], row["interrupted"], row["completed_phase"]), (90, 1, 0))
        self.assertEqual(row["ended_at"], "2026-11-09T14:01:30")
        self.assertEqual(self.repo.real_seconds(self.task["id"]), 90)

    def test_recover_drops_empty_orphans(self):
        self.repo.start_session("work", task_id=self.task["id"])
        self.assertEqual(self.tracker.recover_orphans(), 1)
        self.assertEqual(self.sessions(), [])

    def test_shutdown_saves_interrupted_session(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(45)
        self.tracker.shutdown()
        s = self.sessions("work")[0]
        self.assertEqual((s["seconds"], s["interrupted"]), (45, 1))
        self.assertEqual(self.repo.open_sessions(), [])


class LiveTimeAndHyperfocusTest(TrackingTest):
    def test_live_real_seconds_includes_running_session(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(20)
        self.assertEqual(self.tracker.live_real_seconds(self.task["id"]), 20)
        self.run_seconds(40)                        # checkpoints não duplicam a contagem
        self.assertEqual(self.tracker.live_real_seconds(self.task["id"]), 60)
        self.timer.skip()
        self.assertEqual(self.tracker.live_real_seconds(self.task["id"]), 60)
        other = self.repo.create_task(self.group["id"], "Outra")
        self.assertEqual(self.tracker.live_real_seconds(other["id"]), 0)

    def test_live_real_seconds_of_the_active_subtask(self):
        self.repo.add_manual_adjustment(self.task["id"], 300, subtask_id=self.sub["id"])
        self.tracker.set_active(self.task["id"], self.sub["id"])
        self.timer.start()
        self.run_seconds(70)                        # passa por um checkpoint (30 s e 60 s)
        self.assertEqual(self.tracker.live_real_seconds_subtask(self.sub["id"]), 370)
        other = self.repo.add_subtask(self.task["id"], "Outra")
        self.assertEqual(self.tracker.live_real_seconds_subtask(other["id"]), 0)

    def test_live_includes_previous_sessions(self):
        self.repo.add_manual_adjustment(self.task["id"], 600)
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(45)
        self.assertEqual(self.tracker.live_real_seconds(self.task["id"]), 645)

    def test_hyperfocus_alerts_once_at_150_percent(self):
        self.repo.update_task(self.task["id"], estimate_min=1)
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(89)
        self.assertEqual(self.alerts, [])
        self.run_seconds(1)
        self.assertEqual(len(self.alerts), 1)
        name, data = self.alerts[0]
        self.assertEqual(name, "hyperfocus")
        self.assertEqual((data["task_id"], data["real_seconds"], data["estimate_seconds"]),
                         (self.task["id"], 90, 60))
        self.run_seconds(120)
        self.assertEqual(len(self.alerts), 1)

    def test_alert_counts_time_from_previous_sessions(self):
        self.repo.update_task(self.task["id"], estimate_min=10)
        self.repo.add_manual_adjustment(self.task["id"], 14 * 60)
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(59)
        self.assertEqual(self.alerts, [])
        self.run_seconds(1)                          # 14 min + 60 s = 15 min = 150% de 10
        self.assertEqual(len(self.alerts), 1)

    def test_raising_the_estimate_rearms_the_alert(self):
        self.repo.update_task(self.task["id"], estimate_min=1)
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(90)
        self.repo.update_task(self.task["id"], estimate_min=2)   # +1 min no previsto
        self.tracker.invalidate()
        self.run_seconds(89)                         # 179 s < 180 s
        self.assertEqual(len(self.alerts), 1)
        self.run_seconds(1)
        self.assertEqual(len(self.alerts), 2)

    def test_threshold_setting_and_toggle(self):
        self.repo.update_task(self.task["id"], estimate_min=1)
        self.settings["hyperfocus_threshold_pct"] = 200
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(119)
        self.assertEqual(self.alerts, [])
        self.settings["hyperfocus_alert"] = False
        self.run_seconds(10)
        self.assertEqual(self.alerts, [])

    def test_no_alert_without_estimate_or_task_or_in_break(self):
        self.repo.update_task(self.task["id"], estimate_min=None)
        self.repo.delete_subtask(self.sub["id"])
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(25 * 60 + 600)
        self.assertEqual(self.alerts, [])
        self.timer.skip()
        self.run_seconds(300)
        self.assertEqual(self.alerts, [])

    def test_estimate_falls_back_to_subtask_sum(self):
        self.repo.update_task(self.task["id"], estimate_min=None)   # subtarefa prevê 30 min
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(25 * 60 + 1)                # 25 min: abaixo de 45 min (150% de 30)
        self.assertEqual(self.alerts, [])
        self.run_seconds(20 * 60)
        self.assertEqual(len(self.alerts), 1)


class DistractionTest(TrackingTest):
    def test_distraction_links_session_and_task(self):
        self.tracker.set_active(self.task["id"])
        self.timer.start()
        self.run_seconds(10)
        did = self.tracker.add_distraction("ligar para o banco")
        row = [d for d in self.repo.list_distractions() if d["id"] == did][0]
        self.assertEqual((row["session_id"], row["task_id"]), (self.tracker.session_id, self.task["id"]))

    def test_distraction_without_session(self):
        did = self.tracker.add_distraction("comprar café")
        row = self.repo.list_distractions()[0]
        self.assertEqual((row["id"], row["session_id"], row["task_id"]), (did, None, None))


if __name__ == "__main__":
    unittest.main()
