"""LOCKED_DISTRICT: a single-district deployment (e.g. Pune only)."""

import pytest
from fastapi.testclient import TestClient

from app.agent.service import answer_query
from app.config import get_settings
from app.main import app
from app.reference import effective_district, load_reference, locked_district

GUEST = {"X-Guest-Id": "locked-district-test"}


@pytest.fixture
def pune_only(monkeypatch):
    monkeypatch.setattr(get_settings(), "locked_district", "pune")


def test_off_by_default():
    assert locked_district() is None and effective_district("nashik") == "nashik"


def test_meta_lists_only_the_locked_district(pune_only):
    with TestClient(app) as c:
        meta = c.get("/meta").json()
    assert meta["locked_district"] == "pune" and meta["district"] == "pune"
    assert [d["id"] for d in meta["districts"]] == ["pune"] and meta["states"] == ["Maharashtra"]
    assert meta["markets"] and all(m["district"] == "pune" for m in meta["markets"])


def test_answers_prices_and_alerts_use_the_locked_district(pune_only, session):
    pune_markets = set(load_reference().districts["pune"].market_ids)
    ans = answer_query(session, "Should I sell onion at Nashik?", language="en", use_llm=False, district="nashik")
    assert ans.recommendation["assumptions"]["district"] == "pune"
    assert ans.recommendation["best_market_now"] in pune_markets
    with TestClient(app) as c:
        data = c.get("/prices", params={"crop": "onion", "district": "nashik"}).json()
        assert data["district"] == "pune" and {m["market"] for m in data["markets"]} <= pune_markets
        nashik_market = load_reference().districts["nashik"].market_ids[0]
        assert c.get("/prices", params={"crop": "onion", "market": nashik_market}).status_code == 404
        alert = c.post("/alerts", json={"crop": "onion", "direction": "above", "threshold": 3000, "district": "nashik"}, headers=GUEST).json()
        assert alert["district"] == "pune"


def test_bad_setting_is_reported(monkeypatch):
    monkeypatch.setattr(get_settings(), "locked_district", "atlantis")
    with pytest.raises(ValueError, match="not a known district"):
        locked_district()
