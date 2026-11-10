import unittest
from datetime import date, datetime

from pomodoro.recurrence import describe, is_valid, next_date, options_for


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


class NextDateTest(unittest.TestCase):
    def test_daily_and_weekdays(self):
        self.assertEqual(next_date("daily", date(2026, 11, 9)), date(2026, 11, 10))
        self.assertEqual(next_date("weekdays", date(2026, 11, 9)), date(2026, 11, 10))      # seg -> ter
        self.assertEqual(next_date("weekdays", date(2026, 11, 13)), date(2026, 11, 16))     # sex -> seg
        self.assertEqual(next_date("weekdays", "2026-11-14"), date(2026, 11, 16))           # sáb -> seg

    def test_weekly_is_strictly_after(self):
        self.assertEqual(next_date("weekly:0", date(2026, 11, 9)), date(2026, 11, 16))      # segunda -> segunda
        self.assertEqual(next_date("weekly:2", date(2026, 11, 9)), date(2026, 11, 11))
        self.assertEqual(next_date("weekly:6", datetime(2026, 11, 9, 8)), date(2026, 11, 15))

    def test_monthly_clamps_short_months(self):
        self.assertEqual(next_date("monthly:9", date(2026, 11, 9)), date(2026, 12, 9))
        self.assertEqual(next_date("monthly:15", date(2026, 11, 9)), date(2026, 11, 15))
        self.assertEqual(next_date("monthly:31", date(2026, 11, 9)), date(2026, 11, 30))
        self.assertEqual(next_date("monthly:31", date(2026, 2, 28)), date(2026, 3, 31))
        self.assertEqual(next_date("monthly:5", date(2026, 12, 20)), date(2027, 1, 5))

    def test_rejects_invalid_rules(self):
        for rule in (None, "", "hourly", "weekly:9"):
            with self.assertRaises(ValueError):
                next_date(rule, date(2026, 11, 9))


if __name__ == "__main__":
    unittest.main()
