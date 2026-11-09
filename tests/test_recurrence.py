import unittest
from datetime import date, datetime

from pomodoro.recurrence import describe, is_valid, options_for


class RecurrenceTest(unittest.TestCase):
    def test_validation(self):
        for rule in (None, "daily", "weekdays", "weekly:0", "weekly:6", "monthly:1", "monthly:31"):
            self.assertTrue(is_valid(rule), rule)
        for rule in ("", "weekly", "weekly:7", "weekly:-1", "monthly:0", "monthly:32", "monthly:x", "hourly", 5):
            self.assertFalse(is_valid(rule), rule)

    def test_describe(self):
        self.assertEqual(describe(None), "Não repete")
        self.assertEqual(describe("daily"), "Todo dia")
        self.assertEqual(describe("weekdays"), "Dias úteis")
        self.assertEqual(describe("weekly:0"), "Toda semana (segunda)")
        self.assertEqual(describe("weekly:5"), "Toda semana (sábado)")
        self.assertEqual(describe("monthly:09"), "Todo mês, dia 9")
        with self.assertRaises(ValueError):
            describe("quinzenal")

    def test_options_follow_the_task_day(self):
        options = options_for(date(2026, 11, 9))                    # segunda, dia 9
        self.assertEqual([r for r, _ in options], [None, "daily", "weekdays", "weekly:0", "monthly:9"])
        self.assertEqual(options[3][1], "Toda semana (segunda)")
        self.assertEqual(options_for("2026-11-12")[3], ("weekly:3", "Toda semana (quinta)"))
        self.assertEqual(options_for(datetime(2026, 11, 30, 8))[4], ("monthly:30", "Todo mês, dia 30"))
        self.assertTrue(all(is_valid(rule) for rule, _ in options_for()))


if __name__ == "__main__":
    unittest.main()
