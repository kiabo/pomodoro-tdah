import tempfile
import unittest
from datetime import date, datetime, timedelta

from pomodoro import settings as settings_mod
from pomodoro.controller import Controller
from pomodoro.jira import client as jc, importer
from pomodoro.jira.client import JiraClient

from .jira_support import FakeJira, parsed_issue, raw_issue
from .test_repository import FakeClock
from .test_timer import FakeScheduler

URL = "https://x.atlassian.net"
SETTINGS = {"jira_url": URL, "jira_email": "eu@exemplo.com", "jira_token": "tok"}


class RetryTest(unittest.TestCase):
    def client(self, fake):
        self.slept = []
        return jc.JiraClient(URL, "eu@exemplo.com", "tok", transport=fake, sleep=self.slept.append)

    def test_waits_and_retries_after_429(self):
        fake = FakeJira(pages=[[raw_issue()]])
        fake.throttle = 1
        self.assertEqual(len(self.client(fake).search()), 1)
        self.assertEqual((self.slept, len(fake.calls)), ([1.0], 2))

    def test_gives_up_after_the_retries(self):
        fake = FakeJira()
        fake.throttle = 99
        with self.assertRaises(jc.JiraError) as ctx:
            self.client(fake).test_connection()
        self.assertEqual(len(fake.calls), jc.MAX_RETRIES + 1)
        self.assertIn("esperar", str(ctx.exception))

    def test_does_not_wait_longer_than_the_limit(self):
        fake = FakeJira(status=429, headers={"Retry-After": "120"})
        with self.assertRaises(jc.JiraError) as ctx:
            self.client(fake).test_connection()
        self.assertEqual((self.slept, len(fake.calls)), ([], 1))
        self.assertIn("120 s", str(ctx.exception))

    def test_write_is_retried_too_and_sent_once_accepted(self):
        fake = FakeJira()
        fake.throttle = 1
        self.assertEqual(self.client(fake).add_comment("ABC-1", "oi"), "900")
        self.assertEqual([c["method"] for c in fake.calls], ["POST", "POST"])

    def test_search_flags_truncation(self):
        fake = FakeJira(pages=[[raw_issue(f"ABC-{i}")] for i in range(jc.MAX_PAGES + 1)])
        client = self.client(fake)
        issues = client.search()
        self.assertEqual((len(issues), client.truncated), (jc.MAX_PAGES, True))
        small = self.client(FakeJira(pages=[[raw_issue()]]))
        small.search()
        self.assertFalse(small.truncated)


