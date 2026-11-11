"""Real-price ingestion: exact market matching, variety aggregation, and the
real-over-synthetic rule in the series loader."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from app.agent.data import load_series
from app.db.models import Price
from app.ingestion import prices as ingest
from app.reference import load_reference


def _rec(market: str, variety: str, modal: float, district: str = "Nashik", commodity: str = "Onion", day: str = "08/11/2026") -> dict:
    return {
        "state": "Maharashtra",
        "district": district,
        "market": market,
        "commodity": commodity,
        "variety": variety,
        "grade": "FAQ",
        "arrival_date": day,
        "min_price": str(modal - 300),
        "max_price": str(modal + 300),
        "modal_price": str(modal),
    }


# ----------------------------------------------------------------------------- market matching


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("Lasalgaon", "lasalgaon"),
        ("LASALGAON", "lasalgaon"),
        ("Pimpalgaon Baswant", "pimpalgaon"),
        ("Pimpalgaon(B)", "pimpalgaon"),
        ("Nasik", "nashik"),
        ("Nashik", "nashik"),
        ("Pune", "pune"),
        ("Pune(Gultekdi)", "pune"),
        ("Khed(Chakan)", "chakan"),
    ],
)
def test_published_market_names_match_exactly(published, expected):
    assert ingest._match_market(published) == expected


@pytest.mark.parametrize("published", ["Pune(Moshi)", "Pune(Pimpri)", "Pune(Khadiki)", "Nasik Road", "Solapur", ""])
def test_other_markets_are_not_mistaken_for_pilot_markets(published):
    # The old substring matcher mapped every Pune(...) market onto Gultekdi.
    assert ingest._match_market(published) is None


def test_every_pilot_market_lists_its_agmarknet_names():
    ref = load_reference()
    for m in ref.markets.values():
        assert m.agmarknet_names, m.id
        assert ref.market_by_agmarknet_name(m.agmarknet_names[0]).id == m.id


# ----------------------------------------------------------------------------- varieties


def test_preferred_variety_wins_over_others():
    rows = [ingest.normalise_record(_rec("Lasalgaon", v, p), "data_gov_in") for v, p in [("Other", 1500), ("Red", 2600), ("White", 2000)]]
    out = ingest.aggregate_varieties(rows)
    assert len(out) == 1
    assert out[0]["modal_price"] == 2600  # "Red" is first in onion's preferred list
    assert "variety" not in out[0]


def test_unlisted_varieties_are_averaged_with_overall_min_and_max():
    rows = [ingest.normalise_record(_rec("Lasalgaon", v, p), "data_gov_in") for v, p in [("Pole", 2000), ("1st Sort", 3000)]]
    out = ingest.aggregate_varieties(rows)
    assert len(out) == 1
    assert out[0]["modal_price"] == 2500
    assert out[0]["min_price"] == 1700
    assert out[0]["max_price"] == 3300


def test_arrivals_weight_the_average_when_known():
    a = ingest.normalise_record(_rec("Yeola", "Pole", 2000) | {"arrivals_tonnes": "30"}, "data_gov_in")
    b = ingest.normalise_record(_rec("Yeola", "1st Sort", 3000) | {"arrivals_tonnes": "10"}, "data_gov_in")
    out = ingest.aggregate_varieties([a, b])
    assert out[0]["modal_price"] == 2250
    assert out[0]["arrivals_tonnes"] == 40


def test_different_markets_and_days_stay_separate():
    rows = [
        ingest.normalise_record(_rec("Lasalgaon", "Red", 2600), "data_gov_in"),
        ingest.normalise_record(_rec("Yeola", "Red", 2500), "data_gov_in"),
        ingest.normalise_record(_rec("Lasalgaon", "Red", 2700, day="07/11/2026"), "data_gov_in"),
    ]
    assert len(ingest.aggregate_varieties(rows)) == 3


# ----------------------------------------------------------------------------- fetch (fake API)


def test_fetch_data_gov_in_filters_by_state_and_commodity_and_keeps_only_pilot_markets(session, monkeypatch):
    calls: list[dict] = []

    def fake_get(url, params, timeout):
        calls.append(params)
        commodity = params["filters[commodity]"]
        records = [
            _rec("Lasalgaon", "Red", 2600, commodity=commodity),
            _rec("Lasalgaon", "Other", 1500, commodity=commodity),
            _rec("Pune(Moshi)", "Local", 2200, district="Pune", commodity=commodity),  # not a pilot market
            _rec("Pune", "Local", 2300, district="Pune", commodity=commodity),
        ]
        return httpx.Response(200, json={"records": records}, request=httpx.Request("GET", url))

    monkeypatch.setattr(ingest.httpx, "get", fake_get)
    monkeypatch.setattr(ingest.get_settings(), "data_gov_in_api_key", "test-key")
    try:
        n = ingest.fetch_data_gov_in(session)
        assert n == 6  # (lasalgaon + pune) x 3 crops
        assert len(calls) == 3  # one call per crop for the single pilot state
        assert all("filters[district]" not in c for c in calls)
        assert {c["filters[state.keyword]"] for c in calls} == {"Maharashtra"}
        rows = session.scalars(select(Price).where(Price.source == "data_gov_in")).all()
        assert {r.market for r in rows} == {"lasalgaon", "pune"}
        onion_lasalgaon = next(r for r in rows if r.crop == "onion" and r.market == "lasalgaon")
        assert onion_lasalgaon.modal_price == 2600  # preferred "Red" variety, not an average with "Other"
    finally:
        session.execute(delete(Price).where(Price.source == "data_gov_in"))
        session.commit()


# ----------------------------------------------------------------------------- real beats synthetic


def test_load_series_prefers_real_rows_over_synthetic_for_the_same_day(session):
    # 8 Nov 2026 is a Sunday (no synthetic row); use the latest day that has one.
    as_of = max(p.price_date for p in load_series(session, "onion", date(2026, 11, 8), lookback_days=7)["lasalgaon"])
    session.add(Price(crop="onion", market="lasalgaon", price_date=as_of, min_price=1, modal_price=9999, max_price=10000, source="data_gov_in"))
    session.add(
        Price(crop="onion", market="lasalgaon", price_date=as_of - timedelta(days=1), min_price=1, modal_price=8888, max_price=10000, source="data_gov_in")
    )
    session.commit()
    try:
        pts = load_series(session, "onion", as_of, lookback_days=7)["lasalgaon"]
        by_day = {p.price_date: p for p in pts}
        assert by_day[as_of].modal_price == 9999 and by_day[as_of].source == "data_gov_in"
        assert by_day[as_of - timedelta(days=1)].modal_price == 8888
        assert len(pts) == len(by_day)  # one point per day, never two
        assert [p.price_date for p in pts] == sorted(p.price_date for p in pts)
        older = [p for p in pts if p.price_date < as_of - timedelta(days=1)]
        assert older and all(p.source == "synthetic" for p in older)
    finally:
        session.execute(delete(Price).where(Price.source == "data_gov_in"))
        session.commit()
