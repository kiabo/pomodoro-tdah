import unittest

from pomodoro.jira import client as jc, push

from .jira_support import FakeJira

URL = "https://x.atlassian.net"
TASK = {"id": "t1", "title": "Meu título", "notes": "  Plano:\n1. um\n2. dois ", "estimate_min": 90}
LINK = {"issue_key": "ABC-1", "remote_title": "Título do Jira", "remote_estimate_min": 60,
        "remote_status": "To Do"}


def make(fake):
    return jc.JiraClient(URL, "eu@exemplo.com", "tok", transport=fake)


class ClientWriteTest(unittest.TestCase):
    def test_add_comment(self):
        fake = FakeJira()
        self.assertEqual(make(fake).add_comment("ABC-1", "Olá"), "900")
        call = fake.calls[0]
        self.assertEqual((call["method"], call["url"], call["body"]),
                         ("POST", URL + "/rest/api/2/issue/ABC-1/comment", {"body": "Olá"}))

    def test_transitions_and_transition(self):
        fake = FakeJira()
        client = make(fake)
        found = client.transitions("ABC-1")
        self.assertEqual([(t["id"], t["to_status"], t["to_category"]) for t in found],
                         [("11", "In Progress", "indeterminate"), ("31", "Done", "done")])
        client.transition("ABC-1", "31")
        self.assertEqual(fake.calls[-1]["body"], {"transition": {"id": "31"}})

    def test_update_fields(self):
        fake = FakeJira()
        make(fake).update_fields("ABC-1", title=" Novo ", estimate_min=90)
        call = fake.calls[0]
        self.assertEqual(call["method"], "PUT")
        self.assertEqual(call["body"], {"fields": {"summary": "Novo", "timetracking": {"originalEstimate": "90m"}}})
        make(fake).update_fields("ABC-1")
        self.assertEqual(len(fake.calls), 1)               # nada a enviar: nem chama

    def test_empty_values_are_refused_before_any_call(self):
        fake = FakeJira()
        for call in (lambda c: c.add_comment("ABC-1", "  "), lambda c: c.update_fields("ABC-1", title=" "),
                     lambda c: c.add_comment("../x", "oi")):
            with self.assertRaises(jc.JiraError):
                call(make(fake))
        self.assertEqual(fake.calls, [])

    def test_write_errors_are_explained(self):
        with self.assertRaises(jc.JiraError) as ctx:
            make(FakeJira(write_status=403)).add_comment("ABC-1", "x")
        self.assertIn("permissão", str(ctx.exception))
        body = '{"errorMessages": [], "errors": {"timetracking": "Estimativa desligada."}}'
        with self.assertRaises(jc.JiraError) as ctx:
            make(FakeJira(write_status=400, write_body=body)).update_fields("ABC-1", estimate_min=5)
        self.assertIn("Estimativa desligada.", str(ctx.exception))


class PushPreviewTest(unittest.TestCase):
    def test_comment_preview(self):
        preview = push.comment_preview(TASK, LINK)
        self.assertEqual((preview["kind"], preview["text"], preview["confirmed"]),
                         ("comment", "Plano:\n1. um\n2. dois", False))
        with self.assertRaises(ValueError):
            push.comment_preview({**TASK, "notes": "  "}, LINK)

    def test_fields_preview_only_lists_differences(self):
        preview = push.fields_preview(TASK, LINK)
        self.assertEqual([(c["field"], c["before"], c["after"]) for c in preview["changes"]],
                         [("title", "Título do Jira", "Meu título"), ("estimate", "1h", "1h 30min")])
        same = push.fields_preview({**TASK, "estimate_min": 60}, LINK)
        self.assertEqual([c["field"] for c in same["changes"]], ["title"])
        with self.assertRaises(ValueError):
            push.fields_preview({**TASK, "title": "Título do Jira", "estimate_min": None}, LINK)

    def test_status_preview_needs_options(self):
        with self.assertRaises(ValueError):
            push.status_preview(TASK, LINK, [])

    def test_nothing_runs_without_confirmation(self):
        fake = FakeJira()
        client = make(fake)
        for preview in (push.comment_preview(TASK, LINK), push.fields_preview(TASK, LINK)):
            with self.assertRaises(ValueError):
                push.execute(client, preview)
        self.assertEqual(fake.calls, [])

    def test_unselected_changes_are_not_sent(self):
        fake = FakeJira()
        preview = push.fields_preview(TASK, LINK)
        preview["changes"][0]["selected"] = False
        preview["confirmed"] = True
        push.execute(make(fake), preview)
        self.assertEqual(fake.calls[0]["body"], {"fields": {"timetracking": {"originalEstimate": "90m"}}})
        preview["changes"][1]["selected"] = False
        with self.assertRaises(ValueError):
            push.execute(make(fake), preview)

    def test_status_needs_a_valid_choice(self):
        preview = push.status_preview(TASK, LINK, make(FakeJira()).transitions("ABC-1"))
        preview["confirmed"] = True
        with self.assertRaises(ValueError):
            push.validate(preview)
        preview["transition_id"] = "999"
        with self.assertRaises(ValueError):
            push.validate(preview)


if __name__ == "__main__":
    unittest.main()
