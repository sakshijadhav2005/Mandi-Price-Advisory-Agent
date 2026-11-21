"""Agricultural glossary, built from the language packs.

Used for consistent terminology: the LLM prompt lists the target-language terms.
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



def glossary_for(lang: str) -> str:
    """Glossary lines for the prompt, e.g. 'modal price -> मॉडल भाव'."""
    if lang == "en":
        return ""
    return "\n".join(f"- {en} -> {langs[lang][0]}" for en, langs in glossary().items() if lang in langs)
