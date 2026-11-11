"""Apoio aos testes do Jira: um Jira simulado que entra no lugar do transporte HTTP."""

import json


def raw_issue(key="ABC-1", summary="Corrigir login", status="To Do", category="new", seconds=3600,
              description="Detalhes", updated="2026-11-10T10:00:00.000-0300", project="ABC"):
    fields = {
        "summary": summary, "description": description,
        "status": {"name": status, "statusCategory": {"key": category}},
        "project": {"key": project, "name": "Projeto " + project},
        "updated": updated, "issuetype": {"name": "Task"},
    }
    if seconds is not None:
        fields["timetracking"] = {"originalEstimateSeconds": seconds}
    return {"id": key.split("-")[1] + "00", "key": key, "fields": fields}


def parsed_issue(**kwargs):
    from pomodoro.jira.client import parse_issue
    return parse_issue(raw_issue(**kwargs), "https://x.atlassian.net")


class FakeJira:
    """Transporte falso: guarda as chamadas e responde com o que foi preparado."""

    def __init__(self, pages=None, status=200, myself=None, error=None, headers=None, write_status=None,
                 write_body="{}", transitions=None):
        self.write_status, self.write_body = write_status, write_body
        self.transitions = transitions if transitions is not None else [
            {"id": "11", "name": "Iniciar", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
            {"id": "31", "name": "Concluir", "to": {"name": "Done", "statusCategory": {"key": "done"}}}]
        self.pages = list(pages or [[]])
        self.status, self.error, self.headers = status, error, headers or {}
        self.myself = myself or {"displayName": "Fabiano"}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        if self.error:
            raise self.error
        if self.status != 200:
            return self.status, "{}", self.headers
        if url.endswith("/transitions") and method == "GET":
            return 200, json.dumps({"transitions": self.transitions}), {}
        if method in ("PUT", "POST") and "/issue/" in url:
            if self.write_status:
                return self.write_status, self.write_body, {}
            return (201, '{"id": "900"}', {}) if url.endswith("/comment") else (204, "", {})
        if url.endswith("/myself"):
            return 200, json.dumps(self.myself), {}
        page = self.pages.pop(0) if self.pages else []
        data = {"issues": page, "isLast": not self.pages}
        if self.pages:
            data["nextPageToken"] = f"t{len(self.calls)}"
        return 200, json.dumps(data), {}
