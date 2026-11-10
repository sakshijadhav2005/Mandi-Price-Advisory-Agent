"""Language packs loaded from backend/data/languages/<code>.json.

Adding a language needs no code change: add a JSON file with the same template
keys (checked by tests) and a glossary, plus the UI strings in packages/i18n.
"""

from __future__ import annotations

import json
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
        )
    if "en" not in packs:
        raise RuntimeError("English language pack (en.json) is required as the fallback")
    return packs


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
