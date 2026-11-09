import unittest

from pomodoro.ui.format import (delta_text, format_clock, format_minutes, format_real,
                                parse_duration, pomodoros_estimate)


class FormatTest(unittest.TestCase):
    def test_format_minutes_matches_the_design(self):
        cases = {0: "0m", 5: "5m", 45: "45m", 60: "1h", 65: "1h 05m", 80: "1h 20m",
                 90: "1h 30m", 130: "2h 10m", 270: "4h 30m", 1440: "24h"}
        for minutes, expected in cases.items():
            self.assertEqual(format_minutes(minutes), expected, minutes)

    def test_format_minutes_rounds_and_clamps(self):
        self.assertEqual(format_minutes(44.6), "45m")
        self.assertEqual(format_minutes(-5), "0m")

    def test_format_real(self):
        self.assertEqual(format_real(0), "—")
        self.assertEqual(format_real(None), "—")
        self.assertEqual(format_real(20), "<1m")
        self.assertEqual(format_real(90), "2m")
        self.assertEqual(format_real(50 * 60), "50m")
        self.assertEqual(format_real(3905 * 1), "1h 05m")

    def test_format_clock(self):
        self.assertEqual(format_clock(932), "15:32")
        self.assertEqual(format_clock(0), "00:00")
        self.assertEqual(format_clock(25 * 60), "25:00")
        self.assertEqual(format_clock(5400), "1:30:00")
        self.assertEqual(format_clock(-130), "+02:10")

    def test_delta_text(self):
        self.assertEqual(delta_text(15 * 60, 20), ("↓5m", "under"))
        self.assertEqual(delta_text(62 * 60, 50), ("↑12m", "over"))
        self.assertEqual(delta_text(20 * 60, 20), ("", "even"))
        self.assertEqual(delta_text(0, 20), ("", "even"))
        self.assertEqual(delta_text(600, None), ("", "even"))
        self.assertEqual(delta_text(95 * 60, 30), ("↑1h 05m", "over"))

    def test_pomodoros_estimate(self):
        self.assertEqual(pomodoros_estimate(90), 4)
        self.assertEqual(pomodoros_estimate(45), 2)
        self.assertEqual(pomodoros_estimate(25), 1)
        self.assertEqual(pomodoros_estimate(26), 2)
        self.assertEqual(pomodoros_estimate(0), 0)
        self.assertEqual(pomodoros_estimate(None), 0)
        self.assertEqual(pomodoros_estimate(100, work_min=50), 2)


class ParseDurationTest(unittest.TestCase):
    def test_accepted_formats(self):
        cases = {
            "90": 90, "45m": 45, "45 min": 45, "1h30": 90, "1h 30m": 90, "1H30M": 90,
            "1:30": 90, "0:45": 45, "2h": 120, "2 horas": 120, "1,5h": 90, "1.5h": 90,
            "  25  ": 25, "0": 0, "1h 5": 65,
        }
        for text, expected in cases.items():
            self.assertEqual(parse_duration(text), expected, text)

    def test_rejected(self):
        for text in ("", "   ", None, "abc", "h", "1:75", "-5", "1h30x", "um"):
            self.assertIsNone(parse_duration(text), repr(text))

    def test_round_trip_with_format(self):
        for minutes in (5, 45, 60, 65, 90, 270):
            self.assertEqual(parse_duration(format_minutes(minutes)), minutes)


if __name__ == "__main__":
    unittest.main()
