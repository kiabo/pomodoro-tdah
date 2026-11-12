import tempfile
import unittest
from pathlib import Path

from pomodoro import db
from pomodoro.jira import client as jc, importer
from pomodoro.repository import Repository

from .jira_support import parsed_issue, raw_issue
from .test_repository import FakeClock


def issue(**kwargs):
    return parsed_issue(**kwargs)


class ParseTest(unittest.TestCase):
    def test_epic_child_subtask_and_plain(self):
        epic = jc.parse_issue(raw_issue("ABC-10", issue_type="Epic", level=1), "https://x.atlassian.net")
        self.assertEqual((epic["is_epic"], epic["is_subtask"], epic["parent"]), (True, False, None))
        child = jc.parse_issue(raw_issue("ABC-11", parent="ABC-10", parent_title="Plataforma"), "https://x.atlassian.net")
        self.assertEqual(child["parent"], {"key": "ABC-10", "title": "Plataforma", "is_epic": True})
        sub = jc.parse_issue(raw_issue("ABC-12", issue_type="Subtarefa", level=-1, subtask=True, parent="ABC-11",
                                       parent_type="Tarefa"), "https://x.atlassian.net")
        self.assertEqual((sub["is_subtask"], sub["parent"]["is_epic"]), (True, False))
        plain = jc.parse_issue(raw_issue("ABC-13"), "https://x.atlassian.net")
        self.assertEqual((plain["is_epic"], plain["parent"], plain["issue_type"]), (False, None, "Task"))

    def test_parent_is_requested_and_default_jql_includes_unassigned_and_reported(self):
        self.assertIn("parent", jc.SEARCH_FIELDS)
        for part in ("assignee = currentUser()", "reporter = currentUser()", "assignee is EMPTY", "Unresolved"):
            self.assertIn(part, jc.DEFAULT_JQL)


class HierarchyImportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def run_import(self, issues, epic_groups=None, project_groups=None):
        items = importer.plan_import(self.repo, issues, project_groups, epic_groups)
        result = importer.apply_import(self.repo, items, all_keys=[i["key"] for i in issues],
                                       epic_groups=epic_groups)
        return items, result

    def group_names(self, task_key):
        link = self.repo.jira_link_by_key(task_key)
        return self.repo.get_group(self.repo.get_task(link["task_id"])["group_id"])["name"]

    def test_epic_becomes_group_and_children_go_into_it(self):
        issues = [issue(key="ABC-10", summary="Plataforma", issue_type="Epic", level=1),
                  issue(key="ABC-11", summary="Tarefa A", parent="ABC-10", parent_title="Plataforma"),
                  issue(key="ABC-12", summary="Bug B", issue_type="Bug", parent="ABC-10", parent_title="Plataforma"),
                  issue(key="ABC-13", summary="Sem épico")]
        items, result = self.run_import(issues)
        self.assertEqual((result["created"], result["groups"]), (3, 1))
        self.assertIsNone(self.repo.jira_link_by_key("ABC-10"))            # o épico NÃO vira tarefa
        self.assertEqual((self.group_names("ABC-11"), self.group_names("ABC-12")), ("Plataforma", "Plataforma"))
        self.assertEqual(self.group_names("ABC-13"), "Jira")
        link = self.repo.jira_link_by_key("ABC-12")
        self.assertEqual((link["issue_type"], link["epic_key"]), ("Bug", "ABC-10"))
        self.assertEqual(list(result["epic_groups"]), ["ABC-10"])

    def test_epic_resolved_or_outside_the_result_still_makes_the_group(self):
        _items, result = self.run_import([issue(key="ABC-11", parent="ABC-43", parent_title="Épico antigo")])
        self.assertEqual(self.group_names("ABC-11"), "Épico antigo")
        self.assertEqual(result["groups"], 1)

    def test_epic_without_children_creates_empty_group(self):
        _items, result = self.run_import([issue(key="ABC-10", summary="Vazio", issue_type="Epic", level=1)])
        self.assertEqual(result["groups"], 1)
        self.assertEqual([g["name"] for g in self.repo.list_groups() if g["name"] == "Vazio"], ["Vazio"])

    def test_second_import_is_idempotent_and_reuses_the_group(self):
        issues = [issue(key="ABC-10", issue_type="Epic", level=1, summary="Plataforma"),
                  issue(key="ABC-11", parent="ABC-10", parent_title="Plataforma")]
        _i, first = self.run_import(issues)
        count = len(self.repo.list_groups())
        items, second = self.run_import(issues, epic_groups=first["epic_groups"])
        self.assertEqual({i.action for i in items}, {importer.SAME})
        self.assertEqual((second["created"], second["groups"], len(self.repo.list_groups())), (0, 0, count))

    def test_new_child_of_known_epic_goes_to_the_users_renamed_group(self):
        _i, first = self.run_import([issue(key="ABC-11", parent="ABC-10", parent_title="Plataforma")])
        group_id = first["epic_groups"]["ABC-10"]
        self.repo.update_group(group_id, name="Meu nome")
        self.run_import([issue(key="ABC-14", parent="ABC-10", parent_title="Plataforma")],
                        epic_groups=first["epic_groups"])
        self.assertEqual(self.group_names("ABC-14"), "Meu nome")

    def test_deleted_epic_group_is_recreated(self):
        _i, first = self.run_import([issue(key="ABC-11", parent="ABC-10", parent_title="Plataforma")])
        self.repo.delete_group(first["epic_groups"]["ABC-10"])
        self.run_import([issue(key="ABC-14", parent="ABC-10", parent_title="Plataforma")],
                        epic_groups=first["epic_groups"])
        self.assertEqual(self.group_names("ABC-14"), "Plataforma")

    def test_jira_subtask_becomes_local_subtask_of_its_parent(self):
        issues = [issue(key="ABC-11", summary="Pai"),
                  issue(key="ABC-12", summary="Filha", issue_type="Subtarefa", level=-1, subtask=True,
                        parent="ABC-11", parent_type="Tarefa", seconds=1200)]
        items, result = self.run_import(issues)
        self.assertEqual((result["created"], result["subtasks"]), (1, 1))
        self.assertIsNone(self.repo.jira_link_by_key("ABC-12"))            # não vira tarefa solta
        parent_id = self.repo.jira_link_by_key("ABC-11")["task_id"]
        sub = self.repo.list_subtasks(parent_id)[0]
        self.assertEqual((sub["title"], sub["jira_key"], sub["estimate_min"]), ("Filha", "ABC-12", 20))
        again, second = self.run_import(issues, epic_groups=result["epic_groups"])
        self.assertEqual((second["subtasks"], len(self.repo.list_subtasks(parent_id))), (0, 1))

    def test_subtask_of_already_imported_parent(self):
        self.run_import([issue(key="ABC-11")])
        _i, result = self.run_import([issue(key="ABC-12", issue_type="Subtarefa", level=-1, subtask=True,
                                            parent="ABC-11", parent_type="Tarefa")])
        self.assertEqual(result["subtasks"], 1)

    def test_subtask_with_unknown_parent_falls_back_to_a_task(self):
        items, result = self.run_import([issue(key="ABC-12", issue_type="Subtarefa", level=-1, subtask=True,
                                               parent="ABC-99", parent_type="Tarefa")])
        self.assertEqual((items[0].kind, result["created"], result["subtasks"]), (importer.TASK, 1, 0))

    def test_unselected_epic_group_item_creates_nothing(self):
        issues = [issue(key="ABC-10", issue_type="Epic", level=1)]
        items = importer.plan_import(self.repo, issues)
        items[0].selected = False
        result = importer.apply_import(self.repo, items)
        self.assertEqual((result["groups"], len(self.repo.list_groups())), (0, 1))     # só o "Geral"

    def test_changed_type_or_epic_shows_as_update(self):
        self.run_import([issue(key="ABC-11")])
        items = importer.plan_import(self.repo, [issue(key="ABC-11", parent="ABC-10", parent_title="P")])
        self.assertEqual((items[0].action, "tipo ou épico" in items[0].changes), (importer.UPDATE, True))


if __name__ == "__main__":
    unittest.main()
