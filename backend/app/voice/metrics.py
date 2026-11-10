"""Speech recognition metrics: word error rate (WER) and character error rate (CER)."""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\sऀ-෿]", re.UNICODE)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalise(text: str) -> str:
    """Lowercase, NFC, Latin digits, no punctuation (including the danda), single spaces."""
    text = unicodedata.normalize("NFC", text).translate(_DEVANAGARI_DIGITS).lower()
    text = text.replace("।", " ").replace("॥", " ")
    return " ".join(_PUNCT.sub(" ", text).split())


def _edit_distance(ref: list, hyp: list) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    ref, hyp = list(normalise(reference).replace(" ", "")), list(normalise(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)
