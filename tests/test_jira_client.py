import base64
import unittest

from pomodoro.jira import client as jc

from .jira_support import FakeJira, raw_issue

URL = "https://x.atlassian.net"


def make(fake, **kwargs):
    return jc.JiraClient(kwargs.get("url", URL), "eu@exemplo.com", "tok", transport=fake,
                         sleep=kwargs.get("sleep", lambda seconds: None))


class NormalizeUrlTest(unittest.TestCase):
    def test_accepts_and_cleans(self):
        self.assertEqual(jc.normalize_url("https://x.atlassian.net/"), URL)
        self.assertEqual(jc.normalize_url("  x.atlassian.net "), URL)
        self.assertEqual(jc.normalize_url("https://x.atlassian.net/?a=1#b"), URL)
        self.assertEqual(jc.normalize_url("http://localhost:8080"), "http://localhost:8080")

    def test_rejects(self):
        for bad in ("", "   ", "http://x.atlassian.net", "ftp://x.com"):
            with self.assertRaises(jc.JiraError, msg=bad):
                jc.normalize_url(bad)


class ClientTest(unittest.TestCase):
    def test_test_connection_uses_basic_auth(self):
        fake = FakeJira()
        self.assertEqual(make(fake).test_connection(), "Fabiano")
        call = fake.calls[0]
        self.assertEqual((call["method"], call["url"]), ("GET", URL + "/rest/api/2/myself"))
        expected = base64.b64encode(b"eu@exemplo.com:tok").decode()
        self.assertEqual(call["headers"]["Authorization"], "Basic " + expected)

    def test_search_default_jql_and_parsing(self):
        fake = FakeJira(pages=[[raw_issue("ABC-1", seconds=5400), raw_issue("ABC-2", seconds=None, description=None)]])
        issues = make(fake).search()
        body = fake.calls[0]["body"]
        self.assertEqual(fake.calls[0]["url"], URL + "/rest/api/2/search/jql")
        self.assertIn("currentUser()", body["jql"])
        self.assertIn("summary", body["fields"])
        first, second = issues
        self.assertEqual((first["key"], first["title"], first["estimate_min"], first["project_key"]),
                         ("ABC-1", "Corrigir login", 90, "ABC"))
        self.assertEqual(first["url"], URL + "/browse/ABC-1")
        self.assertEqual((second["estimate_min"], second["description"]), (None, ""))

    def test_search_custom_jql_and_pagination(self):
        fake = FakeJira(pages=[[raw_issue("ABC-1")], [raw_issue("ABC-2")]])
        issues = make(fake).search("project = ABC")
        self.assertEqual([i["key"] for i in issues], ["ABC-1", "ABC-2"])
        self.assertEqual(fake.calls[0]["body"]["jql"], "project = ABC")
        self.assertNotIn("nextPageToken", fake.calls[0]["body"])
        self.assertIn("nextPageToken", fake.calls[1]["body"])

    def test_adf_description_becomes_text(self):
        adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Olá"}]}]}
        issue = jc.parse_issue(raw_issue(description=adf), URL)
        self.assertEqual(issue["description"], "Olá")

    def test_only_reads(self):
        fake = FakeJira(pages=[[raw_issue()]])
        client = make(fake)
        client.test_connection()
        client.search()
        self.assertEqual({c["method"] for c in fake.calls} - {"GET"}, {"POST"})      # POST só na busca
        self.assertTrue(all("search" in c["url"] for c in fake.calls if c["method"] == "POST"))

    def test_friendly_errors(self):
        for status, fragment in ((401, "recusou"), (403, "recusou"), (404, "não encontrado"),
                                 (400, "JQL"), (500, "erro 500")):
            with self.assertRaises(jc.JiraError, msg=status) as ctx:
                make(FakeJira(status=status)).test_connection()
            self.assertIn(fragment, str(ctx.exception))
        with self.assertRaises(jc.JiraError) as ctx:
            make(FakeJira(status=429, headers={"Retry-After": "30"})).search()
        self.assertIn("30 s", str(ctx.exception))
        with self.assertRaises(jc.JiraError) as ctx:
            make(FakeJira(error=OSError("sem rede"))).test_connection()
        self.assertIn("Não consegui falar", str(ctx.exception))

    def test_missing_credentials_and_bad_payload(self):
        fake = FakeJira()
        with self.assertRaises(jc.JiraError):
            jc.JiraClient(URL, "", "tok", transport=fake).test_connection()
        with self.assertRaises(jc.JiraError):
            jc.JiraClient(URL, "a@b.c", "", transport=fake).search()
        self.assertEqual(fake.calls, [])
        with self.assertRaises(jc.JiraError):
            jc.JiraClient(URL, "a@b.c", "t", transport=lambda *a: (200, "<html>", {})).test_connection()


if __name__ == "__main__":
    unittest.main()
