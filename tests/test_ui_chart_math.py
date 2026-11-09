import math
import unittest

from pomodoro.ui.chart_math import RING_START, bar_layout, cycle_bar_layout, cycle_segments, ring_arc

WEEK = [
    {"label": "Seg", "planned": 102, "real": 119},
    {"label": "Ter", "planned": 153, "real": 143},
    {"label": "Qua", "planned": 136, "real": 170},
    {"label": "Qui", "planned": 119, "real": 112},
    {"label": "Sex", "planned": 102, "real": 129},
]


class RingTest(unittest.TestCase):
    def test_arc_angles(self):
        start, end = ring_arc(0.25)
        self.assertAlmostEqual(start, -math.pi / 2)
        self.assertAlmostEqual(end, 0.0)          # 1/4 de volta: 12h -> 3h
        self.assertAlmostEqual(ring_arc(0.5)[1], math.pi / 2)
        self.assertAlmostEqual(ring_arc(1.0)[1] - RING_START, 2 * math.pi)

    def test_fraction_is_clamped(self):
        self.assertEqual(ring_arc(-3), ring_arc(0))
        self.assertEqual(ring_arc(7), ring_arc(1))


class BarLayoutTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(bar_layout([], 400, 200), [])

    def test_bars_sit_on_the_baseline_and_scale_to_the_peak(self):
        layout = bar_layout(WEEK, 640, 202, label_height=22)
        plot_h = 180
        for day in layout:
            for bar in day["bars"]:
                self.assertAlmostEqual(bar["y"] + bar["h"], plot_h)
        tallest = max(b["h"] for d in layout for b in d["bars"])
        self.assertAlmostEqual(tallest, plot_h)                      # o pico (170) ocupa a área toda
        quarta = layout[2]["bars"]
        self.assertAlmostEqual(quarta[1]["h"], plot_h)
        self.assertAlmostEqual(quarta[0]["h"], 136 / 170 * plot_h)

    def test_real_bar_turns_red_only_when_above_planned(self):
        kinds = [d["bars"][1]["kind"] for d in bar_layout(WEEK, 640, 200)]
        self.assertEqual(kinds, ["real_over", "real_ok", "real_over", "real_ok", "real_over"])
        self.assertEqual([d["bars"][0]["kind"] for d in bar_layout(WEEK, 640, 200)], ["planned"] * 5)

    def test_no_plan_is_never_over(self):
        layout = bar_layout([{"label": "Dom", "planned": 0, "real": 40}], 300, 120)
        self.assertEqual(layout[0]["bars"][0]["h"], 0)
        self.assertEqual(layout[0]["bars"][1]["kind"], "real_ok")

    def test_columns_are_evenly_spaced_inside_the_padding(self):
        layout = bar_layout(WEEK, 640, 200, side_pad=12)
        self.assertAlmostEqual(layout[0]["pair_x0"], 12)
        self.assertAlmostEqual(layout[-1]["pair_x1"], 640 - 12)
        steps = [b["pair_x0"] - a["pair_x0"] for a, b in zip(layout, layout[1:])]
        for step in steps:
            self.assertAlmostEqual(step, steps[0])

    def test_single_day_is_centered(self):
        day = bar_layout([WEEK[0]], 300, 120)[0]
        self.assertAlmostEqual((day["pair_x0"] + day["pair_x1"]) / 2, 150)

    def test_many_days_shrink_bars_without_overlap(self):
        month = [{"label": str(i), "planned": 60, "real": 70} for i in range(30)]
        layout = bar_layout(month, 640, 200)
        self.assertLess(layout[0]["bars"][0]["w"], 22)
        self.assertGreaterEqual(layout[0]["bars"][0]["w"], 2)
        for a, b in zip(layout, layout[1:]):
            self.assertLessEqual(a["pair_x1"], b["pair_x0"] + 1e-9)

    def test_tiny_values_stay_visible(self):
        layout = bar_layout([{"label": "x", "planned": 1, "real": 1000}], 300, 120)
        self.assertGreaterEqual(layout[0]["bars"][0]["h"], 2)


class CycleBarTest(unittest.TestCase):
    def test_proportional_and_gapped(self):
        layout = cycle_bar_layout(cycle_segments(25, 5, 15, 4), 400, gap=3)
        self.assertEqual(len(layout), 8)
        self.assertAlmostEqual(layout[-1]["x"] + layout[-1]["w"], 400)
        work, short = layout[0], layout[1]
        self.assertAlmostEqual(work["w"] / short["w"], 5.0)
        for a, b in zip(layout, layout[1:]):
            self.assertAlmostEqual(b["x"] - (a["x"] + a["w"]), 3)

    def test_tiny_segments_stay_visible_and_empty_is_empty(self):
        layout = cycle_bar_layout([{"kind": "work", "minutes": 100}, {"kind": "short", "minutes": 0}], 200, min_width=3)
        self.assertGreaterEqual(layout[1]["w"], 3)
        self.assertEqual(cycle_bar_layout([], 200), [])


class CycleTest(unittest.TestCase):
    def test_segments(self):
        segments = cycle_segments(25, 5, 15, 4)
        self.assertEqual([(s["kind"], s["minutes"]) for s in segments],
                         [("work", 25), ("short", 5), ("work", 25), ("short", 5), ("work", 25), ("short", 5),
                          ("work", 25), ("long", 15)])
        self.assertEqual(sum(s["minutes"] for s in segments), 130)

    def test_single_cycle_ends_with_the_long_break(self):
        self.assertEqual([(s["kind"], s["minutes"]) for s in cycle_segments(50, 10, 20, 1)],
                         [("work", 50), ("long", 20)])


if __name__ == "__main__":
    unittest.main()
