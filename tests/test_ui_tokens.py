import re
import unittest
from pathlib import Path

from pomodoro.ui.tokens import COLORS, GROUP_COLORS, hex_to_rgb

CSS = Path(__file__).resolve().parent.parent / "pomodoro" / "ui" / "theme.css"


class TokensTest(unittest.TestCase):
    def test_all_tokens_are_valid_hex(self):
        for name, value in COLORS.items():
            self.assertRegex(value, r"^#[0-9A-F]{6}$", name)

    def test_no_accidental_duplicate_colors(self):
        by_value = {}
        for name, value in COLORS.items():
            by_value.setdefault(value, set()).add(name)
        duplicates = [names for names in by_value.values() if len(names) > 1]
        self.assertEqual(duplicates, [{"ink", "dark"}])   # único alias intencional do design

    def test_css_only_uses_design_tokens(self):
        used = set(re.findall(r"#[0-9A-Fa-f]{6}\b", CSS.read_text()))
        known = {v.upper() for v in COLORS.values()}
        unknown = {c for c in used if c.upper() not in known}
        self.assertEqual(unknown, set(), "cores no theme.css que não são tokens do design")

    def test_group_palette_has_seven_distinct_colors(self):
        self.assertEqual(len(GROUP_COLORS), 7)
        self.assertEqual(len(set(GROUP_COLORS)), 7)
        self.assertTrue(set(GROUP_COLORS) <= set(COLORS.values()))

    def test_hex_to_rgb(self):
        self.assertEqual(hex_to_rgb("#FFFFFF"), (1.0, 1.0, 1.0))
        self.assertEqual(hex_to_rgb("#000000"), (0.0, 0.0, 0.0))
        r, g, b = hex_to_rgb("#5B5BD6")
        self.assertAlmostEqual(r, 0x5B / 255)
        self.assertAlmostEqual(b, 0xD6 / 255)
        with self.assertRaises(ValueError):
            hex_to_rgb("#FFF")


if __name__ == "__main__":
    unittest.main()
