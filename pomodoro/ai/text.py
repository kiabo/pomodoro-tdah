"""Comparação de títulos de tarefas: palavras-chave, radicais e similaridade. Funções puras."""

import re
import unicodedata
from collections import Counter

STOPWORDS = frozenset(
    "de da do das dos para por com sem em no na nos nas um uma uns umas que ao aos as os ou se ser ter "
    "mais menos muito pra pro the and".split()
)
STEM_LEN = 5
_TOKEN = re.compile(r"[^\W\d_]+")


def normalize(text):
    """Minúsculas e sem acentos: 'Relatório' -> 'relatorio'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text):
    """Palavras com significado (sem conectivos nem palavras de 1–2 letras), como escritas, em minúsculas."""
    return [w for w in _TOKEN.findall(text.lower()) if len(w) >= 3 and normalize(w) not in STOPWORDS]


def stem(word):
    """Radical simples: as 5 primeiras letras sem acento ('escrever' e 'escrita' -> 'escri')."""
    return normalize(word)[:STEM_LEN]


def stems(text):
    return frozenset(stem(w) for w in words(text))


def similarity(a, b):
    """Jaccard entre dois conjuntos de radicais, de 0 a 1."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def display_word(stem_, titles):
    """A palavra mais usada nos títulos que tem esse radical (com acento), para mostrar ao usuário."""
    counts = Counter(w for title in titles for w in words(title) if stem(w) == stem_)
    if not counts:
        return stem_
    best = max(counts.values())
    return min((w for w, n in counts.items() if n == best), key=len)


def weighted_median(values, weights=None):
    """Mediana ponderada. Sem pesos, é a mediana comum (a menor das duas centrais em empate)."""
    if not values:
        raise ValueError("sem valores")
    weights = weights or [1.0] * len(values)
    pairs = sorted(zip(values, weights))
    half = sum(w for _v, w in pairs) / 2
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]
