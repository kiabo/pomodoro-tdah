import unittest

from pomodoro.stats import accuracy, capacity_level, mean_accuracy


class AccuracyTest(unittest.TestCase):
    def test_exact_and_off(self):
        self.assertAlmostEqual(accuracy(30 * 60, 30), 1.0)
        self.assertAlmostEqual(accuracy(45 * 60, 30), 0.5)     # 50% acima
        self.assertAlmostEqual(accuracy(15 * 60, 30), 0.5)     # 50% abaixo
        self.assertAlmostEqual(accuracy(27 * 60, 30), 0.9)

    def test_floor_at_zero(self):
        self.assertEqual(accuracy(120 * 60, 30), 0.0)

    def test_not_measurable(self):
        for real, est in ((0, 30), (None, 30), (600, None), (600, 0)):
            self.assertIsNone(accuracy(real, est))

    def test_mean_ignores_unmeasurable(self):
        pairs = [(30 * 60, 30), (15 * 60, 30), (0, 30), (600, None)]
        self.assertAlmostEqual(mean_accuracy(pairs), 0.75)
        self.assertIsNone(mean_accuracy([(0, 30)]))
        self.assertIsNone(mean_accuracy([]))


class CapacityTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(capacity_level(0, 360), ("empty", 0))
        self.assertEqual(capacity_level(None, 360), ("empty", 0))
        self.assertEqual(capacity_level(270, 360), ("ok", 0))      # exatamente 75%
        self.assertEqual(capacity_level(271, 360), ("tight", 0))
        self.assertEqual(capacity_level(360, 360), ("tight", 0))
        self.assertEqual(capacity_level(420, 360), ("over", 60))

    def test_no_free_time_configured(self):
        self.assertEqual(capacity_level(60, 0), ("over", 60))
        self.assertEqual(capacity_level(60, None), ("over", 60))


if __name__ == "__main__":
    unittest.main()
