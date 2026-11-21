"""All-India coverage: every district, place names in questions, markets learnt from
the Agmarknet feed, and demo prices made on demand for districts outside the pilot."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.agent.data import load_series
from app.db.models import AgmarknetMarket, Price
from app.ingestion import prices as ingest
from app.ingestion import synthetic
from app.main import app
from app.reference import detect_district, load_reference

AS_OF = date(2026, 11, 8)


def test_every_district_of_india_is_listed_with_a_market():
    ref = load_reference()
    assert len(ref.districts) > 750 and len(ref.states) == 36
    assert list(ref.districts)[:2] == ["nashik", "pune"]  # the pilot stays the default
    for d in ref.districts.values():
        assert d.market_ids, d.id
        assert 6 < d.centre["lat"] < 37 and 68 < d.centre["lon"] < 98, d.id  # inside India
        for m in d.market_ids:
            assert ref.markets[m].district == d.id
    assert ref.districts["lucknow"].state == "Uttar Pradesh"
    assert {"hassan", "haveri"} <= set(ref.districts)  # two Karnataka districts the source file merged


def test_gps_finds_the_nearest_district_anywhere():
    scope = load_reference().scope(None, 26.85, 80.95)  # Lucknow
    assert scope.district == "lucknow" and "lucknow-market" in scope.market_ids


@pytest.mark.parametrize(
    ("text", "state", "district"),
    [
        ("What is the onion price in Lucknow?", None, "lucknow"),
        ("Bangalore tomato rate", None, "bengaluru-urban"),
        ("Osmanabad la kanda bhav", None, "dharashiv"),  # old name
        ("onion rate in Aurangabad", "Maharashtra", "chhatrapati-sambhajinagar"),  # the farmer's state wins
        ("onion rate in Aurangabad", "Bihar", "aurangabad"),
        ("नाशिकला कांदा विकू का?", None, "nashik"),
        # Everyday words that are also district names are not places.
        ("What is the mandi price today?", None, None),
        ("Should I hold my onion for a month?", None, None),
        ("shimla mirch ka bhav", None, None),
    ],
)
def test_detect_district(text, state, district):
    assert detect_district(text, prefer_state=state) == district


def test_feed_rows_match_markets_within_their_state():
    ref = load_reference()
    assert ref.market_by_agmarknet_name("Aurangabad", "Bihar").id == "aurangabad-market"
    assert ref.market_by_agmarknet_name("Aurangabad", "Maharashtra").id == "chhatrapati-sambhajinagar-market"
    assert ref.district_by_agmarknet_name("Maharashtra", "Nasik").id == "nashik"
    assert ref.district_by_agmarknet_name("Chattisgarh", "Raipur").id == "raipur"  # Agmarknet's spelling


def _rec(state, district, market, modal=2400, commodity="Onion"):
    return {
        "state": state, "district": district, "market": market, "commodity": commodity, "variety": "Other",
        "arrival_date": "08/11/2026", "min_price": str(modal - 200), "max_price": str(modal + 200), "modal_price": str(modal),
    }


@pytest.fixture
def clean_markets(session):
    yield
    session.execute(delete(AgmarknetMarket))
    session.execute(delete(Price).where(Price.source == "agmarknet_csv"))
    session.commit()
    load_reference.cache_clear()


def test_feed_teaches_new_markets_and_replaces_demo_prices(session, clean_markets, tmp_path):
    # A farmer in Lucknow asks first: the district gets demo prices.
    synthetic._ensured.discard("lucknow-market")
    load_series(session, "onion", AS_OF, markets=["lucknow-market"])
    demo = session.scalar(select(func.count()).select_from(Price).where(Price.market == "lucknow-market", Price.source == "synthetic"))
    assert demo > 1000

    # Then real Agmarknet rows arrive: the main market by its own name, plus a market we did not know.
    csv_file = tmp_path / "up.csv"
    import csv

    rows = [_rec("Uttar Pradesh", "Lucknow", "Lucknow"), _rec("Uttar Pradesh", "Lucknow", "Banthara", 2300), _rec("Pune", "x", "y")]
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert ingest.load_csv(session, csv_file) == 2

    ref = load_reference()
    assert "lucknow-banthara" in ref.districts["lucknow"].market_ids
    assert ref.markets["lucknow-banthara"].lat == ref.districts["lucknow"].centre["lat"]
    left = session.scalar(select(func.count()).select_from(Price).where(Price.market.in_(ref.districts["lucknow"].market_ids), Price.source == "synthetic"))
    assert left == 0  # demo prices are gone once the district has real ones
    series = load_series(session, "onion", AS_OF, markets=ref.districts["lucknow"].market_ids)
    assert {m: pts[-1].source for m, pts in series.items()} == {"lucknow-market": "agmarknet_csv", "lucknow-banthara": "agmarknet_csv"}


def test_pilot_districts_are_not_extended_by_the_feed(session, clean_markets):
    assert ingest.register_markets(session, [_rec("Maharashtra", "Pune", "Pune(Moshi)")]) == 0


def test_any_district_answers_with_demo_prices():
    with TestClient(app) as c:
        data = c.get("/prices", params={"crop": "okra", "district": "madurai"}).json()
        assert data["district"] == "madurai"
        market = data["markets"][0]
        assert market["market"] == "madurai-market" and market["status"] == "fresh" and market["source"] == "synthetic"
        r = c.post("/chat", json={"message": "Should I sell my okra now?", "language": "en", "district": "madurai"}, headers={"X-Guest-Id": "india-test-0001"}).json()
        assert r["decision"] in {"sell", "hold"}
        assert r["recommendation"]["best_market_now"] == "madurai-market"


def test_demo_prices_can_be_switched_off(session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_prices", False)
    synthetic._ensured.discard("leh-market")
    assert load_series(session, "onion", AS_OF, markets=["leh-market"]) == {}
