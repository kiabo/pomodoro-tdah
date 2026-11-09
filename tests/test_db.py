import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pomodoro import db

NOW = datetime(2026, 11, 9, 10, 0, 0)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class MigrationTest(TempDirTest):
    def test_fresh_database_gets_latest_schema(self):
        conn = db.open_database(self.dir, NOW)
        self.assertEqual(db.schema_version(conn), db.SCHEMA_VERSION)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ("groups", "tasks", "subtasks", "sessions", "distractions", "day_reviews", "meta"):
            self.assertIn(name, tables)
        conn.close()

    def test_reopening_is_idempotent(self):
        db.open_database(self.dir, NOW).close()
        conn = db.open_database(self.dir, NOW)
        self.assertEqual(db.schema_version(conn), db.SCHEMA_VERSION)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0], 1)
        conn.close()

    def test_newer_database_is_refused(self):
        path = self.dir / db.DB_FILENAME
        raw = sqlite3.connect(path)
        raw.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
        raw.close()
        with self.assertRaises(RuntimeError):
            db.open_database(self.dir, NOW)

    def test_foreign_keys_are_enforced(self):
        conn = db.open_database(self.dir, NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks(id, group_id, title, created_at) VALUES ('x', 'nao-existe', 't', 'now')"
            )
        conn.close()

    def test_default_group_created(self):
        conn = db.open_database(self.dir, NOW)
        group = conn.execute("SELECT * FROM groups").fetchone()
        self.assertEqual(group["name"], db.DEFAULT_GROUP_NAME)
        self.assertEqual(db.get_meta(conn, "default_group_id"), group["id"])
        conn.close()


class LegacyImportTest(TempDirTest):
    def write_legacy(self, content):
        path = self.dir / db.LEGACY_TASKS_FILENAME
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_imports_tasks_and_keeps_backup(self):
        path = self.write_legacy([
            {"id": "a1b2c3d4", "title": "Responder e-mails", "done": True},
            {"id": "e5f6a7b8", "title": "Lavar roupa", "done": False},
            {"id": "zz", "title": "   "},
            "lixo",
        ])
        conn = db.open_database(self.dir, NOW)
        rows = conn.execute("SELECT * FROM tasks ORDER BY position").fetchall()
        self.assertEqual([r["title"] for r in rows], ["Responder e-mails", "Lavar roupa"])
        self.assertEqual(rows[0]["id"], "a1b2c3d4")
        self.assertEqual(rows[0]["status"], "done")
        self.assertIsNotNone(rows[0]["done_at"])
        self.assertEqual(rows[1]["status"], "todo")
        self.assertIsNone(rows[1]["scheduled_for"])
        default_group = db.get_meta(conn, "default_group_id")
        self.assertTrue(all(r["group_id"] == default_group for r in rows))
        self.assertFalse(path.exists())
        self.assertTrue((self.dir / "tasks.json.bak").exists())
        conn.close()

    def test_import_happens_only_once(self):
        self.write_legacy([{"id": "a", "title": "Primeira", "done": False}])
        db.open_database(self.dir, NOW).close()
        # Um novo tasks.json depois da migração não é importado de novo.
        self.write_legacy([{"id": "b", "title": "Segunda", "done": False}])
        conn = db.open_database(self.dir, NOW)
        titles = [r["title"] for r in conn.execute("SELECT title FROM tasks")]
        self.assertEqual(titles, ["Primeira"])
        conn.close()

    def test_unreadable_file_is_left_untouched(self):
        path = self.write_legacy("{isso não é json")
        conn = db.open_database(self.dir, NOW)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertTrue(path.exists())
        self.assertEqual(db.get_meta(conn, "legacy_imported"), "unreadable")
        conn.close()

    def test_no_legacy_file(self):
        conn = db.open_database(self.dir, NOW)
        self.assertIsNone(db.get_meta(conn, "legacy_imported"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
