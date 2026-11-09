import json
import unittest
from types import SimpleNamespace

from pomodoro.ai import claude_client as cc
from pomodoro.ai.summary import build_summary

from .ai_support import Seed


class FakeMessages:
    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error, self.calls = text, stop_reason, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


def client_with(**kwargs):
    messages = FakeMessages(**kwargs)
    return cc.ClaudeClient("sk-x", client=SimpleNamespace(messages=messages)), messages


class AuthenticationError(Exception):
    pass


class ClaudeClientTest(unittest.TestCase):
    def test_insights_request_shape_and_parsing(self):
        client, messages = client_with(text=json.dumps({"insights": ["Uma ", "", "Duas"]}))
        self.assertEqual(client.insights("resumo"), ["Uma", "Duas"])
        call = messages.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(call["output_config"]["effort"], "low")
        self.assertNotIn("thinking", call)

    def test_subtasks(self):
        payload = {"subtasks": [{"title": "Rascunho", "minutes": 25}, {"title": " ", "minutes": 5},
                                {"title": "Revisar", "minutes": 0}]}
        client, _ = client_with(text=json.dumps(payload))
        self.assertEqual(client.subtasks("Relatório"), [("Rascunho", 25), ("Revisar", None)])

    def test_answer(self):
        client, _ = client_with(text=json.dumps({"answer": " Cerca de 1h. "}))
        self.assertEqual(client.answer("quanto?", "resumo"), "Cerca de 1h.")

    def test_failures_become_ai_unavailable(self):
        for kwargs, fragment in (
            ({"text": "não é json"}, "formato inesperado"),
            ({"text": "[]"}, "formato inesperado"),
            ({"text": "{}", "stop_reason": "refusal"}, "recusou"),
            ({"text": "{}", "stop_reason": "max_tokens"}, "cortada"),
            ({"error": AuthenticationError("401")}, "chave da API foi recusada"),
            ({"error": RuntimeError("boom")}, "Não foi possível"),
            ({"text": json.dumps({"insights": []})}, "não devolveu"),
        ):
            client, _ = client_with(**kwargs)
            with self.assertRaises(cc.AIUnavailable) as ctx:
                client.insights("x")
            self.assertIn(fragment, str(ctx.exception), kwargs)

    def test_missing_key_or_sdk(self):
        with self.assertRaises(cc.AIUnavailable):
            cc.ClaudeClient("").insights("x")


class SummaryTest(unittest.TestCase):
    def test_summary_lists_only_aggregated_data(self):
        seed = Seed()
        try:
            self.assertIn("Sem tarefas", build_summary(seed.repo))
            seed.done(seed.work, "Escrever relatório", 30, 45, interrupted=1)
            text = build_summary(seed.repo)
            self.assertIn("[Trabalho] Escrever relatório: previsto 30 min, real 47 min, 1 interrupção(ões)", text)
        finally:
            seed.close()


if __name__ == "__main__":
    unittest.main()
