import unittest
from datetime import date

from pomodoro.ai import analysis

from .ai_support import Seed


class PeriodTest(unittest.TestCase):
    def test_bounds(self):
        today = date(2026, 11, 9)       # segunda
        self.assertEqual(analysis.period_bounds("day", today), (today, today))
        self.assertEqual(analysis.period_bounds("week", today), (date(2026, 11, 9), date(2026, 11, 15)))
        self.assertEqual(analysis.period_bounds("month", today), (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual(analysis.period_bounds("week", "2026-11-15")[0], date(2026, 11, 9))
        with self.assertRaises(ValueError):
            analysis.period_bounds("ano", today)


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.seed = Seed()
        s = self.seed
        s.done(s.work, "Escrever relatório A", 30, 45, day="2026-11-03", hour=9)
        s.done(s.work, "Escrever relatório B", 40, 60, day="2026-11-04", hour=10, subtasks=[("x", 10)])
        s.done(s.work, "Escrever relatório C", 20, 30, day="2026-11-05", hour=9, interrupted=1)
        s.done(s.home, "Lavar roupa", 30, 30, day="2026-11-06", hour=15)
        s.done(s.home, "Lavar louça", 20, 20, day="2026-11-09", hour=15)
        s.todo(s.work, "Escrever relatório D", 40)

    def tearDown(self):
        self.seed.close()

    def test_week_kpis_and_chart(self):
        a = analysis.build_analysis(self.seed.repo, "2026-11-09", "week")
        self.assertEqual((a.start, a.end), ("2026-11-09", "2026-11-15"))
        self.assertEqual((a.done_count, a.measured_count), (1, 1))
        self.assertEqual(a.accuracy, 1.0)
        self.assertEqual(len(a.days), 7)
        self.assertEqual([d.label for d in a.days][:2], ["seg", "ter"])
        self.assertEqual(a.days[0].planned_min, 20)

    def test_month_has_every_day_and_all_samples(self):
        a = analysis.build_analysis(self.seed.repo, "2026-11-09", "month")
        self.assertEqual((a.done_count, len(a.days)), (5, 30))
        self.assertEqual(a.days[2].label, "3")
        self.assertAlmostEqual(a.mean_deviation_min, (15 + 20 + 12) / 5, places=1)
        names = [g.name for g in a.groups]
        self.assertEqual(names[0], "Casa")                       # mais precisa primeiro
        self.assertAlmostEqual(a.groups[1].ratio, 1.533, places=2)

    def test_day_period_charts_the_week(self):
        a = analysis.build_analysis(self.seed.repo, "2026-11-09", "day")
        self.assertEqual((a.done_count, len(a.days)), (1, 7))

    def test_insights_and_predictions(self):
        a = analysis.build_analysis(self.seed.repo, "2026-11-09", "month")
        self.assertTrue(any("Tarefas com" in i and "a mais" in i for i in a.insights), a.insights)
        self.assertEqual(len(a.predictions), 1)
        p = a.predictions[0]
        self.assertEqual((p.title, p.user_min, p.ai_min), ("Escrever relatório D", 40, 60))
        self.assertEqual(p.group_name, "Trabalho")

    def test_empty_history(self):
        fresh = Seed()
        try:
            a = analysis.build_analysis(fresh.repo, "2026-11-09", "week")
            self.assertFalse(a.has_data)
            self.assertEqual((a.accuracy, a.insights, a.predictions), (None, [], []))
        finally:
            fresh.close()


if __name__ == "__main__":
    unittest.main()
