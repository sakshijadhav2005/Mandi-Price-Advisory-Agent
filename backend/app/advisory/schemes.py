"""Government schemes: structured entries (data/schemes/<id>.json) and yes/no eligibility rules.

Each entry gives, in en/hi/mr, what the farmer gets, who can get it, who cannot, the
documents and how to apply, plus the official link, helpline, the date the information
was last checked (`info_as_of`) and a review status. Entries start as "draft"; an officer
who checks one sets "reviewed" and their name. Answers always point to the official
source, and say when an entry is unreviewed or older than STALE_AFTER_DAYS.

Eligibility rules are facts that must be true or false (`_facts.json` holds the questions
in three languages), so "am I eligible?" is answered by rules, never by a guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR
from app.reference import load_reference

SCHEME_DIR = DATA_DIR / "schemes"
LANGS = ("en", "hi", "mr")
TEXT_FIELDS = ("benefit", "who", "not_eligible", "documents", "apply")
STALE_AFTER_DAYS = 183  # flag entries whose information is older than about six months


class SchemeError(ValueError):
    """A scheme file is invalid (missing language, unknown fact, bad link, ...)."""


@dataclass(frozen=True)
class Scheme:
    id: str
    state: str  # "all" for central schemes
    category: str
    names: dict[str, str]
    aliases: tuple[str, ...]
    url: str
    helpline: str
    info_as_of: date
    review_status: str  # draft | reviewed
    reviewed_by: str | None
    sources: tuple[str, ...]
    text: dict[str, dict[str, str]]
    eligibility: tuple[dict, ...]

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names["en"]

    def texts(self, lang: str) -> dict[str, str]:
        return self.text.get(lang) or self.text["en"]

    def applies_to(self, state: str) -> bool:
        return self.state.lower() in ("all", "central") or self.state.lower() == state.lower()

    def is_stale(self, today: date) -> bool:
        return today - self.info_as_of > timedelta(days=STALE_AFTER_DAYS)


@lru_cache
def load_facts(directory: Path | None = None) -> dict[str, dict]:
    raw = json.loads(((directory or SCHEME_DIR) / "_facts.json").read_text(encoding="utf-8"))
    facts = {k: v for k, v in raw.items() if not k.startswith("_")}
    for key, fact in facts.items():
        if set(fact.get("question", {})) != set(LANGS):
            raise SchemeError(f"fact {key}: 'question' needs {LANGS}")
        reasons = [r for r in ("reason_true", "reason_false") if r in fact]
        if not reasons or any(set(fact[r]) != set(LANGS) for r in reasons):
            raise SchemeError(f"fact {key}: needs reason_true or reason_false in {LANGS}")
    return facts


def _parse(raw: dict, facts: dict[str, dict], states: set[str]) -> Scheme:
    sid = raw.get("id", "?")
    problems = []
    for key in ("id", "state", "category", "names", "aliases", "url", "helpline", "info_as_of", "review_status", "text", "eligibility"):
        if key not in raw:
            problems.append(f"missing '{key}'")
    if problems:
        raise SchemeError(f"{sid}: " + "; ".join(problems))
    if set(raw["names"]) != set(LANGS):
        problems.append(f"names need {LANGS}")
    for lang in LANGS:
        missing = [f for f in TEXT_FIELDS if f not in raw["text"].get(lang, {})]
        if missing:
            problems.append(f"text.{lang} missing {missing}")
        elif not raw["text"][lang]["benefit"].strip() or not raw["text"][lang]["apply"].strip():
            problems.append(f"text.{lang} needs 'benefit' and 'apply'")
    if raw["state"].lower() not in ("all", "central") and raw["state"] not in states:
        problems.append(f"unknown state {raw['state']!r}")
    if not raw["url"].startswith("https://"):
        problems.append("url must start with https://")
    if raw["review_status"] not in ("draft", "reviewed"):
        problems.append("review_status must be draft or reviewed")
    if raw["review_status"] == "reviewed" and not raw.get("reviewed_by"):
        problems.append("a reviewed entry needs reviewed_by")
    for rule in raw["eligibility"]:
        fact = facts.get(rule.get("fact"))
        if fact is None:
            problems.append(f"unknown fact {rule.get('fact')!r}")
        elif not isinstance(rule.get("must_be"), bool):
            problems.append(f"rule {rule['fact']}: must_be must be true or false")
        elif f"reason_{str(not rule['must_be']).lower()}" not in fact:
            problems.append(f"rule {rule['fact']}: fact has no reason_{str(not rule['must_be']).lower()}")
    try:
        as_of = date.fromisoformat(raw["info_as_of"])
    except (TypeError, ValueError):
        problems.append("info_as_of must be YYYY-MM-DD")
        as_of = date.min
    if problems:
        raise SchemeError(f"{sid}: " + "; ".join(problems))
    return Scheme(
        id=raw["id"],
        state=raw["state"],
        category=raw["category"],
        names=raw["names"],
        aliases=tuple(a.lower() for a in raw["aliases"]),
        url=raw["url"],
        helpline=raw["helpline"],
        info_as_of=as_of,
        review_status=raw["review_status"],
        reviewed_by=raw.get("reviewed_by"),
        sources=tuple(raw.get("sources", [])),
        text=raw["text"],
        eligibility=tuple(raw["eligibility"]),
    )


@lru_cache
def load_schemes(directory: Path | None = None) -> dict[str, Scheme]:
    """All scheme entries, validated; a broken file stops the app rather than giving wrong answers."""
    directory = directory or SCHEME_DIR
    facts = load_facts(directory)
    states = set(load_reference().states)
    schemes: dict[str, Scheme] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scheme = _parse(json.loads(path.read_text(encoding="utf-8")), facts, states)
        if scheme.id != path.stem:
            raise SchemeError(f"{path.name}: id {scheme.id!r} must match the file name")
        schemes[scheme.id] = scheme
    return schemes


def schemes_for_state(state: str) -> list[Scheme]:
    return [s for s in load_schemes().values() if s.applies_to(state)]


def detect_scheme(text: str) -> Scheme | None:
    """The scheme a question names (longest alias wins; Latin aliases must start a word)."""
    lowered = text.lower()
    best: tuple[int, Scheme] | None = None
    for scheme in load_schemes().values():
        for alias in scheme.aliases:
            if alias.isascii():  # whole words: "drip" but not "dripping"
                hit = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z])", lowered)
            else:  # Marathi/Hindi endings attach to the name ("किसानचा"), so a substring is right
                hit = alias in lowered
            if hit and (best is None or len(alias) > best[0]):
                best = (len(alias), scheme)
    return best[1] if best else None


def check_eligibility(scheme: Scheme, facts: dict[str, bool | None], lang: str) -> dict:
    """eligible / not_eligible (with reasons) / depends (with the questions still open) / open
    (the scheme has no conditions beyond being a farmer)."""
    definitions = load_facts()
    reasons, questions = [], []
    for rule in scheme.eligibility:
        key, must_be = rule["fact"], rule["must_be"]
        value = facts.get(key)
        if value is None:
            questions.append(definitions[key]["question"][lang])
        elif value != must_be:
            reasons.append(definitions[key][f"reason_{str(value).lower()}"][lang])
    if reasons:
        verdict = "not_eligible"
    elif questions:
        verdict = "depends"
    else:
        verdict = "eligible" if scheme.eligibility else "open"
    return {"scheme": scheme.id, "verdict": verdict, "reasons": reasons, "questions": questions}


def problems_report(today: date) -> list[str]:
    """Entries a person should look at: unreviewed or older than STALE_AFTER_DAYS."""
    out = []
    for s in load_schemes().values():
        if s.review_status != "reviewed":
            out.append(f"{s.id}: not reviewed yet (information as of {s.info_as_of})")
        if s.is_stale(today):
            out.append(f"{s.id}: information is older than {STALE_AFTER_DAYS} days ({s.info_as_of}); re-check the official source")
    return out
