import unittest
from datetime import datetime

from pomodoro import settings as settings_mod
from pomodoro.timer import Phase, PomodoroTimer


class FakeScheduler:
    """Guarda os callbacks em vez de usar o GLib; fire() simula a passagem de 1 segundo."""

    def __init__(self):
        self.callbacks = {}
        self._next_id = 1

    def add(self, callback):
        source_id = self._next_id
        self._next_id += 1
        self.callbacks[source_id] = callback
        return source_id

    def remove(self, source_id):
        del self.callbacks[source_id]

    def fire(self):
        for source_id, callback in list(self.callbacks.items()):
            if not callback():
                self.callbacks.pop(source_id, None)


def make_settings(**overrides):
    s = settings_mod.sanitize({})
    s.update(overrides)
    return s


class TimerTest(unittest.TestCase):
    def make(self, **overrides):
        self.scheduler = FakeScheduler()
        self.events = []
        self.ticks = 0
        self.phase_changes = []
        defaults = dict(work_min=1, short_break_min=1, long_break_min=2,
                        cycles_before_long_break=2, count_overtime=False, warn_before_end_min=0)
        defaults.update(overrides)
        timer = PomodoroTimer(
            make_settings(**defaults), self._on_tick, self.phase_changes.append,
            on_event=lambda name, **data: self.events.append((name, data)),
            scheduler=self.scheduler,
        )
        return timer

    def _on_tick(self):
        self.ticks += 1

    def names(self):
        return [name for name, _ in self.events]

    def data(self, name):
        return [d for n, d in self.events if n == name]

    @staticmethod
    def run_seconds(timer, n):
        for _ in range(n):
            timer.tick()


class PhaseSequenceTest(TimerTest):
    def test_full_cycle_with_long_break(self):
        t = self.make(auto_start_work=True)
        t.start()
        seen = [(t.phase, t.cycle)]
        for _ in range(7):
            self.run_seconds(t, t.remaining)
            seen.append((t.phase, t.cycle))
        self.assertEqual(seen, [
            (Phase.WORK, 1), (Phase.SHORT_BREAK, 1), (Phase.WORK, 2), (Phase.LONG_BREAK, 1),
            (Phase.WORK, 1), (Phase.SHORT_BREAK, 1), (Phase.WORK, 2), (Phase.LONG_BREAK, 1),
        ])
        self.assertTrue(t.running)

    def test_durations(self):
        t = self.make()
        self.assertEqual(t.remaining, 60)
        t.skip()  # foco -> pausa curta
        self.assertEqual(t.remaining, 60)
        t.skip()
        t.skip()  # foco 2 -> pausa longa
        self.assertEqual((t.phase, t.remaining), (Phase.LONG_BREAK, 120))

    def test_auto_start_defaults_breaks_yes_work_no(self):
        t = self.make()
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.SHORT_BREAK)
        self.assertTrue(t.running)                      # pausa começa sozinha
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.WORK)
        self.assertFalse(t.running)                     # foco espera o usuário
        self.assertEqual(len(self.scheduler.callbacks), 0)

    def test_auto_start_breaks_off(self):
        t = self.make(auto_start_breaks=False)
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.SHORT_BREAK)
        self.assertFalse(t.running)
        self.assertEqual(self.phase_changes, [True])
        self.assertEqual(len(self.scheduler.callbacks), 0)

    def test_manual_skip_keeps_running_state(self):
        t = self.make()
        t.skip()                                        # parado
        self.assertFalse(t.running)
        t.start()
        t.skip()                                        # rodando
        self.assertTrue(t.running)
        self.assertEqual(self.phase_changes, [False, False])

    def test_no_double_ticking_after_pause_inside_tick(self):
        t = self.make(auto_start_breaks=False)
        t.start()
        self.run_seconds(t, 59)
        self.scheduler.fire()                           # 60º segundo pelo agendador: pausa dentro do tick
        self.assertFalse(t.running)
        self.assertEqual(len(self.scheduler.callbacks), 0)
        t.start()
        self.assertEqual(len(self.scheduler.callbacks), 1)
        before = t.remaining
        self.scheduler.fire()
        self.assertEqual(t.remaining, before - 1)

    def test_pause_removes_source(self):
        t = self.make()
        t.start()
        self.assertEqual(len(self.scheduler.callbacks), 1)
        t.pause()
        self.assertEqual(len(self.scheduler.callbacks), 0)
        t.start()
        t.start()                                       # idempotente
        self.assertEqual(len(self.scheduler.callbacks), 1)


