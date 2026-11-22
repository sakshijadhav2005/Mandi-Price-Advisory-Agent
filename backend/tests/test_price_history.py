"""Price catch-up by date from data.gov.in: missed days are filled, wrong filter
spellings are detected, outages raise, and demo prices go once there is enough real data."""

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db.models import Price
from app.ingestion import price_history
from app.ingestion.price_history import CatchUpError, catch_up, missing_days

TODAY = date(2026, 11, 22)
PUNE_MARKETS = ("pune", "chakan", "manchar", "junnar", "baramati")


@pytest.fixture
def clean(session, monkeypatch):
    def wipe():
        session.execute(delete(Price).where(Price.market.in_(PUNE_MARKETS)))
        session.commit()

    wipe()
    monkeypatch.setattr(get_settings(), "data_gov_in_api_key", "test-key")
    monkeypatch.setattr(price_history, "_working", None)
    monkeypatch.setattr("app.ingestion.prices.time.sleep", lambda s: None)
    yield
    wipe()


def record(day: date, market="Pune", district="Pune", modal=4700):
    return {"State": "Maharashtra", "District": district, "Market": market, "Commodity": "Onion", "Variety": "Red",
            "Grade": "FAQ", "Arrival_Date": day.strftime("%d/%m/%Y"), "Min_Price": modal - 500, "Max_Price": modal + 500,
            "Modal_Price": modal, "Commodity_Code": "23"}


def fake_service(calls, only_spelling="filters[State.keyword]", holidays=()):
    """Applies the filters only when they use `only_spelling`'s style; otherwise it ignores
    them (like data.gov.in) and returns rows for any date and district."""

    def get(url, params=None, **kw):
        calls.append(params)
        req = httpx.Request("GET", url)
        if params["offset"] > 0:
            return httpx.Response(200, json={"records": []}, request=req)
        if only_spelling in params:
            raw = params.get("filters[Arrival_Date]") or params["filters[arrival_date]"]
            day = date(*reversed([int(x) for x in raw.split("/")]))
            recs = [] if day in holidays else [record(day)]
        else:
            recs = [record(date(2026, 1, 5), district="Nashik", market="Lasalgaon")]
        return httpx.Response(200, json={"records": recs}, request=req)

    return get


def test_missing_days_are_filled_by_date(clean, session, monkeypatch):
    calls = []
    holiday = TODAY - timedelta(days=3)
    monkeypatch.setattr(httpx, "get", fake_service(calls, holidays={holiday}))
    assert len(missing_days(session, "pune", 5, TODAY)) == 5
    out = catch_up(session, ["pune"], days=5, today=TODAY)
    assert out["pune"]["days_filled"] == 4 and out["pune"]["days_without_prices"] == 1
    rows = session.scalars(select(Price).where(Price.market == "pune", Price.crop == "onion")).all()
    assert {r.price_date for r in rows} == {TODAY - timedelta(days=n) for n in (1, 2, 4, 5)}
    assert all(r.source == "data_gov_in" and r.modal_price == 4700 for r in rows)
    assert calls[0]["filters[State.keyword]"] == "Maharashtra" and calls[0]["filters[Arrival_Date]"] == "17/11/2026"
    # A second run asks only for the day still missing (the holiday).
    calls.clear()
    catch_up(session, ["pune"], days=5, today=TODAY)
    assert [c["filters[Arrival_Date]"] for c in calls] == [holiday.strftime("%d/%m/%Y")]


def test_ignored_filter_spelling_is_not_trusted(clean, session, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "get", fake_service(calls, only_spelling="filters[state]"))
    out = catch_up(session, ["pune"], days=2, today=TODAY)
    assert out["pune"]["days_filled"] == 2
    state_keys = ("filters[State.keyword]", "filters[State]", "filters[state]")
    assert [next(k for k in state_keys if k in c) for c in calls[:3]] == list(state_keys)
    # Rows from the unfiltered answers (Nashik, January) were not stored.
    stray = select(func.count()).select_from(Price).where(Price.price_date == date(2026, 1, 5), Price.source == "data_gov_in")
    assert session.scalar(stray) == 0


def test_outage_raises_and_demo_prices_go_after_enough_real_days(clean, session, monkeypatch):
    def down(url, params=None, **kw):
        return httpx.Response(502, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", down)
    with pytest.raises(CatchUpError):
        catch_up(session, ["pune"], days=3, today=TODAY)

    session.add(Price(crop="onion", market="pune", price_date=TODAY - timedelta(days=40), min_price=1, modal_price=2, max_price=3, source="synthetic"))
    session.commit()
    monkeypatch.setattr(httpx, "get", fake_service([]))
    out = catch_up(session, ["pune"], days=price_history.REAL_DAYS_TO_DROP_DEMO, today=TODAY)
    assert out["pune"]["demo_rows_removed"] == 1
    assert session.scalar(select(func.count()).select_from(Price).where(Price.source == "synthetic", Price.market == "pune")) == 0
