"""Sarvam AI translation (POST https://api.sarvam.ai/translate), used to put English source
text such as the IMD crop advice into Marathi and Hindi once, when it is downloaded.

Numbers stay in international digits (`numerals_format`), so doses and dates read the same
as in the original. Long text is split at sentence ends to stay under the model's limit.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

TRANSLATE_URL = "https://api.sarvam.ai/translate"
LOCALES = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
MAX_CHARS = 1800  # sarvam-translate:v1 accepts 2000 characters; mayura:v1 1000


class TranslationUnavailable(Exception):
    pass


def available() -> bool:
    return bool(get_settings().sarvam_api_key)


def _pieces(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?।])\s+", text.strip()):
        while len(sentence) > limit:
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if buf and len(buf) + 1 + len(sentence) > limit:
            parts.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        parts.append(buf)
    return parts


def translate(text: str, target: str, source: str = "en") -> str:
    """Translate `text` (en -> hi / mr). Raises TranslationUnavailable without a key or on failure."""
    s = get_settings()
    if not s.sarvam_api_key:
        raise TranslationUnavailable("SARVAM_API_KEY is not set")
    if not text.strip() or target == source:
        return text
    model = s.sarvam_translate_model
    limit = MAX_CHARS if model.startswith("sarvam-translate") else 900
    out = []
    for piece in _pieces(text, limit):
        try:
            resp = httpx.post(
                TRANSLATE_URL,
                headers={"api-subscription-key": s.sarvam_api_key},
                json={
                    "input": piece,
                    "source_language_code": LOCALES[source],
                    "target_language_code": LOCALES[target],
                    "model": model,
                    "numerals_format": "international",
                },
                timeout=45,
            )
            resp.raise_for_status()
            out.append(resp.json()["translated_text"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise TranslationUnavailable(f"Sarvam translate failed: {exc}") from exc
    return " ".join(out)
