"""Cliente opcional da API do Claude (SDK `anthropic`, importado só quando usado).

Envia apenas o resumo agregado (grupo, título, previsto e real). Qualquer falha vira AIUnavailable,
e quem chama cai na versão local. Não use em threads com o SQLite: monte o texto antes (summary) e
passe-o aqui.
"""

import json
import logging

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
MAX_TOKENS = 1500

SYSTEM = (
    "Você é o assistente de um app de Pomodoro para pessoas com TDAH. Responda sempre em português do Brasil, "
    "com frases curtas, acolhedoras e concretas, sem julgamento. Use somente os dados fornecidos; "
    "se faltarem dados, diga isso em vez de inventar."
)

INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {"insights": {"type": "array", "items": {"type": "string"}}},
    "required": ["insights"], "additionalProperties": False,
}
SUBTASKS_SCHEMA = {
    "type": "object",
    "properties": {"subtasks": {"type": "array", "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "minutes": {"type": "integer"}},
        "required": ["title", "minutes"], "additionalProperties": False}}},
    "required": ["subtasks"], "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"], "additionalProperties": False,
}


class AIUnavailable(Exception):
    """A IA na nuvem não está disponível (sem SDK, sem chave, sem rede, recusa ou resposta inválida)."""


class ClaudeClient:
    def __init__(self, api_key, model=DEFAULT_MODEL, client=None, timeout=30.0):
        self.model = model or DEFAULT_MODEL
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    # ---- infraestrutura -------------------------------------------------

    def _sdk(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise AIUnavailable("Falta a chave da API nas configurações.")
        try:
            import anthropic
        except ImportError as error:
            raise AIUnavailable("O pacote “anthropic” não está instalado (pip install anthropic).") from error
        self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout)
        return self._client

    def _ask(self, prompt, schema):
        client = self._sdk()
        try:
            response = client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except AIUnavailable:
            raise
        except Exception as error:
            raise AIUnavailable(_friendly(error)) from error
        if getattr(response, "stop_reason", None) == "refusal":
            raise AIUnavailable("O Claude recusou responder a este pedido.")
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise AIUnavailable("A resposta do Claude foi cortada. Tente novamente.")
        raw = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")
        try:
            data = json.loads(raw)
        except ValueError as error:
            raise AIUnavailable("A resposta do Claude veio em um formato inesperado.") from error
        if not isinstance(data, dict):
            raise AIUnavailable("A resposta do Claude veio em um formato inesperado.")
        return data

    # ---- funções --------------------------------------------------------

    def test_connection(self):
        """Faz uma chamada mínima; levanta AIUnavailable se algo estiver errado."""
        self._ask("Responda apenas {\"answer\": \"ok\"}.", ANSWER_SCHEMA)
        return True

    def insights(self, summary):
        data = self._ask(
            f"{summary}\n\nEscreva de 3 a 5 percepções curtas (uma frase cada) sobre como esta pessoa estima "
            "e executa tarefas, com um conselho prático quando fizer sentido.", INSIGHTS_SCHEMA)
        items = [str(i).strip() for i in data.get("insights", []) if str(i).strip()]
        if not items:
            raise AIUnavailable("O Claude não devolveu percepções.")
        return items[:5]

    def subtasks(self, title, summary=""):
        data = self._ask(
            f"{summary}\n\nQuebre a tarefa “{title}” em 3 a 6 passos pequenos e concretos, cada um com a duração "
            "estimada em minutos (múltiplos de 5, de 5 a 60), considerando o ritmo desta pessoa.", SUBTASKS_SCHEMA)
        result = []
        for item in data.get("subtasks", []):
            step = str(item.get("title", "")).strip()
            minutes = item.get("minutes")
            if step:
                result.append((step[:200], int(minutes) if isinstance(minutes, int) and minutes > 0 else None))
        if not result:
            raise AIUnavailable("O Claude não devolveu passos.")
        return result[:8]

    def answer(self, question, summary):
        data = self._ask(f"{summary}\n\nPergunta: {question}\n\nResponda em até 3 frases.", ANSWER_SCHEMA)
        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise AIUnavailable("O Claude não devolveu resposta.")
        return answer


def _friendly(error):
    name = type(error).__name__
    messages = {
        "AuthenticationError": "A chave da API foi recusada. Confira-a nas configurações.",
        "PermissionDeniedError": "A chave não tem permissão para usar este modelo.",
        "NotFoundError": "Modelo não encontrado. Escolha outro nas configurações.",
        "RateLimitError": "Limite de uso da API atingido. Tente de novo em instantes.",
        "APIConnectionError": "Sem conexão com a API do Claude.",
        "APITimeoutError": "A API do Claude demorou demais para responder.",
        "BadRequestError": "A API recusou o pedido (verifique o modelo escolhido).",
    }
    log.warning("falha na API do Claude: %s: %s", name, error)
    return messages.get(name, "Não foi possível falar com o Claude agora.")