class OvertimeAndWarningTest(TimerTest):
    def test_warning_fires_once_at_threshold(self):
        t = self.make(work_min=5, warn_before_end_min=2)
        t.start()
        self.run_seconds(t, 5 * 60 - 1)
        self.assertEqual(self.data("warning"), [{"remaining": 120}])
        self.assertEqual(t.remaining, 1)

    def test_no_warning_when_disabled_or_too_long(self):
        t = self.make(work_min=5, warn_before_end_min=0)
        t.start()
        self.run_seconds(t, 200)
        self.assertEqual(self.data("warning"), [])
        t2 = self.make(work_min=1, warn_before_end_min=2)   # aviso maior que o foco
        t2.start()
        self.run_seconds(t2, 59)
        self.assertEqual(self.data("warning"), [])

    def test_no_warning_during_breaks(self):
        t = self.make(work_min=5, short_break_min=5, warn_before_end_min=2)
        t.skip()
        t.start()
        self.run_seconds(t, 200)
        self.assertEqual(self.data("warning"), [])

    def test_overtime_keeps_counting(self):
        t = self.make(count_overtime=True)
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.WORK)
        self.assertTrue(t.in_overtime)
        self.assertEqual(self.data("overtime"), [{}])
        self.run_seconds(t, 90)
        self.assertEqual(t.remaining, -90)
        self.assertEqual(t.overtime_seconds, 90)
        self.assertEqual(self.data("overtime"), [{}])   # só avisa uma vez
        self.assertEqual(self.phase_changes, [])

    def test_skip_during_overtime_counts_as_completed(self):
        t = self.make(count_overtime=True)
        t.start()
        self.run_seconds(t, 100)
        t.skip()
        ended = self.data("phase_ended")[0]
        self.assertTrue(ended["completed"])
        self.assertEqual(ended["seconds"], 100)
        self.assertEqual(ended["overtime_seconds"], 40)
        self.assertEqual(ended["reason"], "skip")
        self.assertFalse(t.in_overtime)
        self.assertEqual(t.phase, Phase.SHORT_BREAK)

    def test_overtime_off_advances_at_zero(self):
        t = self.make(count_overtime=False)
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.SHORT_BREAK)
        self.assertEqual(self.data("overtime"), [])
        self.assertTrue(self.data("phase_ended")[0]["auto"])

    def test_breaks_never_go_overtime(self):
        t = self.make(count_overtime=True)
        t.skip()
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(t.phase, Phase.WORK)
        self.assertEqual(self.data("overtime"), [])


class PhaseEventsTest(TimerTest):
    def test_skip_before_zero_is_not_completed(self):
        t = self.make()
        t.start()
        self.run_seconds(t, 20)
        t.skip()
        ended = self.data("phase_ended")[0]
        self.assertFalse(ended["completed"])
        self.assertEqual((ended["seconds"], ended["auto"], ended["reason"]), (20, False, "skip"))

    def test_phase_started_reflects_final_running_state(self):
        t = self.make(auto_start_breaks=False)
        states = []
        t.add_listener(lambda name, **d: states.append(t.running) if name == "phase_started" else None)
        t.start()
        self.run_seconds(t, 60)
        self.assertEqual(states, [False])

    def test_reset_phase_discards_progress_and_pauses(self):
        t = self.make()
        t.start()
        self.run_seconds(t, 30)
        t.reset_phase()
        self.assertFalse(t.running)
        self.assertEqual((t.remaining, t.phase_elapsed), (60, 0))
        ended = self.data("phase_ended")[0]
        self.assertEqual((ended["reason"], ended["completed"], ended["seconds"]), ("reset", False, 30))
        self.assertIn("paused", self.names())
        self.assertEqual(len(self.scheduler.callbacks), 0)

    def test_restart_all(self):
        t = self.make()
        t.skip()
        t.skip()
        t.start()
        self.run_seconds(t, 10)
        t.restart_all()
        self.assertEqual((t.phase, t.cycle, t.remaining), (Phase.WORK, 1, 60))
        self.assertFalse(t.running)
        self.assertEqual(self.data("phase_ended")[-1]["reason"], "restart")

    def test_broken_listener_does_not_stop_the_clock(self):
        t = self.make()

        def boom(name, **data):
            raise RuntimeError("defeito")

        t.add_listener(boom)
        with self.assertLogs("pomodoro.timer", level="ERROR"):
            t.start()
            t.tick()
        self.assertEqual(t.remaining, 59)


