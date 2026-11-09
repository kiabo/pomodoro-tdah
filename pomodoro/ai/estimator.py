"""Estimador local: aprende com o seu histórico (previsto × real) e sugere tempos. Funciona sem internet.

Para uma tarefa nova ele procura, em ordem, tarefas parecidas (mesmas palavras), tarefas do mesmo grupo e
o histórico todo. Do melhor conjunto com amostras suficientes tira a razão real ÷ previsto e a aplica à
previsão do usuário. A confiança depende de quantas amostras há e de quão regulares elas são.
"""

from dataclasses import dataclass, field

from . import text
from .samples import collect_samples

MIN_SIMILAR = 3          # tarefas parecidas para confiar na semelhança
MIN_GROUP = 3
MIN_HISTORY = 5
SIMILARITY_MIN = 0.34
TOLERANCE = 0.10         # diferenças menores que isso não viram sugestão
CONFIDENCE_LABELS = {1: "baixa", 2: "média", 3: "alta", 4: "alta"}


def round5(minutes):
    return max(int(round(minutes / 5.0)) * 5, 5)


def format_minutes(minutes):
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest}m"
    return f"{hours}h" if rest == 0 else f"{hours}h {rest:02d}m"


@dataclass
class Prediction:
    ratio: float                 # real ÷ previsto típico
    typical_minutes: float       # tempo real típico dessas tarefas
    basis: str                   # "similar" | "group" | "history"
    samples: int
    confidence: int              # 1 a 4
    examples: list = field(default_factory=list)

    @property
    def confidence_label(self):
        return CONFIDENCE_LABELS[self.confidence]


def confidence(ratios):
    """Nível 1–4: mais amostras e mais regularidade = mais confiança."""
    n = len(ratios)
    mean = sum(ratios) / n
    spread = (sum((r - mean) ** 2 for r in ratios) / n) ** 0.5 / mean if mean else 1.0
    level = 2 if n < 6 else 3
    if n >= 10 and spread < 0.35:
        level += 1
    if spread > 0.8:
        level -= 1
    return min(max(level, 1), 4)


def bias_phrase(ratio):
    """'você costuma levar ~35% a mais do que prevê' / 'menos' / 'quase exatamente o previsto'."""
    if ratio >= 1 + TOLERANCE:
        return f"você costuma levar ~{round((ratio - 1) * 100)}% a mais do que prevê"
    if ratio <= 1 - TOLERANCE:
        return f"você costuma levar ~{round((1 - ratio) * 100)}% a menos do que prevê"
    return "você costuma acertar a previsão"


class Estimator:
    # ---- previsão -------------------------------------------------------

    def collect(self, repo):
        return collect_samples(repo)

    def predict_from(self, samples, title, group_id=None, exclude_task_id=None):
        """Melhor Prediction possível para `title` com essas amostras, ou None se faltam dados."""
        samples = [s for s in samples if s.task_id != exclude_task_id]
        target = text.stems(title)
        scored = [(text.similarity(target, s.stems), s) for s in samples]
        similar = [(score, s) for score, s in scored if score >= SIMILARITY_MIN]
        if len(similar) >= MIN_SIMILAR:
            chosen, weights, basis = [s for _score, s in similar], [score for score, _s in similar], "similar"
        else:
            in_group = [s for s in samples if group_id is not None and s.group_id == group_id]
            if len(in_group) >= MIN_GROUP:
                chosen, weights, basis = in_group, None, "group"
            elif len(samples) >= MIN_HISTORY:
                chosen, weights, basis = samples, None, "history"
            else:
                return None
        ratios = [s.ratio for s in chosen]
        examples = [s.title for s in sorted(chosen, key=lambda s: -text.similarity(target, s.stems))[:2]] \
            if basis == "similar" else []
        return Prediction(
            ratio=text.weighted_median(ratios, weights),
            typical_minutes=text.weighted_median([s.real_min for s in chosen], weights),
            basis=basis, samples=len(chosen), confidence=confidence(ratios), examples=examples,
        )

    def note_for(self, prediction):
        where = {"similar": f"{prediction.samples} tarefas parecidas",
                 "group": f"{prediction.samples} tarefas deste grupo",
                 "history": f"{prediction.samples} tarefas do seu histórico"}[prediction.basis]
        quoted = ", ".join(f"“{t}”" for t in prediction.examples)
        origin = f"Baseado em {where}" + (f" ({quoted})" if quoted else "")
        return f"{origin}: {bias_phrase(prediction.ratio)}."

    def suggest_estimate(self, repo, title, group_id=None, user_estimate_min=None, task_id=None):
        """{"minutes", "note", "confidence", "basis", "samples"} ou None (sem dados ou já está bom)."""
        if not (title or "").strip():
            return None
        prediction = self.predict_from(self.collect(repo), title, group_id, exclude_task_id=task_id)
        if prediction is None:
            return None
        if user_estimate_min:
            minutes = round5(user_estimate_min * prediction.ratio)
            if abs(minutes - user_estimate_min) < max(5, TOLERANCE * user_estimate_min):
                return None
        elif prediction.basis == "similar":
            minutes = round5(prediction.typical_minutes)
        else:
            return None                      # sem previsão do usuário e sem tarefas parecidas: não chuta
        return {"minutes": minutes, "note": self.note_for(prediction), "confidence": prediction.confidence,
                "basis": prediction.basis, "samples": prediction.samples}

    # ---- subtarefas -----------------------------------------------------

    def suggest_subtasks(self, repo, title, group_id=None, limit=8):
        """Reaproveita as subtarefas da tarefa concluída mais parecida: [(título, minutos ou None)]."""
        target = text.stems(title)
        if not target:
            return []
        best, best_score = None, 0.0
        for sample in self.collect(repo):
            score = text.similarity(target, sample.stems)
            if sample.has_subtasks and score >= 0.5 and score > best_score:
                best, best_score = sample, score
        if best is None:
            return []
        result = []
        for sub in repo.list_subtasks(best.task_id)[:limit]:
            real = repo.real_seconds_subtask(sub["id"]) / 60
            minutes = round5(real) if real >= 1 else sub["estimate_min"]
            result.append((sub["title"], minutes or None))
        return result

    # ---- perguntas ------------------------------------------------------

    def answer_duration(self, repo, question):
        """Responde 'quanto tempo levo para X?' só com tarefas parecidas; None se não há base."""
        prediction = self.predict_from(self.collect(repo), question)
        if prediction is None or prediction.basis != "similar":
            return None
        quoted = ", ".join(f"“{t}”" for t in prediction.examples)
        return (f"Com base em {prediction.samples} tarefas parecidas ({quoted}), você leva em média "
                f"{format_minutes(prediction.typical_minutes)} — {bias_phrase(prediction.ratio)}.")
