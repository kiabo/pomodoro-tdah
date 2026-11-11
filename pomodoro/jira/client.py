"""Cliente mínimo da API REST v2 do Jira Cloud (e-mail + API token), só com a biblioteca padrão.

Lê (testar a conexão, buscar as issues) e escreve apenas o que o usuário confirmou na tela:
comentar, mudar o status, atualizar título e previsão. Qualquer falha vira JiraError com uma
mensagem em português. O transporte HTTP é injetável para os testes não usarem a rede.
Rode em thread, nunca junto com o SQLite.
"""

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_JQL = "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"
SEARCH_FIELDS = ["summary", "description", "status", "project", "timetracking", "updated", "issuetype"]
PAGE_SIZE = 100
MAX_PAGES = 10
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
MAX_RETRIES = 2          # novas tentativas quando o Jira pede para esperar (429)
MAX_WAIT_SECONDS = 30    # espera máxima aceita por tentativa; acima disso, desiste com uma mensagem


class JiraError(Exception):
    """O Jira não está disponível (configuração incompleta, rede, credenciais ou resposta inválida)."""


def normalize_url(url):
    """https://empresa.atlassian.net/ -> https://empresa.atlassian.net. Levanta JiraError se inválida."""
    text = (url or "").strip()
    if text and "://" not in text:
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    host = parts.hostname or ""
    if not host:
        raise JiraError("Informe o endereço do Jira, como https://empresa.atlassian.net.")
    if parts.scheme != "https" and not (parts.scheme == "http" and host in LOCAL_HOSTS):
        raise JiraError("O endereço do Jira precisa começar com https:// (o token não pode viajar sem criptografia).")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _urllib_transport(method, url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), dict(error.headers or {})


def _text(value):
    """Descrição como texto: a API v2 devolve texto, mas protege contra o formato ADF."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []) or []:
                walk(child)
            if node.get("type") in ("paragraph", "heading", "listItem"):
                parts.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return "".join(parts).strip()


def parse_issue(raw, base_url):
    """Converte a issue crua da API no dicionário que o app usa."""
    fields = raw.get("fields") or {}
    status = fields.get("status") or {}
    project = fields.get("project") or {}
    seconds = (fields.get("timetracking") or {}).get("originalEstimateSeconds") or 0
    key = raw["key"]
    return {
        "key": key,
        "id": str(raw.get("id") or ""),
        "title": (fields.get("summary") or "").strip() or key,
        "description": _text(fields.get("description")),
        "status": status.get("name") or "",
        "status_category": ((status.get("statusCategory") or {}).get("key") or ""),
        "project_key": project.get("key") or key.rsplit("-", 1)[0],
        "project_name": project.get("name") or "",
        "estimate_min": round(seconds / 60) if seconds else None,
        "updated": fields.get("updated") or "",
        "issue_type": (fields.get("issuetype") or {}).get("name") or "",
        "url": f"{base_url}/browse/{key}",
    }


def _retry_after(headers, default):
    """Segundos que o Jira pediu para esperar (cabeçalho Retry-After), ou `default`."""
    value = {k.lower(): v for k, v in (headers or {}).items()}.get("retry-after")
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return default


def _reason(text):
    """Motivo que o Jira dá para recusar uma alteração (errorMessages / errors), ou ''."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    messages = [m for m in data.get("errorMessages") or [] if isinstance(m, str)]
    messages += [f"{v}" for v in (data.get("errors") or {}).values() if isinstance(v, str)]
    return "O Jira recusou: " + " ".join(messages) if messages else ""


def _key_path(issue_key):
    key = (issue_key or "").strip()
    if not key or "/" in key or "?" in key:
        raise JiraError("Chave de issue inválida.")
    return urllib.parse.quote(key)