class OverridesAndSettingsTest(TimerTest):
    def test_group_overrides_when_pristine(self):
        t = self.make(work_min=25)
        t.set_overrides(work_min=50, short_break_min=10)
        self.assertEqual(t.remaining, 50 * 60)
        t.skip()
        self.assertEqual(t.remaining, 10 * 60)
        t.set_overrides()
        self.assertEqual(t.remaining, 60)

    def test_overrides_do_not_touch_running_phase(self):
        t = self.make(work_min=25)
        t.start()
        self.run_seconds(t, 5)
        t.set_overrides(work_min=50)
        self.assertEqual(t.remaining, 25 * 60 - 5)
        t.skip()          # a pausa curta não tem override
        t.skip()          # próximo foco já usa o override
        self.assertEqual(t.remaining, 50 * 60)

    def test_update_settings_only_resets_untouched_phase(self):
        t = self.make(work_min=25)
        t.update_settings(make_settings(work_min=30, count_overtime=False))
        self.assertEqual(t.remaining, 30 * 60)
        t.start()
        self.run_seconds(t, 10)
        t.update_settings(make_settings(work_min=45, count_overtime=False))
        self.assertEqual(t.remaining, 30 * 60 - 10)     # em andamento: preserva o progresso
        t.pause()
        t.update_settings(make_settings(work_min=45, count_overtime=False))
        self.assertEqual(t.remaining, 30 * 60 - 10)     # pausada no meio: também preserva


class NextIntervalsTest(TimerTest):
    NOW = datetime(2026, 11, 9, 15, 0, 0)

    def test_schedule_from_current_state(self):
        t = self.make(work_min=25, short_break_min=5, long_break_min=15, cycles_before_long_break=2)
        t.start()
        self.run_seconds(t, 10 * 60)                    # faltam 15 min
        items = t.next_intervals(now=self.NOW, count=4)
        self.assertEqual([i["phase"] for i in items],
                         [Phase.SHORT_BREAK, Phase.WORK, Phase.LONG_BREAK, Phase.WORK])
        self.assertEqual(items[0]["start"], datetime(2026, 11, 9, 15, 15))
        self.assertEqual(items[0]["end"], datetime(2026, 11, 9, 15, 20))
        self.assertEqual(items[1]["start"], datetime(2026, 11, 9, 15, 20))
        self.assertEqual(items[2]["start"], datetime(2026, 11, 9, 15, 45))
        self.assertEqual(items[2]["seconds"], 15 * 60)
        self.assertEqual(items[0]["label"], "Pausa curta")

    def test_does_not_change_state(self):
        t = self.make()
        t.next_intervals(now=self.NOW, count=5)
        self.assertEqual((t.phase, t.cycle, t.remaining), (Phase.WORK, 1, 60))

    def test_overtime_means_next_phase_starts_now(self):
        t = self.make(count_overtime=True)
        t.start()
        self.run_seconds(t, 90)
        first = t.next_intervals(now=self.NOW, count=1)[0]
        self.assertEqual(first["start"], self.NOW)

    def test_uses_group_overrides(self):
        t = self.make(work_min=25, short_break_min=5)
        t.set_overrides(work_min=50, short_break_min=10)
        items = t.next_intervals(now=self.NOW, count=2)
        self.assertEqual(items[0]["seconds"], 10 * 60)
        self.assertEqual(items[0]["start"], datetime(2026, 11, 9, 15, 50))


if __name__ == "__main__":
    unittest.main()
