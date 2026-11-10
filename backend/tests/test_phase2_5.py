"""Voice providers and metrics, price alerts and push, admin endpoints."""

import base64
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_mod
from app.alerts import check_alerts
from app.config import get_settings
from app.main import app
from app.voice import adapters
from app.voice.metrics import cer, normalise, wer

GUEST = {"X-Guest-Id": "phase-test-0001"}
AS_OF = date(2026, 11, 8)


def test_wer_and_cer():
    assert wer("मी कांदा आता विकू", "मी कांदा आता विकू।") == 0.0
    assert wer("should I sell onion now", "should I sell onions now") == pytest.approx(0.2)
    assert wer("a b c", "") == 1.0
    assert cer("टमाटर", "टमाटर") == 0.0
    assert normalise("२० क्विंटल!") == "20 क्विंटल"


@pytest.fixture
def settings_override(monkeypatch):
    s = get_settings()

    def apply(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(s, k, v)

    return apply


def test_google_tts_and_cache(monkeypatch, settings_override):
    settings_override(tts_provider="google", google_tts_api_key="k")
    adapters._tts_cache.clear()
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return httpx.Response(200, json={"audioContent": base64.b64encode(b"mp3").decode()}, request=httpx.Request("POST", url))

    monkeypatch.setattr(adapters.httpx, "post", fake_post)
    assert adapters.synthesize("नमस्कार", "mr") == (b"mp3", "audio/mpeg")
    assert adapters.synthesize("नमस्कार", "mr") == (b"mp3", "audio/mpeg")
    assert len(calls) == 1
    assert calls[0][1]["json"]["voice"]["languageCode"] == "mr-IN"


def test_azure_tts_escapes_ssml(monkeypatch, settings_override):
    settings_override(tts_provider="azure", azure_speech_key="k")
    adapters._tts_cache.clear()
    seen = {}

    def fake_post(url, **kw):
        seen["body"] = kw["content"].decode()
        return httpx.Response(200, content=b"mp3", request=httpx.Request("POST", url))

    monkeypatch.setattr(adapters.httpx, "post", fake_post)
    adapters.synthesize("price < ₹2,000 & rising", "hi")
    assert "&lt; ₹2,000 &amp; rising" in seen["body"] and "hi-IN-SwaraNeural" in seen["body"]


def test_tts_provider_error_maps_to_502(monkeypatch, settings_override):
    settings_override(tts_provider="google", google_tts_api_key="k")
    adapters._tts_cache.clear()
    monkeypatch.setattr(
        adapters.httpx, "post", lambda url, **kw: httpx.Response(500, request=httpx.Request("POST", url))
    )
    with TestClient(app) as c:
        assert c.post("/voice/speak", json={"text": "x", "language": "en"}, headers=GUEST).status_code == 502


def test_alerts_api_and_trigger(session, monkeypatch):
    pushed = []
    monkeypatch.setattr(alerts_mod, "send_expo_push", lambda tokens, title, body, data=None: pushed.append((tokens, title, body)) or bool(tokens))
    with TestClient(app) as c:
        assert c.post("/devices", json={"push_token": "ExponentPushToken[abc123]", "platform": "android"}, headers=GUEST).json() == {"registered": True}
        a = c.post("/alerts", json={"crop": "onion", "direction": "above", "threshold": 100, "language": "mr"}, headers=GUEST).json()
        c.post("/alerts", json={"crop": "onion", "direction": "below", "threshold": 1, "language": "en"}, headers=GUEST)
        assert c.post("/alerts", json={"crop": "wheat", "direction": "above", "threshold": 1}, headers=GUEST).status_code == 422

        assert check_alerts(session, AS_OF) == 1  # only the 'above 100' alert crosses
        assert check_alerts(session, AS_OF) == 0  # same report date: no repeat
        assert pushed[0][0] == ["ExponentPushToken[abc123]"] and "कांदा" in pushed[0][2]

        inbox = c.get("/alerts/notifications", headers=GUEST).json()
        assert len(inbox) == 1 and not inbox[0]["read"]
        c.post("/alerts/notifications/read", headers=GUEST)
        assert c.get("/alerts/notifications?unread_only=true", headers=GUEST).json() == []

        assert c.delete(f"/alerts/{a['id']}", headers={"X-Guest-Id": "someone-else-9999"}).status_code == 404
        assert c.delete(f"/alerts/{a['id']}", headers=GUEST).json() == {"deleted": True}
        assert [x["active"] for x in c.get("/alerts", headers=GUEST).json()] == [False, True]


def test_expo_push_payload(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return httpx.Response(200, json={"data": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerts_mod.httpx, "post", fake_post)
    assert alerts_mod.send_expo_push(["ExponentPushToken[x]"], "t", "b", {"k": 1})
    assert seen["json"][0] == {"to": "ExponentPushToken[x]", "title": "t", "body": "b", "sound": "default", "data": {"k": 1}}
    assert alerts_mod.send_expo_push([], "t", "b") is False


def test_admin_endpoints(settings_override):
    with TestClient(app) as c:
        assert c.get("/admin/stats").status_code == 404  # disabled without ADMIN_TOKEN
        settings_override(admin_token="secret")
        assert c.get("/admin/stats").status_code == 401
        c.post("/chat", json={"message": "tomato sell?", "language": "hi", "input_mode": "voice"}, headers=GUEST)
        stats = c.get("/admin/stats", headers={"X-Admin-Token": "secret"}).json()
        assert stats["per_language"]["hi"]["answers"] >= 1
        assert stats["per_language"]["hi"]["voice_input_share"] > 0
        csv_text = c.get("/admin/export.csv", headers={"X-Admin-Token": "secret"}).text
        assert csv_text.startswith("message_id,") and "tomato sell?" in csv_text


def test_meta_lists_language_packs():
    with TestClient(app) as c:
        packs = c.get("/meta").json()["language_packs"]
        assert {p["code"]: p["speech_locale"] for p in packs} == {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}