class JiraClient:
    def __init__(self, base_url, email, token, transport=None, timeout=30.0, sleep=time.sleep):
        self._sleep = sleep
        self.truncated = False          # a última busca parou no limite de páginas (faltou ler issues)
        self.email = (email or "").strip()
        self._token = (token or "").strip()
        self._url = base_url
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    @property
    def base_url(self):
        return normalize_url(self._url)

    def _request(self, method, path, payload=None, write=False):
        base = self.base_url
        if not self.email or not self._token:
            raise JiraError("Falta o e-mail ou o token do Jira nas configurações.")
        credentials = base64.b64encode(f"{self.email}:{self._token}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(MAX_RETRIES + 1):
            try:
                status, text, response_headers = self._transport(method, base + path, headers, body, self._timeout)
            except JiraError:
                raise
            except Exception as error:
                log.warning("falha de rede no Jira: %s", error)
                raise JiraError("Não consegui falar com o Jira. Confira a internet e o endereço.") from error
            if status != 429 or attempt == MAX_RETRIES:
                break
            wait = _retry_after(response_headers, default=2.0 * (attempt + 1))
            if wait > MAX_WAIT_SECONDS:
                break
            log.info("Jira pediu para esperar %.0f s (tentativa %d)", wait, attempt + 1)
            self._sleep(wait)      # o 429 recusa o pedido antes de processá-lo, então repetir é seguro
        if status == 403 and write:
            raise JiraError("Sua conta não tem permissão para fazer isso nesta issue.")
        if status in (401, 403):
            raise JiraError("O Jira recusou o e-mail ou o token. Confira os dois (o token é o da API, não a senha).")
        if status == 404:
            raise JiraError("Endereço do Jira não encontrado. Confira a URL nas configurações.")
        if status == 429:
            wait = {k.lower(): v for k, v in (response_headers or {}).items()}.get("retry-after")
            raise JiraError("O Jira pediu para esperar um pouco" + (f" ({wait} s)." if wait else ".")
                            + " Tente de novo daqui a pouco.")
        if status == 400 and write:
            raise JiraError(_reason(text) or "O Jira não aceitou essa alteração.")
        if status == 400:
            raise JiraError("O Jira não entendeu a busca. Confira a JQL nas configurações.")
        if status >= 400:
            raise JiraError(f"O Jira respondeu com erro {status}.")
        if status == 204 or not (text or "").strip():
            return {}
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError) as error:
            raise JiraError("O Jira devolveu uma resposta inesperada. Confira se o endereço é o do Jira.") from error
        if not isinstance(data, dict):
            raise JiraError("O Jira devolveu uma resposta inesperada.")
        return data

    def test_connection(self):
        """Nome de quem está conectado."""
        data = self._request("GET", "/rest/api/2/myself")
        return data.get("displayName") or data.get("emailAddress") or self.email

    def search(self, jql=None):
        """Issues que casam com a JQL (padrão: as minhas em aberto), já convertidas."""
        base = self.base_url
        issues, token = [], None
        self.truncated = False
        for page in range(MAX_PAGES):
            payload = {"jql": (jql or "").strip() or DEFAULT_JQL, "fields": SEARCH_FIELDS, "maxResults": PAGE_SIZE}
            if token:
                payload["nextPageToken"] = token
            data = self._request("POST", "/rest/api/2/search/jql", payload)
            for raw in data.get("issues") or []:
                if isinstance(raw, dict) and raw.get("key"):
                    issues.append(parse_issue(raw, base))
            token = data.get("nextPageToken")
            if not token or data.get("isLast"):
                break
            self.truncated = page == MAX_PAGES - 1
        return issues

    # ---- escrita: só o que o usuário confirmou ---------------------------

    def add_comment(self, issue_key, text):
        """Acrescenta um comentário (não altera nada que já existe). Devolve o id do comentário."""
        if not (text or "").strip():
            raise JiraError("O comentário está vazio.")
        data = self._request("POST", f"/rest/api/2/issue/{_key_path(issue_key)}/comment", {"body": text}, write=True)
        return str(data.get("id") or "")

    def transitions(self, issue_key):
        """[{id, name, to_status, to_category}] das mudanças de status possíveis agora."""
        data = self._request("GET", f"/rest/api/2/issue/{_key_path(issue_key)}/transitions")
        result = []
        for raw in data.get("transitions") or []:
            target = raw.get("to") or {}
            result.append({"id": str(raw.get("id")), "name": raw.get("name") or target.get("name") or "",
                           "to_status": target.get("name") or "",
                           "to_category": (target.get("statusCategory") or {}).get("key") or ""})
        return result

    def transition(self, issue_key, transition_id):
        self._request("POST", f"/rest/api/2/issue/{_key_path(issue_key)}/transitions",
                      {"transition": {"id": str(transition_id)}}, write=True)

    def update_fields(self, issue_key, title=None, estimate_min=None):
        """Atualiza só o que foi passado: título (summary) e/ou previsão original em minutos."""
        fields = {}
        if title is not None:
            if not title.strip():
                raise JiraError("O título não pode ficar vazio.")
            fields["summary"] = title.strip()
        if estimate_min is not None:
            fields["timetracking"] = {"originalEstimate": f"{int(estimate_min)}m"}
        if not fields:
            return
        self._request("PUT", f"/rest/api/2/issue/{_key_path(issue_key)}", {"fields": fields}, write=True)

    def add_worklog(self, issue_key, seconds, started, comment=""):
        """Lança tempo trabalhado. started no formato do Jira (2026-11-11T14:00:00.000-0300). Devolve o id."""
        if seconds < 60:
            raise JiraError("O Jira só aceita lançamentos de pelo menos 1 minuto.")
        payload = {"timeSpentSeconds": int(seconds), "started": started}
        if comment:
            payload["comment"] = comment
        data = self._request("POST", f"/rest/api/2/issue/{_key_path(issue_key)}/worklog", payload, write=True)
        return str(data.get("id") or "")

    def subtask_types(self, project_key):
        """[{id, name}] dos tipos de sub-tarefa que o projeto aceita."""
        data = self._request("GET", f"/rest/api/2/project/{_key_path(project_key)}")
        types = [{"id": str(t.get("id")), "name": t.get("name") or ""}
                 for t in data.get("issueTypes") or [] if t.get("subtask")]
        if not types:
            raise JiraError("Este projeto do Jira não permite sub-tarefas.")
        return types

    def create_subtask(self, parent_key, project_key, title, type_id, estimate_min=None):
        """Cria uma sub-tarefa filha de parent_key. Devolve a chave criada (ex.: ABC-12)."""
        if not (title or "").strip():
            raise JiraError("O título da subtarefa está vazio.")
        fields = {"project": {"key": project_key}, "parent": {"key": parent_key}, "issuetype": {"id": str(type_id)},
                  "summary": title.strip()}
        if estimate_min:
            fields["timetracking"] = {"originalEstimate": f"{int(estimate_min)}m"}
        data = self._request("POST", "/rest/api/2/issue", {"fields": fields}, write=True)
        if not data.get("key"):
            raise JiraError("O Jira não devolveu a chave da subtarefa criada.")
        return data["key"]

    def subtasks_of(self, issue_key):
        """[{key, title, done}] das sub-tarefas que já existem no Jira (leitura)."""
        data = self._request("GET", f"/rest/api/2/issue/{_key_path(issue_key)}?fields=subtasks")
        result = []
        for raw in (data.get("fields") or {}).get("subtasks") or []:
            fields = raw.get("fields") or {}
            category = ((fields.get("status") or {}).get("statusCategory") or {}).get("key")
            result.append({"key": raw.get("key"), "title": (fields.get("summary") or raw.get("key") or "").strip(),
                           "done": category == "done"})
        return [r for r in result if r["key"]]
