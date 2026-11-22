"""Catch-up of real prices by date from data.gov.in (no manual downloads).

The daily fetch (`fetch_data_gov_in`) only keeps what data.gov.in returns on the day it
runs; a day the service is down would otherwise be lost for good. The data.gov.in
resource "Variety-wise Daily Market Prices Data of Commodity" (DATA_GOV_IN_RESOURCE_ID)
keeps past days and can be filtered by Arrival_Date, so this module:

- finds the days in the last `days` that have no real price for a district's markets,
- asks data.gov.in for each of those days (one district at a time, small requests),
- stores the rows like any other real price (real beats demo on the same day), and
- once a pilot district has enough real days, deletes its demo prices altogether.

data.gov.in's filter field names differ between its resources ("State" / "State.keyword"
/ "state"), and a wrong name is silently ignored, so each spelling is tried in turn and
one is only trusted when the rows it returns really are for the asked date and district.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Price
from app.ingestion.prices import DATA_GOV_URL, _get_with_retries, _keys, _parse_date, normalise_record, record_failure, upsert_prices
from app.reference import load_reference

log = logging.getLogger(__name__)

PAGE = 1000
MAX_PAGES = 10
# Delete a pilot district's demo prices once it has real prices on this many days.
REAL_DAYS_TO_DROP_DEMO = 14

FILTER_SPELLINGS: list[dict[str, str]] = [
    {"state": "filters[State.keyword]", "district": "filters[District.keyword]", "date": "filters[Arrival_Date]"},
    {"state": "filters[State]", "district": "filters[District]", "date": "filters[Arrival_Date]"},
    {"state": "filters[state]", "district": "filters[district]", "date": "filters[arrival_date]"},
]
_working: dict[str, str] | None = None  # the spelling that worked last (per process)


class CatchUpError(RuntimeError):
    pass


def _rows_match(records: list[dict], day: date, district_names: set[str]) -> bool:
    """True when every returned row is for the asked day and district (the filters were applied)."""
    for rec in records:
        k = _keys(rec)
        try:
            if _parse_date(str(k.get("arrival_date", ""))) != day:
                return False
        except ValueError:
            return False
        if str(k.get("district", "")).strip().lower() not in district_names:
            return False
    return True


def _fetch(spelling: dict[str, str], day: date, state: str, district: str) -> list[dict]:
    s = get_settings()
    out: list[dict] = []
    for page in range(MAX_PAGES):
        resp = _get_with_retries(
            DATA_GOV_URL.format(resource_id=s.data_gov_in_resource_id),
            params={
                "api-key": s.data_gov_in_api_key,
                "format": "json",
                "limit": PAGE,
                "offset": page * PAGE,
                spelling["state"]: state,
                spelling["district"]: district,
                spelling["date"]: day.strftime("%d/%m/%Y"),
            },
        )
        batch = resp.json().get("records", [])
        out.extend(batch)
        if len(batch) < PAGE:
            break
    return out


def fetch_day(day: date, state: str, district: str, accepted: set[str] | None = None) -> list[dict]:
    """Raw data.gov.in records for one district on one day ([] when none were reported)."""
    global _working
    spellings = [_working] if _working else FILTER_SPELLINGS
    for spelling in spellings:
        records = _fetch(spelling, day, state, district)
        if records and _rows_match(records, day, accepted or {district.lower()}):
            _working = spelling
            return records
        if _working:  # the known spelling returned nothing: no prices that day
            return []
    return []


def missing_days(session: Session, district: str, days: int, today: date) -> list[date]:
    """Days in the last `days` (before today) without any real price in the district."""
    markets = load_reference().districts[district].market_ids
    start = today - timedelta(days=days)
    have = set(
        session.scalars(
            select(Price.price_date).where(Price.market.in_(markets), Price.source != "synthetic", Price.price_date >= start).distinct()
        )
    )
    return [d for d in (start + timedelta(n) for n in range(days)) if d not in have and d < today]


def drop_demo_when_enough_real(session: Session, district: str) -> int:
    markets = load_reference().districts[district].market_ids
    real_days = session.scalar(
        select(func.count(func.distinct(Price.price_date))).where(Price.market.in_(markets), Price.source != "synthetic")
    ) or 0
    if real_days < REAL_DAYS_TO_DROP_DEMO:
        return 0
    n = session.execute(delete(Price).where(Price.source == "synthetic", Price.market.in_(markets))).rowcount or 0
    session.commit()
    if n:
        log.info("%s has real prices on %d days: removed %d demo price rows", district, real_days, n)
    return n


def catch_up(session: Session, districts: list[str], days: int = 30, today: date | None = None) -> dict:
    """Fill the days without real prices for each district. Raises CatchUpError when
    data.gov.in cannot be reached at all (so the caller can alert)."""
    s = get_settings()
    if not s.data_gov_in_api_key:
        raise CatchUpError("DATA_GOV_IN_API_KEY is not set")
    today = today or date.today()
    ref = load_reference()
    summary: dict[str, dict] = {}
    for district in districts:
        d = ref.districts[district]
        state, name = d.state, (d.agmarknet_names or (d.name,))[0]
        accepted = {n.lower() for n in (d.name, *d.agmarknet_names)}
        filled, empty, rows_total = [], [], 0
        for day in missing_days(session, district, days, today):
            try:
                records = fetch_day(day, state, name, accepted)
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                record_failure(session, "data_gov_in_history", repr(exc))
                if not filled and not empty:
                    raise CatchUpError(f"data.gov.in unreachable: {exc!r}") from exc
                log.warning("price catch-up stopped at %s for %s: %r", day, district, exc)
                break
            rows = [r for rec in records if (r := normalise_record(rec, "data_gov_in"))]
            if rows:
                rows_total += upsert_prices(session, rows, "data_gov_in_history")
                filled.append(day.isoformat())
            else:
                empty.append(day.isoformat())  # market holiday, or not reported yet
        summary[district] = {"days_filled": len(filled), "days_without_prices": len(empty), "rows": rows_total,
                             "demo_rows_removed": drop_demo_when_enough_real(session, district)}
    return summary
