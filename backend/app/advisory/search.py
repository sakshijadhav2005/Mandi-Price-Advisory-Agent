"""Small lexical search (BM25) for the advisory features that need retrieval: reviewed
storage documents and Kisan Call Centre answers.

- Words are reduced to a light stem so Marathi / Hindi endings and English plurals match
  ("कांद्याची" ~ "कांदा", "onions" ~ "onion").
- A question is expanded with the glossary and crop names, so a Marathi question also
  finds English text ("कांदा साठवण" also searches "onion storage").
- A hit must share real content words with the question (not only the crop name or
  filler words); otherwise nothing is returned, so a weak match never becomes an answer.

The corpora here are small (hundreds to a few thousand passages per district), so the
index is built in memory when needed.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.reference import load_reference, tokens
from app.translation.glossary import glossary

# Marathi / Hindi endings that attach to a word (longest first when stripping).
_INDIC_SUFFIXES = sorted(
    [
        "ांच्या", "ांची", "ांचे", "ांचा", "ांना", "ांनी", "ांमध्ये", "ामध्ये", "मध्ये", "साठी", "करिता", "पासून", "पर्यंत",
        "च्या", "ची", "चे", "चा", "ला", "ना", "ने", "नी", "त", "ात", "वर", "ावर", "ाने", "ाला", "ाचा", "ाची", "ाचे",
        "ों", "ें", "ाओं", "ियों", "ीय", "ी", "े", "ा", "ो",
    ],
    key=len,
    reverse=True,
)
_STOPWORDS = {
    # English
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "it", "my", "i", "me", "we",
    "how", "what", "when", "which", "why", "should", "can", "do", "does", "did", "with", "at", "by", "from", "this",
    "that", "there", "please", "tell", "about", "farmer", "asked", "query", "information", "regarding", "give", "get",
    # Marathi
    "काय", "कसे", "कशी", "कसा", "कधी", "का", "मी", "माझा", "माझी", "माझे", "आहे", "आहेत", "करू", "करावे", "करावी",
    "आणि", "किंवा", "ते", "हे", "या", "व", "तर", "पण", "मला", "आम्ही", "सांगा", "बद्दल", "माहिती",
    # Hindi
    "क्या", "कैसे", "कब", "मैं", "मेरा", "मेरी", "है", "हैं", "करें", "करना", "और", "या", "यह", "वह", "को", "से", "में",
    "पर", "के", "की", "का", "बताएं", "बारे", "जानकारी",
}


def stem(word: str) -> str:
    word = word.lower()
    if word.isascii():
        for suffix in ("ies", "es", "s"):
            if len(word) > 4 and word.endswith(suffix):
                return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
        return word
    for suffix in _INDIC_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[: -len(suffix)]
            break
    word = word.rstrip("्ाीिुूेैोौंँ") or word  # drop a trailing vowel sign / virama
    if word.endswith("्य") and len(word) > 4:  # Marathi oblique stem: "कांद्या-" ~ "कांदा"
        word = word[:-2]
    return word


def terms(text: str) -> list[str]:
    return [stem(t) for t in tokens(text) if t not in _STOPWORDS and len(t) > 1]


def _crop_terms() -> set[str]:
    out = set()
    for crop in load_reference().crops.values():
        for name in (crop.name, *crop.aliases, *crop.names.values()):
            out.update(terms(name))
    return out


def expand(question: str) -> list[str]:
    """The question's terms plus their translations from the glossary and crop names."""
    base = terms(question)
    extra: list[str] = []
    lowered = question.lower()
    for english, renderings in glossary().items():
        variants = [english, *(v for vs in renderings.values() for v in vs)]
        if any(stem(v) in base or v.lower() in lowered for v in variants):
            extra.extend(t for v in variants for t in terms(v))
    for crop in load_reference().crops.values():
        names = [crop.name, *crop.aliases, *crop.names.values()]
        if any(set(terms(n)) & set(base) for n in names):
            extra.extend(t for n in (crop.name, *crop.names.values()) for t in terms(n))
    seen: list[str] = []
    for t in base + extra:
        if t not in seen:
            seen.append(t)
    return seen


@dataclass
class Hit:
    key: object
    score: float
    matched: list[str]


class BM25:
    def __init__(self, docs: list[tuple[object, str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.keys = [k for k, _ in docs]
        self.docs = [Counter(terms(text)) for _, text in docs]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.docs else 0.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def _variants(self, term: str) -> list[str]:
        """Index words a query word matches. Marathi / Hindi build words by adding to a stem
        ("साठवण" -> "साठवणूक", "साठवणुकी"), so a shared beginning of 4+ letters counts."""
        if term.isascii() or len(term) < 4:
            return [term]
        if not hasattr(self, "_vocab"):
            self._vocab = sorted({t for d in self.docs for t in d if not t.isascii()})
        return [v for v in self._vocab if v.startswith(term) or (len(v) >= 4 and term.startswith(v))] or [term]

    def search(self, question: str, k: int = 3, min_content_terms: int = 1) -> list[Hit]:
        """Best passages for the question. A passage must match at least `min_content_terms`
        words that are not crop names (a crop name alone is not a match)."""
        crop_words = _crop_terms()
        query: list[str] = []
        content: set[str] = set()
        for term in expand(question):
            for v in self._variants(term):
                if v not in query:
                    query.append(v)
                    if term not in crop_words and v not in crop_words:
                        content.add(v)
        hits = []
        for i, doc in enumerate(self.docs):
            matched = [t for t in query if t in doc]
            if len([t for t in matched if t in content]) < min_content_terms:
                continue
            score = 0.0
            for t in matched:
                tf = doc[t]
                score += self.idf.get(t, 0.0) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1)))
            hits.append(Hit(self.keys[i], round(score, 4), matched))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]


_MARATHI = re.compile(r"(आहे|आहेत|करावी|करावे|करा|मध्ये|साठी|च्या|पाहिजे|नाही)")
_HINDI = re.compile(r"(है|हैं|करें|करना|में|के लिए|चाहिए|नहीं|की)")


def guess_language(text: str) -> str:
    """en / mr / hi for a passage (Marathi and Hindi share a script: count typical words)."""
    if not re.search(r"[ऀ-ॿ]", text):
        return "en"
    return "mr" if len(_MARATHI.findall(text)) >= len(_HINDI.findall(text)) else "hi"