class ConflictTest(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from pomodoro import db
        from pomodoro.repository import Repository
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def sync(self, **kwargs):
        issues = [parsed_issue(**kwargs)]
        items = importer.plan_import(self.repo, issues)
        importer.apply_import(self.repo, items, all_keys=["ABC-1"])
        return items

    def test_both_changed_title_keeps_mine_and_flags(self):
        self.sync(summary="Original", seconds=3600)
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        self.repo.update_task(task_id, title="Meu título")
        items = self.sync(summary="Título do time", seconds=3600)
        self.assertTrue(any("o seu foi mantido" in c for c in items[0].changes))
        self.assertEqual(self.repo.get_task(task_id)["title"], "Meu título")
        self.assertEqual(self.repo.jira_link(task_id)["conflicts"], "title")

    def test_duplicate_issue_in_one_search_is_imported_once(self):
        items = importer.plan_import(self.repo, [parsed_issue(), parsed_issue()])
        self.assertEqual(len(items), 1)
        self.assertEqual(importer.apply_import(self.repo, items)["created"], 1)

    def test_both_changed_estimate_flags_but_untouched_local_does_not(self):
        self.sync(seconds=3600)
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        self.sync(seconds=7200)                                    # só o Jira mudou: sem divergência
        self.assertEqual(self.repo.jira_link(task_id)["conflicts"], "")
        self.repo.update_task(task_id, estimate_min=45)
        self.sync(seconds=10800)                                   # os dois mudaram
        self.assertEqual(self.repo.jira_link(task_id)["conflicts"], "estimate")
        self.assertEqual(self.repo.get_task(task_id)["estimate_min"], 45)

    def test_only_jira_changed_title_is_not_a_conflict(self):
        self.sync(summary="A")
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        self.sync(summary="B")
        self.assertEqual((self.repo.get_task(task_id)["title"], self.repo.jira_link(task_id)["conflicts"]), ("B", ""))

    def test_conflict_disappears_when_values_match_again(self):
        self.sync(summary="Original")
        task_id = self.repo.jira_link_by_key("ABC-1")["task_id"]
        self.repo.update_task(task_id, title="Meu")
        self.sync(summary="Time")
        self.assertEqual(self.repo.jira_link(task_id)["conflicts"], "title")
        self.sync(summary="Meu")                                   # o time adotou o seu título
        self.assertEqual(self.repo.jira_link(task_id)["conflicts"], "")


class J5Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJira(pages=[[raw_issue("ABC-1", summary="Original")]])
        self.clock = FakeClock(datetime(2026, 11, 9, 14, 0, 0))
        self.notes = []
        self.c = self.make()

    def tearDown(self):
        self.c.shutdown()
        self._tmp.cleanup()

    def make(self, **settings):
        return Controller(
            data_dir=self._tmp.name, settings=settings_mod.sanitize({**SETTINGS, **settings}),
            scheduler=FakeScheduler(), now=self.clock, today=lambda: date(2026, 11, 9),
            notify=self.notes.append, run_async=lambda job, deliver: deliver(job()),
            jira_factory=lambda url, email, token: JiraClient(url, email, token, transport=self.fake,
                                                             sleep=lambda s: None))

    def preview(self):
        box = []
        self.c.jira_preview(lambda items, error: box.append((items, error)))
        return box[0]

    def import_one(self):
        self.c.jira_import(self.preview()[0])
        self.fake.calls.clear()
        return self.c.repo.jira_link_by_key("ABC-1")["task_id"]

    def writes(self):
        return [c for c in self.fake.calls if c["method"] in ("POST", "PUT") and "search" not in c["url"]]

class ControllerJ5Test(J5Case):
    def test_off_by_default(self):
        self.c.poll_clock()
        self.assertEqual(self.fake.calls, [])

    def test_auto_sync_updates_existing_and_only_announces_new(self):
        task_id = self.import_one()
        self.c.apply_settings({"jira_auto_sync_min": 15})
        self.fake.pages = [[raw_issue("ABC-1", summary="Atualizada", status="In Progress", category="indeterminate"),
                            raw_issue("ABC-2", summary="Nova")]]
        events = []
        self.c.subscribe(events.append)
        self.c.poll_clock()
        self.assertEqual(self.c.repo.get_task(task_id)["title"], "Atualizada")
        self.assertEqual(self.c.jira_link(task_id)["remote_status"], "In Progress")
        self.assertIsNone(self.c.repo.jira_link_by_key("ABC-2"))           # tarefa nova NÃO é criada sozinha
        self.assertEqual(len(self.c.repo.list_tasks()), 1)
        self.assertEqual(self.c.jira_sync_status["new"], 1)
        self.assertEqual(self.notes, ["1 issue(s) nova(s) no Jira. Importe em Configurações → Jira."])
        self.assertIn("jira-sync", events)
        self.assertIn("data", events)
        self.assertEqual(self.writes(), [])                                 # nunca escreve no Jira

    def test_respects_the_interval_and_notifies_new_only_once(self):
        self.import_one()
        self.c.apply_settings({"jira_auto_sync_min": 15})
        page = [raw_issue("ABC-1", summary="Original"), raw_issue("ABC-2")]
        self.fake.pages = [page]
        self.c.poll_clock()
        calls = len(self.fake.calls)
        self.clock.advance(minutes=14)
        self.c.poll_clock()
        self.assertEqual(len(self.fake.calls), calls)                       # ainda não deu o intervalo
        self.clock.advance(minutes=2)
        self.fake.pages = [page]
        self.c.poll_clock()
        self.assertGreater(len(self.fake.calls), calls)
        self.assertEqual(len(self.notes), 1)                                # a mesma issue nova não avisa de novo

    def test_error_is_silent_but_visible_in_status(self):
        self.import_one()
        self.c.apply_settings({"jira_auto_sync_min": 15})
        self.fake.status = 401
        self.c.poll_clock()
        self.assertFalse(self.c.jira_sync_status["ok"])
        self.assertIn("recusou", self.c.jira_sync_status["message"])
        self.assertEqual(self.notes, [])

    def test_does_not_overlap(self):
        self.import_one()
        self.c.apply_settings({"jira_auto_sync_min": 15})
        self.c._jira_syncing = True
        self.c.poll_clock()
        self.assertEqual(self.fake.calls, [])

    def test_not_configured_does_nothing(self):
        self.c.shutdown()
        self.c = self.make(jira_token="", jira_auto_sync_min=15)
        import os
        os.environ.pop("JIRA_API_TOKEN", None)
        self.c.poll_clock()
        self.assertEqual(self.fake.calls, [])

    def test_truncated_search_does_not_flag_missing(self):
        task_id = self.import_one()
        self.fake.pages = [[raw_issue(f"XYZ-{p}-{i}", project="XYZ") for i in range(2)] for p in range(jc.MAX_PAGES + 1)]
        items, error = self.preview()
        self.assertFalse(items.complete)
        self.c.jira_import(items)
        self.assertEqual(self.c.jira_link(task_id)["missing"], 0)           # ABC-1 não veio, mas a leitura foi cortada

    def test_resolve_conflict_use_jira_or_keep_mine(self):
        task_id = self.import_one()
        self.c.repo.update_task(task_id, title="Meu", estimate_min=45)
        self.fake.pages = [[raw_issue("ABC-1", summary="Time", seconds=7200)]]
        self.c.jira_import(self.preview()[0])
        self.assertEqual(self.c.jira_link(task_id)["conflicts"], "estimate,title")
        self.c.jira_resolve_conflict(task_id, "title", use_jira=True)
        self.assertEqual(self.c.repo.get_task(task_id)["title"], "Time")
        self.c.jira_resolve_conflict(task_id, "estimate", use_jira=False)
        self.assertEqual(self.c.repo.get_task(task_id)["estimate_min"], 45)
        self.assertEqual(self.c.jira_link(task_id)["conflicts"], "")
        self.assertEqual(self.writes(), [])
        with self.assertRaises(ValueError):
            self.c.jira_resolve_conflict(task_id, "outro", True)

    def test_pushing_fields_clears_their_conflict(self):
        task_id = self.import_one()
        self.c.repo.update_task(task_id, title="Meu")
        self.fake.pages = [[raw_issue("ABC-1", summary="Time")]]
        self.c.jira_import(self.preview()[0])
        self.assertEqual(self.c.jira_link(task_id)["conflicts"], "title")
        preview = self.c.jira_prepare_fields(task_id)
        preview["confirmed"] = True
        box = []
        self.c.jira_push(preview, lambda m, e: box.append(e))
        self.assertEqual((box, self.c.jira_link(task_id)["conflicts"]), ([None], ""))

    def test_focus_context_has_jira_key(self):
        task_id = self.import_one()
        self.c.focus(task_id)
        self.assertEqual(self.c.focus_context()["jira_key"], "ABC-1")
        plain = self.c.add_task("Sem Jira")
        self.c.focus(plain["id"])
        self.assertIsNone(self.c.focus_context()["jira_key"])


class ControllerHierarchyTest(J5Case):
    """Mesmo cenário do controlador, agora com épicos e sub-tarefas."""

    EPIC_PAGE = [raw_issue("ABC-10", summary="Plataforma", issue_type="Epic", level=1),
                 raw_issue("ABC-11", summary="Tarefa A", parent="ABC-10", parent_title="Plataforma"),
                 raw_issue("ABC-12", summary="Filha", issue_type="Subtarefa", level=-1, subtask=True,
                           parent="ABC-11", parent_type="Tarefa")]

    def test_import_creates_groups_subtasks_and_remembers_epic_mapping(self):
        self.fake.pages = [list(self.EPIC_PAGE)]
        items, _ = self.preview()
        result = self.c.jira_import(items)
        self.assertEqual((result["created"], result["groups"], result["subtasks"]), (1, 1, 1))
        group_id = self.c.settings["jira_epic_groups"]["ABC-10"]
        self.assertEqual(self.c.repo.get_group(group_id)["name"], "Plataforma")
        task_id = self.c.repo.jira_link_by_key("ABC-11")["task_id"]
        self.assertEqual(self.c.repo.get_task(task_id)["group_id"], group_id)
        self.assertEqual(self.c.repo.list_subtasks(task_id)[0]["jira_key"], "ABC-12")
        self.fake.pages = [list(self.EPIC_PAGE)]
        again, _ = self.preview()                                           # o mapa salvo evita grupo duplicado
        self.assertEqual({i.action for i in again}, {"same"})

    def test_project_choice_does_not_override_epic_group(self):
        self.fake.pages = [list(self.EPIC_PAGE) + [raw_issue("ABC-20", summary="Sem épico")]]
        items, _ = self.preview()
        other = self.c.repo.create_group("Trabalho")
        self.c.jira_import(items, {"ABC": other["id"]})
        epic_task = self.c.repo.get_task(self.c.repo.jira_link_by_key("ABC-11")["task_id"])
        loose = self.c.repo.get_task(self.c.repo.jira_link_by_key("ABC-20")["task_id"])
        self.assertNotEqual(epic_task["group_id"], other["id"])
        self.assertEqual(loose["group_id"], other["id"])

    def test_auto_sync_never_creates_groups_or_subtasks(self):
        self.c.apply_settings({"jira_auto_sync_min": 15})
        self.fake.pages = [list(self.EPIC_PAGE)]
        groups = len(self.c.repo.list_groups())
        self.c.poll_clock()
        self.assertEqual((len(self.c.repo.list_groups()), self.c.repo.list_jira_links()), (groups, []))
        self.assertEqual(self.c.conn.execute("SELECT COUNT(*) FROM subtasks").fetchone()[0], 0)
        self.assertEqual(self.c.jira_sync_status["new"], 2)
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
