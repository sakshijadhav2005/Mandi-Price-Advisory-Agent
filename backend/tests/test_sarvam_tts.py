"""Sarvam AI (Bulbul) text-to-speech: request shape, MP3 output, long answers split."""

import base64

import httpx
import pytest

from app.config import get_settings
from app.voice import adapters


@pytest.fixture
def sarvam(monkeypatch):
    s = get_settings()
    for k, v in {"tts_provider": "sarvam", "sarvam_api_key": "key-1", "sarvam_tts_speaker": "", "sarvam_tts_model": "bulbul:v3"}.items():
        monkeypatch.setattr(s, k, v)
    adapters._tts_cache.clear()
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        audio = base64.b64encode(f"mp3-{len(calls)}".encode()).decode()
        return httpx.Response(200, json={"request_id": "r", "audios": [audio]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(adapters.httpx, "post", fake_post)
    yield calls
    adapters._tts_cache.clear()


def test_marathi_request(sarvam, monkeypatch):
    audio, media = adapters.synthesize("कांद्याचा भाव ₹2,000 प्रति क्विंटल आहे.", "mr")
    assert (audio, media) == (b"mp3-1", "audio/mpeg")
    url, kw = sarvam[0]
    assert url == "https://api.sarvam.ai/text-to-speech"
    assert kw["headers"] == {"api-subscription-key": "key-1"}
    body = kw["json"]
    assert body["language_code"] == "mr-IN" and body["model"] == "bulbul:v3"
    assert body["output_audio_codec"] == "mp3" and body["enable_preprocessing"] is True
    assert "speaker" not in body  # empty setting: Sarvam's default voice

    monkeypatch.setattr(get_settings(), "sarvam_tts_speaker", "ritu")
    adapters.synthesize("नमस्कार", "mr")
    assert sarvam[1][1]["json"]["speaker"] == "ritu"


def test_long_answer_is_split_and_joined(sarvam):
    sentence = "हा एक मोठा वाक्य आहे जे पुन्हा पुन्हा येते. "
    text = sentence * 120  # ~5,000 characters
    audio, _ = adapters.synthesize(text, "mr")
    assert len(sarvam) >= 3
    assert all(len(kw["json"]["text"]) <= adapters.SARVAM_MAX_CHARS for _, kw in sarvam)
    assert audio == b"".join(f"mp3-{i}".encode() for i in range(1, len(sarvam) + 1))


def test_missing_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "tts_provider", "sarvam")
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "")
    adapters._tts_cache.clear()
    with pytest.raises(adapters.VoiceNotConfigured):
        adapters.synthesize("नमस्कार", "mr")
