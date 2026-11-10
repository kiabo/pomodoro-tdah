import unittest

from pomodoro.ui.shortcuts import key_action


class KeyActionTest(unittest.TestCase):
    def test_ctrl_shortcuts_work_even_while_typing(self):
        self.assertEqual(key_action("k", ctrl=True, typing=True), "search")
        self.assertEqual(key_action("N", ctrl=True), "new-task")
        self.assertIsNone(key_action("x", ctrl=True))
        self.assertIsNone(key_action("space", ctrl=True))

    def test_space_toggles_the_timer_only_when_nothing_consumes_it(self):
        self.assertEqual(key_action("space"), "toggle-timer")
        self.assertIsNone(key_action("space", typing=True))
        self.assertIsNone(key_action("space", activatable=True))

    def test_escape_goes_back_except_on_today_or_while_typing(self):
        self.assertEqual(key_action("Escape", page="task"), "back")
        self.assertEqual(key_action("Escape", page="plan"), "back")
        self.assertIsNone(key_action("Escape", page="today"))
        self.assertIsNone(key_action("Escape", typing=True, page="task"))

    def test_other_keys_are_ignored(self):
        self.assertIsNone(key_action("a"))
        self.assertIsNone(key_action(None))


if __name__ == "__main__":
    unittest.main()
