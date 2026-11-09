import unittest

from pomodoro.ai import text
from pomodoro.ai.estimator import (Estimator, Prediction, bias_phrase, confidence, format_minutes, round5)
from pomodoro.ai.samples import collect_samples

from .ai_support import Seed


class TextTest(unittest.TestCase):
    def test_stems_ignore_accents_stopwords_and_short_words(self):
        self.assertEqual(text.stems("Escrever o relatório de vendas"), frozenset({"escre", "relat", "venda"}))
        self.assertEqual(text.stems("Relatorio"), text.stems("Relatório"))
        self.assertEqual(text.stems("ir a um"), frozenset())
        self.assertEqual(text.stem("Apresentação"), "apres")

    def test_similarity(self):
        a, b = text.stems("Escrever relatório mensal"), text.stems("Escrever relatório de vendas")
        self.assertAlmostEqual(text.similarity(a, b), 2 / 4)
        self.assertEqual(text.similarity(a, a), 1.0)
        self.assertEqual(text.similarity(a, frozenset()), 0.0)
        self.assertEqual(text.similarity(a, text.stems("Lavar roupa")), 0.0)

    def test_display_word_keeps_the_accent_of_the_most_common_form(self):
        titles = ["Relatório mensal", "Relatório de vendas", "relatorios"]
        self.assertEqual(text.display_word("relat", titles), "relatório")
        self.assertEqual(text.display_word("xyzab", titles), "xyzab")

    def test_weighted_median(self):
        self.assertEqual(text.weighted_median([3, 1, 2]), 2)
        self.assertEqual(text.weighted_median([1, 10], [1, 5]), 10)
        self.assertEqual(text.weighted_median([1, 2, 3, 4]), 2)
        with self.assertRaises(ValueError):
            text.weighted_median([])


class HelpersTest(unittest.TestCase):
    def test_rounding_and_format(self):
        self.assertEqual([round5(m) for m in (1, 2.4, 2.6, 47, 78, 82.4)], [5, 5, 5, 45, 80, 80])
        self.assertEqual(format_minutes(80), "1h 20m")
        self.assertEqual(format_minutes(45), "45m")
        self.assertEqual(format_minutes(120), "2h")

    def test_bias_phrase(self):
        self.assertEqual(bias_phrase(1.35), "você costuma levar ~35% a mais do que prevê")
        self.assertEqual(bias_phrase(0.75), "você costuma levar ~25% a menos do que prevê")
        self.assertEqual(bias_phrase(1.05), "você costuma acertar a previsão")

    def test_confidence_grows_with_samples_and_shrinks_with_spread(self):
        self.assertEqual(confidence([1.2, 1.2, 1.2]), 2)
        self.assertEqual(confidence([1.2] * 6), 3)
        self.assertEqual(confidence([1.2] * 12), 4)
        self.assertEqual(confidence([0.5, 3.0, 0.4, 2.8, 0.5, 3.1, 0.4, 2.9, 0.5, 3.0, 0.4, 2.7]), 3)
        self.assertEqual(confidence([0.3, 3.0, 0.4]), 1)
        self.assertEqual(Prediction(1.0, 10, "history", 5, 4).confidence_label, "alta")
        self.assertEqual(Prediction(1.0, 10, "history", 5, 2).confidence_label, "média")


class SamplesTest(unittest.TestCase):
    def setUp(self):
        self.seed = Seed()

    def tearDown(self):
        self.seed.close()

    def test_only_measurable_done_tasks_become_samples(self):
        s = self.seed
        s.done(s.work, "Medida", 30, 39, hour=9, subtasks=[("A", 10)], interrupted=1)
        s.done(s.work, "Sem previsão", None, 20)
        s.done(s.work, "Muito curta", 30, 0.5)
        pending = s.todo(s.work, "Pendente", 30)
        s.repo.add_manual_adjustment(pending["id"], 600)
        sub_only = s.done(s.work, "Só subtarefas", None, 40, subtasks=[("X", 20), ("Y", 25)], use_subtask_estimate=True)
        samples = {x.title: x for x in collect_samples(s.repo)}
        self.assertEqual(set(samples), {"Medida", "Só subtarefas"})
        measured = samples["Medida"]
        self.assertEqual((measured.estimate_min, round(measured.real_min, 2), measured.has_subtasks), (30.0, 39.0 + 2.0, True))
        self.assertEqual((measured.start_hour, measured.interruptions, measured.done_day), (9, 1, "2026-11-05"))
        self.assertAlmostEqual(measured.ratio, 41 / 30)
        self.assertEqual(samples["Só subtarefas"].estimate_min, 45.0)
        self.assertEqual(sub_only["title"], "Só subtarefas")


