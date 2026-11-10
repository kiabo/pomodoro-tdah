import tempfile
import unittest
from types import SimpleNamespace

from tests_gtk._support import make_controller, require_gtk

require_gtk()

from gi.repository import Gdk  # noqa: E402

from pomodoro.ui.main_window import MainWindow  # noqa: E402
from pomodoro.ui.theme import load_theme  # noqa: E402


def key(keyval, state=0):
    return SimpleNamespace(keyval=keyval, state=state)


class MainWindowShortcutsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name)
        load_theme()
        self.window = MainWindow(self.controller)
        self.window.show_all()

    def tearDown(self):
        self.window.destroy()
        self.controller.shutdown()
        self._tmp.cleanup()

    def test_space_toggles_timer_when_focus_is_neutral(self):
        self.window.set_focus(None)
        self.assertTrue(self.window._on_key_press(self.window, key(Gdk.KEY_space)))
        self.assertTrue(self.controller.timer.running)
        self.window._on_key_press(self.window, key(Gdk.KEY_space))
        self.assertFalse(self.controller.timer.running)

    def test_space_is_left_to_text_fields(self):
        self.window.today.search.grab_focus()
        self.assertFalse(self.window._on_key_press(self.window, key(Gdk.KEY_space)))
        self.assertFalse(self.controller.timer.running)

    def test_escape_returns_to_today(self):
        self.window.show_page("groups")
        self.window.set_focus(None)
        self.assertTrue(self.window._on_key_press(self.window, key(Gdk.KEY_Escape)))
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")
        self.assertFalse(self.window._on_key_press(self.window, key(Gdk.KEY_Escape)))

    def test_ctrl_k_focuses_search(self):
        self.window.show_page("plan")
        self.assertTrue(self.window._on_key_press(self.window, key(Gdk.KEY_k, Gdk.ModifierType.CONTROL_MASK)))
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")


if __name__ == "__main__":
    unittest.main()
