"""Sarvam translation of the IMD crop advice: request shape, long text, failures, answers."""

from datetime import date

import httpx
import pytest
from sqlalchemy import delete

from app.advisory import agromet
from app.advisory.agromet import fetch_bulletin, translate_stored
from app.agent.service import answer_query
from app.config import get_settings
from app.db.models import AgrometBulletin
from app.translation import sarvam
from tests.test_agromet import bulletin_text, serve

AS_OF = date(2026, 11, 8)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "key-1")
    calls = []

    def fake_post(url, **kw):
        calls.append(kw["json"])
        body = kw["json"]
        return httpx.Response(200, json={"translated_text": f"[{body['target_language_code']}] {body['input']}"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(sarvam.httpx, "post", fake_post)
    return calls


def test_request_and_long_text(key):
    assert sarvam.translate("Spray neem extract.", "mr") == "[mr-IN] Spray neem extract."
    body = key[0]
    assert body["source_language_code"] == "en-IN" and body["model"] == "sarvam-translate:v1" and body["numerals_format"] == "international"
    long = "This is one sentence of advice. " * 120  # ~3,800 characters
    sarvam.translate(long, "hi")
    assert len(key) >= 3 and all(len(b["input"]) <= sarvam.MAX_CHARS for b in key[1:])


def test_no_key_or_failure(monkeypatch):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "")
    with pytest.raises(sarvam.TranslationUnavailable):
        sarvam.translate("x", "mr")
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "k")
    monkeypatch.setattr(sarvam.httpx, "post", lambda url, **kw: httpx.Response(500, request=httpx.Request("POST", url)))
    with pytest.raises(sarvam.TranslationUnavailable):
        sarvam.translate("x", "mr")


@pytest.fixture
def clean(tmp_path, monkeypatch, session):
    monkeypatch.setattr(get_settings(), "agromet_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "agromet_districts", "pune")
    session.execute(delete(AgrometBulletin))
    session.commit()
    yield
    session.execute(delete(AgrometBulletin))
    session.commit()


def test_bulletin_translated_once_and_used_in_marathi_answers(clean, key, monkeypatch, session):
    serve(monkeypatch, [(200, b"%PDF-1.4 tr", bulletin_text())])
    fetch_bulletin(session, "pune")
    row = session.query(AgrometBulletin).one()
    assert set(row.data["translations"]) == {"mr", "hi"}
    assert row.data["translations"]["mr"]["crops"]["onion"].startswith("[mr-IN] ")
    ans = answer_query(session, "कांद्यावर कीड आहे, या आठवड्यात काय करू?", language="mr", as_of=AS_OF, use_llm=False, district="pune")
    assert "कांदा साठी सल्ला: [mr-IN] Vegetative Growth Stage" in ans.text and "(यंत्र अनुवाद" in ans.text


def test_without_key_bulletin_still_stored_and_can_be_translated_later(clean, monkeypatch, session):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "")
    serve(monkeypatch, [(200, b"%PDF-1.4 later", bulletin_text())])
    fetch_bulletin(session, "pune")
    assert session.query(AgrometBulletin).one().data["translations"] == {}
    ans = answer_query(session, "कांद्यावर कीड आहे, या आठवड्यात काय करू?", language="mr", as_of=AS_OF, use_llm=False, district="pune")
    assert "साठी सल्ला:" not in ans.text and "https://mausam.imd.gov.in" in ans.text
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "key-1")
    monkeypatch.setattr(sarvam.httpx, "post", lambda url, **kw: httpx.Response(200, json={"translated_text": "अनुवाद"}, request=httpx.Request("POST", url)))
    assert translate_stored(session) == 1
    session.expire_all()
    assert session.query(AgrometBulletin).one().data["translations"]["mr"]["crops"]["onion"] == "अनुवाद"
    assert agromet.TRANSLATE_TO == ("mr", "hi")
