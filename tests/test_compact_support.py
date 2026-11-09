import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pomodoro import db
from pomodoro.repository import Repository
from pomodoro.timer import Phase, PomodoroTimer
from pomodoro.today import build_today, next_focus, next_focus_item
from pomodoro.ui.compact_geometry import default_position, valid_position
from pomodoro.ui.format import compact_eyebrow, next_interval_hint

from .test_repository import FakeClock
from .test_timer import FakeScheduler, make_settings


class CompactTextTest(unittest.TestCase):
    def test_eyebrow(self):
        self.assertEqual(compact_eyebrow(Phase.WORK, True, True, 3, 4), "FOCO · 3 DE 4")
        self.assertEqual(compact_eyebrow(Phase.WORK, False, True, 3, 4), "PAUSADO · 3 DE 4")
        self.assertEqual(compact_eyebrow(Phase.WORK, False, False, 1, 4), "PRONTO · 1 DE 4")
        self.assertEqual(compact_eyebrow(Phase.WORK, True, True, 2, 4, overtime=True), "TEMPO EXTRA · 2 DE 4")
        self.assertEqual(compact_eyebrow(Phase.SHORT_BREAK, True, True, 1, 4), "PAUSA CURTA")
        self.assertEqual(compact_eyebrow(Phase.LONG_BREAK, False, True, 1, 4), "PAUSA LONGA · PAUSADA")

    def test_next_interval_hint(self):
        item = {"label": "Pausa curta", "seconds": 300, "start": datetime(2026, 11, 9, 15, 48)}
        self.assertEqual(next_interval_hint(item), "Próximo: pausa curta de 5 min às 15:48")


class GeometryTest(unittest.TestCase):
    MONITOR = (0, 0, 1920, 1080)

    def test_default_is_top_right(self):
        self.assertEqual(default_position(self.MONITOR, (380, 160)), (1920 - 380 - 24, 24))
        self.assertEqual(default_position((1920, 0, 1280, 1024), (380, 160)), (1920 + 1280 - 380 - 24, 24))

    def test_saved_position_kept_when_visible(self):
        self.assertEqual(valid_position((100, 200), [self.MONITOR], (380, 160)), (100, 200))
        self.assertEqual(valid_position((1900, 1060), [self.MONITOR], (380, 160)), (1516, 24))      # só 20 px aparecem
        self.assertEqual(valid_position((-300, 50), [self.MONITOR], (380, 160)), (-300, 50))         # 80 px aparecem

    def test_offscreen_or_missing_falls_back(self):
        self.assertEqual(valid_position((4000, 100), [self.MONITOR], (380, 160)), (1516, 24))
        self.assertEqual(valid_position(None, [self.MONITOR], (380, 160)), (1516, 24))
        self.assertEqual(valid_position([5], [self.MONITOR], (380, 160)), (1516, 24))
        two = [self.MONITOR, (1920, 0, 1280, 1024)]
        self.assertEqual(valid_position((2500, 100), two, (380, 160)), (2500, 100))                 # no 2º monitor
        self.assertEqual(valid_position((2500, 100), [self.MONITOR], (380, 160)), (1516, 24))        # monitor sumiu
        self.assertEqual(valid_position((10, 10), [], (380, 160)), (10, 10))


class NextFocusItemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.conn = db.open_database(Path(self._tmp.name), clock())
        self.repo = Repository(self.conn, now=clock)
        group = self.repo.create_group("Trabalho")
        self.t1 = self.repo.create_task(group["id"], "Relatório", estimate_min=90, scheduled_for="2026-11-09")
        self.s1 = self.repo.add_subtask(self.t1["id"], "Números", 25)
        self.s2 = self.repo.add_subtask(self.t1["id"], "Revisar texto", 35)
        self.t2 = self.repo.create_task(group["id"], "E-mails", estimate_min=20, scheduled_for="2026-11-09")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_item_has_title_and_estimate(self):
        view = build_today(self.repo, "2026-11-09")
        self.assertEqual(next_focus_item(view, self.t1["id"], self.s1["id"]), ("Revisar texto", 35))
        self.repo.set_subtask_done(self.s2["id"])
        self.repo.set_subtask_done(self.s1["id"])
        view = build_today(self.repo, "2026-11-09")
        self.assertEqual(next_focus_item(view, self.t1["id"], None), ("E-mails", 20))
        self.repo.set_task_status(self.t2["id"], "done")
        self.assertEqual(next_focus_item(build_today(self.repo, "2026-11-09"), None, None), ("Relatório", 90))
        self.repo.set_task_status(self.t1["id"], "done")
        self.assertEqual(next_focus_item(build_today(self.repo, "2026-11-09"), None, None), (None, None))

    def test_next_focus_is_the_title_only(self):
        view = build_today(self.repo, "2026-11-09")
        self.assertEqual(next_focus(view, self.t1["id"], self.s1["id"]), "Revisar texto")


class ExtendTest(unittest.TestCase):
    def make(self):
        self.ticks = 0
        return PomodoroTimer(make_settings(work_min=1, short_break_min=1), lambda: setattr(self, "ticks", self.ticks + 1),
                             lambda auto: None, scheduler=FakeScheduler())

    def test_extend_adds_and_never_reaches_zero_by_subtracting(self):
        timer = self.make()
        timer.extend(60)
        self.assertEqual(timer.remaining, 120)
        timer.extend(-30)
        self.assertEqual(timer.remaining, 90)
        timer.extend(-1000)
        self.assertEqual(timer.remaining, 1)
        before = self.ticks
        timer.extend(0)
        self.assertEqual((timer.remaining, self.ticks), (1, before))

    def test_extend_a_running_break_delays_its_end(self):
        timer = self.make()
        timer.skip()
        timer.start()
        timer.extend(60)
        for _ in range(60):
            timer.tick()
        self.assertEqual(timer.phase, Phase.SHORT_BREAK)
        for _ in range(60):
            timer.tick()
        self.assertEqual(timer.phase, Phase.WORK)


if __name__ == "__main__":
    unittest.main()
