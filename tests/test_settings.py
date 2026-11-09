import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pomodoro import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_when_missing(self):
        self.assertEqual(settings.load_settings(self.dir), settings.DEFAULT_SETTINGS)

    def test_old_file_keeps_values_and_gains_new_keys(self):
        old = {"work_min": 50, "short_break_min": 10, "long_break_min": 20, "cycles_before_long_break": 3}
        (self.dir / settings.SETTINGS_FILENAME).write_text(json.dumps(old))
        loaded = settings.load_settings(self.dir)
        self.assertEqual(loaded["work_min"], 50)
        self.assertEqual(loaded["cycles_before_long_break"], 3)
        self.assertTrue(loaded["hyperfocus_alert"])
        self.assertEqual(loaded["compact_fields"], settings.DEFAULT_SETTINGS["compact_fields"])

    def test_invalid_values_fall_back_to_defaults(self):
        bad = {
            "work_min": "vinte", "short_break_min": 0, "auto_start_breaks": "sim",
            "compact_idle_opacity": 5, "compact_fields": ["remaining", "xyz"],
            "compact_position": [10, "a"], "hyperfocus_threshold_pct": True, "desconhecida": 1,
        }
        (self.dir / settings.SETTINGS_FILENAME).write_text(json.dumps(bad))
        loaded = settings.load_settings(self.dir)
        for key in ("work_min", "short_break_min", "auto_start_breaks", "compact_idle_opacity",
                    "compact_fields", "compact_position", "hyperfocus_threshold_pct"):
            self.assertEqual(loaded[key], settings.DEFAULT_SETTINGS[key], key)
        self.assertNotIn("desconhecida", loaded)

    def test_reminder_time_must_be_a_clock_time_or_empty(self):
        for good in ("18:00", "07:30", "23:59", ""):
            self.assertEqual(settings.sanitize({"end_of_day_reminder": good})["end_of_day_reminder"], good)
        for bad in ("25:00", "18:60", "6:00", "18h", "18:00:00", 1800, None):
            self.assertEqual(settings.sanitize({"end_of_day_reminder": bad})["end_of_day_reminder"], "18:00", bad)

    def test_corrupted_file(self):
        (self.dir / settings.SETTINGS_FILENAME).write_text("{quebrado")
        self.assertEqual(settings.load_settings(self.dir), settings.DEFAULT_SETTINGS)

    def test_round_trip_and_private_permissions(self):
        data = settings.load_settings(self.dir)
        data.update(work_min=45, compact_position=[100, 40], anthropic_api_key="sk-teste")
        settings.save_settings(data, self.dir)
        path = self.dir / settings.SETTINGS_FILENAME
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        loaded = settings.load_settings(self.dir)
        self.assertEqual(loaded["work_min"], 45)
        self.assertEqual(loaded["compact_position"], [100, 40])

    def test_defaults_are_not_shared(self):
        a = settings.load_settings(self.dir)
        a["compact_fields"].append("estimate_vs_real")
        self.assertNotIn("estimate_vs_real", settings.DEFAULT_SETTINGS["compact_fields"])

    def test_api_key_falls_back_to_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env"}):
            self.assertEqual(settings.api_key({"anthropic_api_key": ""}), "sk-env")
            self.assertEqual(settings.api_key({"anthropic_api_key": "sk-conf"}), "sk-conf")

    def test_data_dir_override(self):
        with mock.patch.dict(os.environ, {"POMODORO_DATA_DIR": str(self.dir)}):
            self.assertEqual(settings.data_dir(), self.dir)


if __name__ == "__main__":
    unittest.main()