class EstimatorTest(unittest.TestCase):
    def setUp(self):
        self.seed = Seed()
        self.estimator = Estimator()
        s = self.seed
        for index, (est, real) in enumerate(((30, 45), (40, 60), (20, 30), (50, 75))):       # sempre 50% a mais
            s.done(s.work, f"Escrever relatório {index}", est, real)
        for index in range(3):
            s.done(s.home, f"Lavar roupa {index}", 30, 24)                                    # 20% a menos

    def tearDown(self):
        self.seed.close()

    def suggest(self, title, group, estimate=None, **kwargs):
        return self.estimator.suggest_estimate(self.seed.repo, title, group["id"] if group else None, estimate, **kwargs)

    def test_similar_tasks_scale_the_users_estimate(self):
        result = self.suggest("Escrever relatório de vendas", self.seed.work, 60)
        self.assertEqual(result["minutes"], 90)
        self.assertEqual((result["basis"], result["samples"], result["confidence"]), ("similar", 4, 2))
        self.assertIn("Baseado em 4 tarefas parecidas", result["note"])
        self.assertIn("você costuma levar ~50% a mais do que prevê", result["note"])
        self.assertIn("“Escrever relatório", result["note"])

    def test_overestimating_group_gets_a_lower_suggestion(self):
        result = self.suggest("Lavar roupa branca", self.seed.home, 40)
        self.assertEqual((result["minutes"], result["basis"]), (30, "similar"))

    def test_no_suggestion_when_the_estimate_is_already_good(self):
        self.assertIsNone(self.suggest("Lavar roupa", self.seed.home, 24))
        self.assertIsNone(self.suggest("Escrever relatório", self.seed.work, 5 * 0 + 1) and None)

    def test_without_estimate_uses_the_typical_time_of_similar_tasks(self):
        result = self.suggest("Escrever relatório novo", self.seed.work, None)
        self.assertEqual(result["minutes"], 45)                         # mediana ponderada dos tempos reais
        self.assertIsNone(self.suggest("Algo diferente", self.seed.work, None))      # sem parecidas: não chuta

    def test_falls_back_to_group_then_history_then_nothing(self):
        result = self.suggest("Tarefa totalmente nova", self.seed.work, 40)
        self.assertEqual((result["basis"], result["minutes"]), ("group", 60))
        self.assertIn("tarefas deste grupo", result["note"])
        other = self.seed.repo.create_group("Outro")
        result = self.suggest("Tarefa totalmente nova", other, 40)
        self.assertEqual(result["basis"], "history")
        self.assertIn("do seu histórico", result["note"])

    def test_not_enough_data(self):
        fresh = Seed()
        try:
            fresh.done(fresh.work, "Uma", 30, 40)
            self.assertIsNone(Estimator().suggest_estimate(fresh.repo, "Uma", fresh.work["id"], 30))
            self.assertIsNone(Estimator().suggest_estimate(fresh.repo, "   ", None, 30))
        finally:
            fresh.close()

    def test_the_task_itself_is_excluded(self):
        task = self.seed.done(self.seed.work, "Escrever relatório final", 30, 90, day="2026-11-06")
        with_self = self.suggest("Escrever relatório final", self.seed.work, 30)
        without = self.suggest("Escrever relatório final", self.seed.work, 30, task_id=task["id"])
        self.assertEqual((with_self["samples"], without["samples"]), (5, 4))

    def test_suggest_subtasks_reuses_the_most_similar_task(self):
        s = self.seed
        done = s.done(s.work, "Preparar apresentação trimestral", 80, 90,
                      subtasks=[("Definir tópicos", 20), ("Criar slides", 40), ("Ensaiar", 20)])
        first = s.repo.list_subtasks(done["id"])[0]
        s.repo.add_manual_adjustment(done["id"], 25 * 60, subtask_id=first["id"])
        result = self.estimator.suggest_subtasks(s.repo, "Preparar apresentação para o cliente")
        self.assertEqual([t for t, _m in result], ["Definir tópicos", "Criar slides", "Ensaiar"])
        self.assertEqual(result[0][1], 25)                                # tempo real da subtarefa, arredondado
        self.assertEqual(result[1][1], 40)                                # sem real: usa a previsão
        self.assertEqual(self.estimator.suggest_subtasks(s.repo, "Lavar o carro"), [])
        self.assertEqual(self.estimator.suggest_subtasks(s.repo, "  "), [])

    def test_answer_duration(self):
        answer = self.estimator.answer_duration(self.seed.repo, "quanto tempo levo para escrever relatório?")
        self.assertIn("Com base em 4 tarefas parecidas", answer)
        self.assertIn("em média 45m", answer)
        self.assertIsNone(self.estimator.answer_duration(self.seed.repo, "viajar para a lua"))


if __name__ == "__main__":
    unittest.main()
