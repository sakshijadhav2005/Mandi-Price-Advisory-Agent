"""Output guardrails for LLM answers.

- Language: a Hindi/Marathi answer must be mostly Devanagari.
- Grounding: every figure of 2+ digits in the answer must be traceable to a
  number in the tool results (allowing for rounding), so the agent cannot add
  false precision.
"""

from __future__ import annotations

import json
import re

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")


SCRIPT_RANGES = {
    "Devanagari": r"ऀ-ॿ",
    "Bengali": r"ঀ-৿",
    "Gurmukhi": r"਀-੿",
    "Gujarati": r"઀-૿",
    "Odia": r"଀-୿",
    "Tamil": r"஀-௿",
    "Telugu": r"ఀ-౿",
    "Kannada": r"ಀ-೿",
    "Malayalam": r"ഀ-ൿ",
}
_ANY_INDIC = re.compile("[" + "".join(SCRIPT_RANGES.values()) + "]")


def language_ok(text: str, lang: str) -> bool:
    """True when the answer is mostly in the script of the target language."""
    from app.translation.languages import load_languages

    pack = load_languages().get(lang)
    script = pack.script if pack else "Latin"
    latin = len(_LATIN.findall(text))
    if script == "Latin":
        return len(_ANY_INDIC.findall(text)) < 0.2 * max(latin, 1)
    native = len(re.findall("[" + SCRIPT_RANGES.get(script, SCRIPT_RANGES["Devanagari"]) + "]", text))
    return native > 0 and native >= 2 * latin


_SENTENCE = re.compile(r"[.!?।\n]")
OPPOSITE = {"sell": "hold", "hold": "sell"}


def decision_consistent(text: str, decision: str | None, lang: str, advisory: bool = False) -> bool:
    """The first sentence must not recommend a different action than the engine.

    If the first sentence states a decision (sell / hold / not enough data), it must
    be the recommended one, and only that one. A first sentence with no decision
    passes. Catches fluent, grounded answers that recommend the wrong action, such
    as a "sell" result written up as "you can wait".

    For storage/handling questions (`advisory=True`), storage words such as
    "store" or "साठव" are not read as a hold recommendation, but an explicit
    "hold your onions" for a sell result is still rejected.
    """
    if not decision:
        return True
    from app.translation.languages import load_languages

    packs = load_languages()
    pack = packs.get(lang) or packs["en"]
    words = pack.decision_words
    if decision not in words:
        return True
    if advisory:
        storage = [a.lower() for p in packs.values() for a in p.advisory_words]
        words = {d: [w for w in stems if not any(s in w or w in s for s in storage)] for d, stems in words.items()}
    first = next((part for part in _SENTENCE.split(text.lower()) if part.strip()), "")
    stated = {d for d, stems in words.items() if any(w in first for w in stems)}
    if not stated:
        return True
    if decision in OPPOSITE:
        return decision in stated and OPPOSITE[decision] not in stated and "insufficient_data" not in stated
    return stated == {"insufficient_data"}


def _numbers_in(obj) -> set[float]:
    found: set[float] = set()
    if isinstance(obj, bool):
        return found
    if isinstance(obj, (int, float)):
        found.add(float(obj))
    elif isinstance(obj, str):
        for d in _DATE.findall(obj):
            found.update(float(x) for x in re.findall(r"\d+", d))
        for n in _NUMBER.findall(obj.translate(_DEVANAGARI_DIGITS)):
            try:
                found.add(float(n.replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _numbers_in(v)
    return found


def ungrounded_numbers(answer: str, tool_outputs: list[dict]) -> list[str]:
    known = set()
    for out in tool_outputs:
        known |= _numbers_in(json.loads(json.dumps(out, default=str)))
    text = _DATE.sub(" ", answer.translate(_DEVANAGARI_DIGITS))
    bad = []
    for raw in _NUMBER.findall(text):
        cleaned = raw.rstrip(",.")
        try:
            value = float(cleaned.replace(",", ""))
        except ValueError:
            continue
        if value < 10:
            continue  # small counts like "3 days", "2 markets"
        if not any(_close(value, k) for k in known):
            bad.append(cleaned)
    return bad


def _close(value: float, known: float) -> bool:
    if known == 0:
        return value == 0
    if abs(value - known) <= max(1.0, 0.01 * abs(known)):
        return True
    # rounded to tens / hundreds / thousands
    return any(round(known / step) * step == value for step in (10, 50, 100, 1000))
