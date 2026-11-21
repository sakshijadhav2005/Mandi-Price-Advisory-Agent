"""Ops alerts on ingestion failure and consented voice storage."""

import sys
import types

import httpx

from app import ops
from app.config import get_settings
from app.voice import storage

# --- ops alerts -------------------------------------------------------------


def _capture_webhook(monkeypatch):
    sent = []
    monkeypatch.setattr(get_settings(), "ops_alert_webhook_url", "https://hooks.example/x")

    def fake_post(url, json=None, timeout=None):
        sent.append(json["text"])
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(ops.httpx, "post", fake_post)
    return sent


def test_daily_job_alerts_on_failure(monkeypatch):
    sent = _capture_webhook(monkeypatch)

    def boom():
        raise RuntimeError("portal down")

    out = ops.run_daily(boom, lambda: None)
    assert out == {"rows": None, "ingestion": "failed", "alerts": "ok"}
    assert len(sent) == 1 and "portal down" in sent[0]


def test_daily_job_alerts_on_empty_ingestion(monkeypatch):
    sent = _capture_webhook(monkeypatch)
    assert ops.run_daily(lambda: 0, lambda: None)["ingestion"] == "empty"
    assert "0 rows" in sent[0]


def test_daily_job_quiet_when_ok(monkeypatch):
    sent = _capture_webhook(monkeypatch)
    assert ops.run_daily(lambda: 42, lambda: None) == {"rows": 42, "ingestion": "ok", "alerts": "ok"}
    assert sent == []


def test_ops_alert_without_webhook_only_logs(monkeypatch):
    monkeypatch.setattr(get_settings(), "ops_alert_webhook_url", "")
    assert ops.ops_alert("hello") is False


# --- consented voice storage -----------------------------------------------


def test_recording_kept_only_with_setting_and_consent(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "store_voice_recordings", False)
    assert not storage.should_store(True)
    monkeypatch.setattr(s, "store_voice_recordings", True)
    assert not storage.should_store(False)
    assert storage.should_store(True)


def test_recording_saved_to_local_dir(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "recordings_dir", str(tmp_path))
    monkeypatch.setattr(s, "s3_bucket", "")
    where = storage.store_recording(b"abc", ".webm", "mr")
    saved = list(tmp_path.rglob("*.webm"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"abc" and str(saved[0]) == where
    assert saved[0].name.startswith("mr-")


def test_recording_saved_to_s3(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "s3_bucket", "voice-bucket")
    monkeypatch.setattr(s, "s3_prefix", "voice")
    puts = []

    class FakeClient:
        def put_object(self, **kw):
            puts.append(kw)

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *a, **k: FakeClient()))
    where = storage.store_recording(b"abc", "webm", "hi")
    assert where.startswith("s3://voice-bucket/voice/") and where.endswith(".webm")
    assert puts[0]["ServerSideEncryption"] == "AES256" and puts[0]["Body"] == b"abc"


def test_transcribe_api_passes_consent(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.voice import adapters

    seen = {}

    def fake_transcribe(data, suffix, language_hint, consent):
        seen["consent"] = consent
        return adapters.Transcript(text="kanda", language="mr", confidence=0.9, needs_confirmation=False)

    monkeypatch.setattr(adapters, "transcribe", fake_transcribe)
    guest = {"X-Guest-Id": "test-guest-0001"}
    audio = {"audio": ("a.webm", b"xx", "audio/webm")}
    with TestClient(app) as c:
        r = c.post("/voice/transcribe", files=audio, data={"consent": "true"}, headers=guest)
        assert r.status_code == 200, r.text
        assert seen["consent"] is True
        c.post("/voice/transcribe", files=audio, headers=guest)
        assert seen["consent"] is False

