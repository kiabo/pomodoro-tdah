import unittest

from pomodoro.ui.ordering import reorder_ids


class ReorderTest(unittest.TestCase):
    IDS = ["a", "b", "c", "d"]

    def test_move_before_and_after(self):
        self.assertEqual(reorder_ids(self.IDS, "d", "b", after=False), ["a", "d", "b", "c"])
        self.assertEqual(reorder_ids(self.IDS, "d", "b", after=True), ["a", "b", "d", "c"])
        self.assertEqual(reorder_ids(self.IDS, "a", "c", after=True), ["b", "c", "a", "d"])
        self.assertEqual(reorder_ids(self.IDS, "a", "d", after=True), ["b", "c", "d", "a"])
        self.assertEqual(reorder_ids(self.IDS, "c", "a", after=False), ["c", "a", "b", "d"])

    def test_no_change_cases(self):
        self.assertEqual(reorder_ids(self.IDS, "b", "b", after=True), self.IDS)
        self.assertEqual(reorder_ids(self.IDS, "x", "b", after=True), self.IDS)
        self.assertEqual(reorder_ids(self.IDS, "a", "x", after=False), self.IDS)
        self.assertEqual(reorder_ids(self.IDS, "a", "b", after=False), self.IDS)     # já está antes
        self.assertEqual(reorder_ids(self.IDS, "b", "a", after=True), self.IDS)      # já está depois

    def test_input_is_not_mutated(self):
        ids = list(self.IDS)
        reorder_ids(ids, "d", "a", after=False)
        self.assertEqual(ids, self.IDS)


if __name__ == "__main__":
    unittest.main()
