"""Agricultural glossary, built from the language packs.

Used for two things:
1. Query expansion: a Hindi/Marathi query gets English keywords appended (and
   vice versa), so lexical retrieval can match bulletins in another language.
2. Consistent terminology: the LLM prompt lists the target-language terms.
"""

from __future__ import annotations

from functools import lru_cache

from app.translation.languages import load_languages


def supported_languages() -> dict[str, str]:
    """code -> English name for every installed language pack."""
    return {code: p.name for code, p in load_languages().items()}


SUPPORTED_LANGUAGES = supported_languages()


@lru_cache
def glossary() -> dict[str, dict[str, list[str]]]:
    """canonical English term -> {lang: renderings} (English itself excluded)."""
    out: dict[str, dict[str, list[str]]] = {}
    for code, pack in load_languages().items():
        if code == "en":
            continue
        for term, renderings in pack.glossary.items():
            out.setdefault(term, {})[code] = renderings
    return out


def expand_query(query: str) -> str:
    """Append equivalent terms in the other supported languages."""
    lowered = query.lower()
    extra: list[str] = []
    for english, langs in glossary().items():
        variants = [english] + [v for vs in langs.values() for v in vs]
        if any(v.lower() in lowered for v in variants):
            extra.extend(v for v in variants if v.lower() not in lowered and v not in extra)
    return f"{query} {' '.join(extra)}" if extra else query


def glossary_for(lang: str) -> str:
    """Glossary lines for the prompt, e.g. 'modal price -> मॉडल भाव'."""
    if lang == "en":
        return ""
    return "\n".join(f"- {en} -> {langs[lang][0]}" for en, langs in glossary().items() if lang in langs)
