"""Language packs loaded from backend/data/languages/<code>.json.

Adding a language needs no code change: add a JSON file with the same template
keys (checked by tests) and a glossary, plus the UI strings in packages/i18n.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import DATA_DIR

LANG_DIR = DATA_DIR / "languages"


@dataclass(frozen=True)
class LanguagePack:
    code: str
    name: str
    speech_locale: str
    script: str
    templates: dict[str, str]
    glossary: dict[str, list[str]]  # canonical English term -> renderings in this language
    decision_words: dict[str, list[str]]  # decision -> word stems that express it (for consistency checks)
    advisory_words: list[str]  # stems that mark a storage / handling question
    weather_words: list[str] = ()  # stems that mark a weather / spraying / crop-care question
    pesticide_words: list[str] = ()  # stems that mark a pesticide dose / waiting-period question
    scheme_words: list[str] = ()  # "scheme", "योजना": a general government-scheme question
    eligibility_words: list[str] = ()  # "am I eligible", "पात्र", "मिळेल का"


@lru_cache
def load_languages() -> dict[str, LanguagePack]:
    packs = {}
    for path in sorted(LANG_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        packs[raw["code"]] = LanguagePack(
            code=raw["code"],
            name=raw["name"],
            speech_locale=raw.get("speech_locale", raw["code"]),
            script=raw.get("script", "Latin"),
            templates=raw["templates"],
            glossary=raw.get("glossary", {}),
            decision_words=raw.get("decision_words", {}),
            advisory_words=raw.get("advisory_words", []),
            weather_words=raw.get("weather_words", []),
            pesticide_words=raw.get("pesticide_words", []),
            scheme_words=raw.get("scheme_words", []),
            eligibility_words=raw.get("eligibility_words", []),
        )
    if "en" not in packs:
        raise RuntimeError("English language pack (en.json) is required as the fallback")
    return packs


_WORD_START = r"\b"  # a Latin keyword must start a word
_DEVA_START = "(?<![ऀ-ॿ])"  # not preceded by a Devanagari letter or vowel sign
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DAYS_AGO = re.compile(r"(\d{1,3})\s*(?:days?|din|दिवस|दिवसां|दिन)", re.I)


def _mentions(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    for word in (w.lower() for w in words):
        # Words must start a word: "rain" but not "grain", "heat" but not "wheat", and Hindi
        # "पाला" (frost) but not "भाजीपाला" (vegetables). Endings may follow ("पावसाचा").
        if re.search(_WORD_START + re.escape(word), lowered) if word.isascii() else re.search(_DEVA_START + re.escape(word), lowered):
            return True
    return False


def is_weather_question(text: str) -> bool:
    """True for weather, rain, spraying, irrigation and crop-care questions (any language).
    These are answered from the district's IMD agromet bulletin."""
    return _mentions(text, [w for p in load_languages().values() for w in p.weather_words])


def is_pesticide_question(text: str) -> bool:
    """True for pesticide dose / waiting-period questions ("how many days after spraying ...")."""
    return _mentions(text, [w for p in load_languages().values() for w in p.pesticide_words])


def is_scheme_question(text: str) -> bool:
    """True for a general government-scheme question ("which schemes are there?")."""
    return _mentions(text, [w for p in load_languages().values() for w in p.scheme_words])


def asks_eligibility(text: str) -> bool:
    """True when the farmer asks whether they qualify ("am I eligible", "मला मिळेल का")."""
    return _mentions(text, [w for p in load_languages().values() for w in p.eligibility_words])


def days_since_spray(text: str) -> int | None:
    """'I sprayed 3 days ago', '३ दिवसांपूर्वी फवारले' -> 3."""
    m = _DAYS_AGO.search(text.translate(_DEVANAGARI_DIGITS))
    return int(m.group(1)) if m else None


def is_advisory_question(text: str) -> bool:
    """True for storage / quality / handling questions (checked in every language).

    A question that also asks sell-or-hold ("my potatoes are in cold storage,
    hold or sell?") is a decision question, not an advisory one. Stems shared by
    both lists (e.g. Marathi "साठव", store) do not count as asking sell-or-hold.
    """
    lowered = text.lower()
    packs = load_languages().values()
    storage = [w.lower() for p in packs for w in p.advisory_words]
    if not any(w in lowered for w in storage):
        return False
    decision_stems = [
        w.lower()
        for p in packs
        for d in ("sell", "hold")
        for w in p.decision_words.get(d, [])
        if not any(s in w.lower() or w.lower() in s for s in storage)
    ]
    return not any(w in lowered for w in decision_stems)


def asks_sell_or_hold(text: str) -> bool:
    """True when the question uses a sell / hold word in any language."""
    lowered = text.lower()
    return any(
        w.lower() in lowered for p in load_languages().values() for d in ("sell", "hold") for w in p.decision_words.get(d, [])
    )
