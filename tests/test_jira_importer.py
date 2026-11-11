import tempfile
import unittest
from pathlib import Path

from pomodoro import db
from pomodoro.jira import importer
from pomodoro.repository import Repository

from .jira_support import parsed_issue
from .test_repository import FakeClock


class ImporterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)

    def tearDown(self):
        self.conn.close()

    def run_import(self, issues, **kwargs):
        items = importer.plan_import(self.repo, issues, kwargs.get("project_groups"))
        return items, importer.apply_import(self.repo, items, all_keys=[i["key"] for i in issues])

    def test_new_issue_creates_task_in_jira_group(self):
        items, result = self.run_import([parsed_issue(key="ABC-1", seconds=1800)])
        self.assertEqual((items[0].action, result["created"]), (importer.NEW, 1))
        link = self.repo.jira_link_by_key("ABC-1")
        task = self.repo.get_task(link["task_id"])
        self.assertEqual((task["title"], task["estimate_min"], task["status"]), ("Corrigir login", 30, "todo"))
        self.assertEqual(self.repo.get_group(task["group_id"])["name"], "Jira")
        self.assertEqual(link["remote_status"], "To Do")
        self.assertEqual(self.repo.jira_keys(), {task["id"]: "ABC-1"})

    def test_mapped_project_uses_chosen_group(self):
        group = self.repo.create_group("Trabalho")
        _items, _ = self.run_import([parsed_issue()], project_groups={"ABC": group["id"]})
        task = self.repo.get_task(self.repo.jira_link_by_key("ABC-1")["task_id"])
        self.assertEqual(task["group_id"], group["id"])

    def test_archived_or_missing_mapping_falls_back(self):
        group = self.repo.create_group("Velho")
        self.repo.archive_group(group["id"])
        items = importer.plan_import(self.repo, [parsed_issue()], {"ABC": group["id"], "X": "nao-existe"})
        self.assertIsNone(items[0].group_id)

    def test_second_import_is_same_and_idempotent(self):
        self.run_import([parsed_issue()])
        items, result = self.run_import([parsed_issue()])
        self.assertEqual((items[0].action, result["created"], result["updated"]), (importer.SAME, 0, 0))
        self.assertEqual(len(self.repo.list_tasks()), 1)

    def test_update_follows_title_until_user_renames(self):
        self.run_import([parsed_issue(summary="Antigo")])
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        items, result = self.run_import([parsed_issue(summary="Novo", status="In Progress", category="indeterminate")])
        self.assertEqual((items[0].action, result["updated"]), (importer.UPDATE, 1))
        self.assertEqual(self.repo.get_task(task_id)["title"], "Novo")
        self.assertEqual(self.repo.jira_link(task_id)["remote_status"], "In Progress")
        self.repo.update_task(task_id, title="Meu jeito")
        self.run_import([parsed_issue(summary="Outro título do Jira")])
        task = self.repo.get_task(task_id)
        self.assertEqual(task["title"], "Meu jeito")
        self.assertEqual(self.repo.jira_link(task_id)["remote_title"], "Outro título do Jira")

    def test_user_data_is_never_touched(self):
        self.run_import([parsed_issue(seconds=1800)])
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        self.repo.update_task(task_id, estimate_min=90, notes="meu plano", energy="high", scheduled_for="2026-11-12")
        sub = self.repo.add_subtask(task_id, "Passo meu", 10)
        self.run_import([parsed_issue(seconds=7200, description="outra", status="Done", category="done")])
        task = self.repo.get_task(task_id)
        self.assertEqual((task["estimate_min"], task["notes"], task["energy"], task["status"], task["scheduled_for"]),
                         (90, "meu plano", "high", "todo", "2026-11-12"))
        self.assertEqual([s["id"] for s in self.repo.list_subtasks(task_id)], [sub["id"]])
        self.assertEqual(self.repo.jira_link(task_id)["remote_estimate_min"], 120)

    def test_issue_leaving_result_is_flagged_not_deleted(self):
        self.run_import([parsed_issue(key="ABC-1"), parsed_issue(key="ABC-2")])
        self.run_import([parsed_issue(key="ABC-1")])
        self.assertEqual(self.repo.jira_link_by_key("ABC-2")["missing"], 1)
        self.assertEqual(len(self.repo.list_tasks()), 2)
        items, _ = self.run_import([parsed_issue(key="ABC-1"), parsed_issue(key="ABC-2")])
        self.assertEqual(self.repo.jira_link_by_key("ABC-2")["missing"], 0)

    def test_unselected_items_are_skipped(self):
        items = importer.plan_import(self.repo, [parsed_issue(key="ABC-1"), parsed_issue(key="ABC-2")])
        items[0].selected = False
        result = importer.apply_import(self.repo, items)
        self.assertEqual(result["created"], 1)
        self.assertIsNone(self.repo.jira_link_by_key("ABC-1"))

    def test_group_requiring_estimate_skips_issue_without_one(self):
        group = self.repo.create_group("Exige", require_estimate=True)
        items = importer.plan_import(self.repo, [parsed_issue(seconds=None)], {"ABC": group["id"]})
        result = importer.apply_import(self.repo, items)
        self.assertEqual((result["created"], result["skipped"][0][0]), (0, "ABC-1"))
        self.assertEqual(self.repo.list_tasks(group_id=group["id"]), [])

    def test_deleting_task_removes_link_and_unlink_keeps_task(self):
        self.run_import([parsed_issue(key="ABC-1"), parsed_issue(key="ABC-2")])
        one = self.repo.jira_link_by_key("ABC-1")["task_id"]
        two = self.repo.jira_link_by_key("ABC-2")["task_id"]
        self.repo.delete_task(one)
        self.assertIsNone(self.repo.jira_link_by_key("ABC-1"))
        self.repo.remove_jira_link(two)
        self.assertIsNotNone(self.repo.get_task(two))
        self.assertIsNone(self.repo.jira_link(two))


if __name__ == "__main__":
    unittest.main()
