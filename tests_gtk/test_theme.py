import unittest

from tests_gtk._support import require_gtk

require_gtk()

from gi.repository import Gtk  # noqa: E402

from pomodoro.ui import theme  # noqa: E402


class ThemeTest(unittest.TestCase):
    def test_css_parses_without_errors(self):
        _provider, errors = theme.parse_theme()
        self.assertEqual(errors, [])

    def test_load_theme_is_applied_once(self):
        self.assertIs(theme.load_theme(), theme.load_theme())

    def test_themed_window_gets_the_class(self):
        window = theme.themed_window(Gtk.Window())
        self.assertTrue(window.get_style_context().has_class(theme.APP_WINDOW_CLASS))

    def test_style_helper_chains(self):
        label = theme.style(Gtk.Label(), "muted", "small")
        context = label.get_style_context()
        self.assertTrue(context.has_class("muted") and context.has_class("small"))

    def test_rgba(self):
        color = theme.rgba("#5B5BD6", 0.5)
        self.assertAlmostEqual(color.red, 0x5B / 255, places=3)
        self.assertAlmostEqual(color.alpha, 0.5)


if __name__ == "__main__":
    unittest.main()
