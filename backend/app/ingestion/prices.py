"""Price ingestion: data.gov.in (Agmarknet daily prices), Agmarknet CSV export, synthetic.

All loaders normalise to the same row dict and go through `upsert_prices`, which
records an IngestionRun so failures show up in the freshness status.
"""

from __future__ import annotations

import csv
from collections import Counter
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
    """Exact match on the Agmarknet market names listed in reference.json.

    Substring matching is not safe here: Agmarknet lists Pune(Moshi), Pune(Pimpri)
    and others as separate markets, and all of them contain "pune".
    """
    m = load_reference().market_by_agmarknet_name(name)
    return m.id if m else None


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
            "variety": str(keys.get("variety") or "").strip(),
        }
    except (TypeError, ValueError) as exc:
        log.warning("skipping malformed record %s: %s", rec, exc)
        return None


def _mean(values: list[float], weights: list[float | None]) -> float:
    if all(w for w in weights):
        total = sum(w for w in weights if w)
        return sum(v * (w or 0) for v, w in zip(values, weights)) / total
    return sum(values) / len(values)


def aggregate_varieties(rows: list[dict]) -> list[dict]:
    """Collapse one row per variety into one row per crop, market, day and source.

    Agmarknet publishes a separate row for each variety traded. If the crop lists
    preferred varieties in reference.json, the best one present is used; otherwise
    the varieties are averaged (weighted by arrivals when they are known), with
    the overall min and max. A single row passes through unchanged.
    """
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["crop"], r["market"], r["price_date"], r["source"]), []).append(r)
    crops = load_reference().crops
    out: list[dict] = []
    for (crop, _market, _day, _source), group in groups.items():
        chosen = group
        for pref in crops[crop].agmarknet_varieties:
            hits = [r for r in group if r.get("variety", "").lower() == pref.lower()]
            if hits:
                chosen = hits
                break
        base = dict(chosen[0])
        if len(chosen) > 1:
            weights = [r["arrivals_tonnes"] for r in chosen]
            base["modal_price"] = round(_mean([r["modal_price"] for r in chosen], weights), 2)
            base["min_price"] = min(r["min_price"] for r in chosen)
            base["max_price"] = max(r["max_price"] for r in chosen)
            arrivals = [r["arrivals_tonnes"] for r in chosen if r["arrivals_tonnes"] is not None]
            base["arrivals_tonnes"] = sum(arrivals) if arrivals else None
        base.pop("variety", None)
        out.append(base)
    return out


def upsert_prices(session: Session, rows: list[dict], job_source: str) -> int:
    """Insert rows, replacing any existing observation with the same key. Returns rows written."""
    rows = aggregate_varieties(rows)
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
    unmatched: Counter[str] = Counter()
    try:
        # One call per state and commodity. The district filter is deliberately
        # left out: Agmarknet has spelt districts differently over the years
        # ("Nasik" / "Nashik"), and a wrong spelling silently returns nothing.
        # Markets are matched by their exact published names instead.
        states = sorted({d.state for d in ref.districts.values()})
        for state, crop in ((st, c) for st in states for c in ref.crops.values()):
            resp = httpx.get(
                DATA_GOV_URL.format(resource_id=settings.data_gov_in_resource_id),
                params={
                    "api-key": settings.data_gov_in_api_key,
                    "format": "json",
                    "limit": limit,
                    "filters[state.keyword]": state,
                    "filters[commodity]": crop.agmarknet_commodity,
                },
                timeout=60,
            )
            resp.raise_for_status()
            for rec in resp.json().get("records", []):
                if row := normalise_record(rec, "data_gov_in"):
                    rows.append(row)
                else:
                    keys = {k.strip().lower(): v for k, v in rec.items()}
                    unmatched[f"{keys.get('district', '?')} / {keys.get('market', '?')}"] += 1
    except Exception as exc:  # noqa: BLE001 - any failure is recorded for ops
        record_failure(session, "data_gov_in", repr(exc))
        raise
    if unmatched:
        log.info(
            "data.gov.in rows for markets not in reference.json (add their names to agmarknet_names if wanted): %s",
            ", ".join(f"{name} x{n}" for name, n in unmatched.most_common(40)),
        )
    return upsert_prices(session, rows, "data_gov_in")
