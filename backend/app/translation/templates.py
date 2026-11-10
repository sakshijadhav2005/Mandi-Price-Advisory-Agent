"""Answer templates (from the language packs) and rupee formatting.

Hindi and Marathi strings need review by native speakers before the pilot.
"""

from __future__ import annotations

from app.translation.languages import load_languages


def templates(lang: str) -> dict[str, str]:
    packs = load_languages()
    return (packs.get(lang) or packs["en"]).templates


def t(lang: str, key: str, **kwargs) -> str:
    template = templates(lang).get(key) or load_languages()["en"].templates[key]
    return template.format(**kwargs)


def inr(value: float | None) -> str:
    """Format rupees with Indian digit grouping: 123456 -> 1,23,456."""
    if value is None:
        return "-"
    n = int(round(value))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups) + "," + tail
