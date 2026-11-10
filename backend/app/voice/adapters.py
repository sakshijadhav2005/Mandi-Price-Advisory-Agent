"""Speech-to-text and text-to-speech adapters.

Server-side voice is optional in v1. The web app uses the browser's speech
engine (Web Speech API) when the server reports no provider via /meta. To enable
server STT, install the `whisper` extra and set STT_PROVIDER=whisper. Recorded
audio is deleted right after transcription unless STORE_VOICE_RECORDINGS=true
and the user consented (plan section 8).
"""

from __future__ import annotations

import base64
import logging
import math
import os
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from xml.sax.saxutils import escape as xml_escape

import httpx

from app.config import get_settings
from app.voice import storage

log = logging.getLogger(__name__)

WHISPER_LANGS = {"en": "en", "hi": "hi", "mr": "mr"}


class VoiceNotConfigured(Exception):
    pass


class VoiceProviderError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    language: str
    confidence: float  # 0..1, average token probability where available
    needs_confirmation: bool


@lru_cache
def _whisper_model():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise VoiceNotConfigured("faster-whisper is not installed (pip install -e '.[whisper]')") from exc
    return WhisperModel(get_settings().whisper_model, device="auto", compute_type="int8")


def transcribe(audio: bytes, suffix: str = ".webm", language_hint: str | None = None, consent: bool = False) -> Transcript:
    settings = get_settings()
    if settings.stt_provider != "whisper":
        raise VoiceNotConfigured("No server speech-to-text provider configured (STT_PROVIDER=none)")
    model = _whisper_model()
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(audio)
        segments, info = model.transcribe(path, language=WHISPER_LANGS.get(language_hint or ""), vad_filter=True)
        segments = list(segments)
    finally:
        os.unlink(path)  # the temp file is always deleted; consented copies go to storage below
    if storage.should_store(consent):
        try:
            storage.store_recording(audio, suffix, language_hint)
        except Exception as exc:  # storage trouble must not break the farmer's question
            log.error("could not store consented recording: %s", exc)
    text = " ".join(s.text.strip() for s in segments).strip()
    probs = [math.exp(s.avg_logprob) for s in segments] or [0.0]
    confidence = sum(probs) / len(probs)
    lang = info.language if info.language in WHISPER_LANGS else (language_hint or "en")
    return Transcript(text=text, language=lang, confidence=round(confidence, 3), needs_confirmation=confidence < 0.6 or not text)


# Neural voices per language. Marathi and Hindi are both available on Google and Azure.
GOOGLE_VOICES = {"en": ("en-IN", "en-IN-Neural2-A"), "hi": ("hi-IN", "hi-IN-Neural2-A"), "mr": ("mr-IN", "mr-IN-Standard-A")}
AZURE_VOICES = {"en": ("en-IN", "en-IN-NeerjaNeural"), "hi": ("hi-IN", "hi-IN-SwaraNeural"), "mr": ("mr-IN", "mr-IN-AarohiNeural")}

_tts_cache: "OrderedDict[tuple[str, str, str], bytes]" = OrderedDict()
TTS_CACHE_SIZE = 256


def _google_tts(text: str, language: str) -> bytes:
    s = get_settings()
    if not s.google_tts_api_key:
        raise VoiceNotConfigured("GOOGLE_TTS_API_KEY is not set")
    locale, voice = GOOGLE_VOICES.get(language, GOOGLE_VOICES["en"])
    resp = httpx.post(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        params={"key": s.google_tts_api_key},
        json={
            "input": {"text": text},
            "voice": {"languageCode": locale, "name": voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95},
        },
        timeout=30,
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audioContent"])


def _azure_tts(text: str, language: str) -> bytes:
    s = get_settings()
    if not s.azure_speech_key:
        raise VoiceNotConfigured("AZURE_SPEECH_KEY is not set")
    locale, voice = AZURE_VOICES.get(language, AZURE_VOICES["en"])
    ssml = (
        f"<speak version='1.0' xml:lang='{locale}'><voice name='{voice}'>"
        f"<prosody rate='-5%'>{xml_escape(text)}</prosody></voice></speak>"
    )
    resp = httpx.post(
        f"https://{s.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": s.azure_speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "mandi-advisor",
        },
        content=ssml.encode("utf-8"),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


TTS_PROVIDERS = {"google": _google_tts, "azure": _azure_tts}


def synthesize(text: str, language: str) -> tuple[bytes, str]:
    """Returns (MP3 bytes, media type). Repeated answers are served from a small cache."""
    provider = get_settings().tts_provider
    fn = TTS_PROVIDERS.get(provider)
    if fn is None:
        raise VoiceNotConfigured("No server text-to-speech provider configured (TTS_PROVIDER=none)")
    key = (provider, language, text)
    if key in _tts_cache:
        _tts_cache.move_to_end(key)
        return _tts_cache[key], "audio/mpeg"
    try:
        audio = fn(text, language)
    except httpx.HTTPError as exc:
        raise VoiceProviderError(f"{provider} TTS failed: {exc}") from exc
    _tts_cache[key] = audio
    if len(_tts_cache) > TTS_CACHE_SIZE:
        _tts_cache.popitem(last=False)
    return audio, "audio/mpeg"


def capabilities() -> dict:
    s = get_settings()
    return {
        "server_stt": s.stt_provider != "none",
        "server_tts": s.tts_provider != "none",
        "stores_recordings": s.store_voice_recordings,  # apps then ask the farmer for consent
    }
