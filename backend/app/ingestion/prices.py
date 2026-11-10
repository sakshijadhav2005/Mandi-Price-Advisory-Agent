"""Price ingestion: data.gov.in (Agmarknet daily prices), Agmarknet CSV export, synthetic.

All loaders normalise to the same row dict and go through `upsert_prices`, which
records an IngestionRun so failures show up in the freshness status.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import IngestionRun, Price
from app.reference import load_reference

log = logging.getLogger(__name__)

DATA_GOV_URL = "https://api.data.gov.in/resource/{resource_id}"


def _match_market(name: str) -> str | None:
    name = name.strip().lower()
    for m in load_reference().markets.values():
        if m.name.lower() in name or name in m.name.lower() or m.id in name:
            return m.id
    return None


def _match_crop(commodity: str) -> str | None:
    commodity = commodity.strip().lower()
    for c in load_reference().crops.values():
        if c.agmarknet_commodity.lower() == commodity:
            return c.id
    return None


def _parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


def normalise_record(rec: dict, source: str) -> dict | None:
    """Map an Agmarknet-style record (API or CSV) to a Price row, or None if out of scope."""
    keys = {k.strip().lower().replace(" ", "_").replace("(rs./quintal)", "").strip("_"): v for k, v in rec.items()}
    crop = _match_crop(str(keys.get("commodity", "")))
    market = _match_market(str(keys.get("market", keys.get("market_name", ""))))
    if not crop or not market:
        return None
    try:
        raw_date = keys.get("arrival_date") or keys.get("price_date") or keys.get("reported_date")
        return {
            "crop": crop,
            "market": market,
            "price_date": _parse_date(str(raw_date)),
            "min_price": float(keys.get("min_price") or keys.get("min_x0020_price")),
            "modal_price": float(keys.get("modal_price") or keys.get("modal_x0020_price")),
            "max_price": float(keys.get("max_price") or keys.get("max_x0020_price")),
            "arrivals_tonnes": float(keys["arrivals_tonnes"]) if keys.get("arrivals_tonnes") else None,
            "source": source,
        }
    except (TypeError, ValueError) as exc:
        log.warning("skipping malformed record %s: %s", rec, exc)
        return None


def upsert_prices(session: Session, rows: list[dict], job_source: str) -> int:
    """Insert rows, replacing any existing observation with the same key. Returns rows written."""
    written = 0
    for row in rows:
        existing = session.scalar(
            select(Price).where(
                Price.crop == row["crop"],
                Price.market == row["market"],
                Price.price_date == row["price_date"],
                Price.source == row["source"],
            )
        )
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
        else:
            session.add(Price(**row))
        written += 1
    session.add(IngestionRun(job="prices", source=job_source, status="ok", rows=written))
    session.commit()
    return written


def bulk_insert_prices(session: Session, rows: list[dict], job_source: str) -> int:
    """Fast path for an empty table (seeding)."""
    session.bulk_insert_mappings(Price, rows)
    session.add(IngestionRun(job="prices", source=job_source, status="ok", rows=len(rows)))
    session.commit()
    return len(rows)


def record_failure(session: Session, source: str, message: str) -> None:
    session.add(IngestionRun(job="prices", source=source, status="failed", message=message[:2000]))
    session.commit()


def load_csv(session: Session, path: Path, source: str = "agmarknet_csv") -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for rec in csv.DictReader(fh) if (r := normalise_record(rec, source))]
    return upsert_prices(session, rows, source)


def fetch_data_gov_in(session: Session, limit: int = 1000) -> int:
    """Pull today's Agmarknet prices for every configured district and crop from data.gov.in.

    Requires DATA_GOV_IN_API_KEY. The resource publishes the current day's
    prices only, so history has to be built by running this daily (or by
    importing Agmarknet CSV exports with `load_csv`).
    """
    settings = get_settings()
    if not settings.data_gov_in_api_key:
        raise RuntimeError("DATA_GOV_IN_API_KEY is not set")
    ref = load_reference()
    rows: list[dict] = []
    try:
        for district, crop in ((d, c) for d in ref.districts.values() for c in ref.crops.values()):
            resp = httpx.get(
                DATA_GOV_URL.format(resource_id=settings.data_gov_in_resource_id),
                params={
                    "api-key": settings.data_gov_in_api_key,
                    "format": "json",
                    "limit": limit,
                    "filters[state.keyword]": district.state,
                    "filters[district]": district.name,
                    "filters[commodity]": crop.agmarknet_commodity,
                },
                timeout=30,
            )
            resp.raise_for_status()
            for rec in resp.json().get("records", []):
                if row := normalise_record(rec, "data_gov_in"):
                    rows.append(row)
    except Exception as exc:  # network, HTTP, or schema change
        record_failure(session, "data_gov_in", repr(exc))
        raise
    return upsert_prices(session, rows, "data_gov_in")
