"""Price ingestion: data.gov.in (Agmarknet daily prices), Agmarknet CSV export, synthetic.

All loaders normalise to the same row dict and go through `upsert_prices`, which
records an IngestionRun so failures show up in the freshness status.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
import logging
import time
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AgmarknetMarket, IngestionRun, Price
from app.reference import load_reference

log = logging.getLogger(__name__)

DATA_GOV_URL = "https://api.data.gov.in/resource/{resource_id}"


def _match_market(name: str, state: str | None = None) -> str | None:
    """Exact match on a known market's Agmarknet name, within the row's state if given.

    Substring matching is not safe here: Agmarknet lists Pune(Moshi), Pune(Pimpri)
    and others as separate markets, and all of them contain "pune". The state keeps
    same-named markets apart (Aurangabad in Bihar and in Maharashtra).
    """
    m = load_reference().market_by_agmarknet_name(name, state or None)
    return m.id if m else None


def _keys(rec: dict) -> dict:
    """Agmarknet field names, normalised ("Modal Price (Rs./Quintal)" -> "modal_price")."""
    return {k.strip().lower().replace(" ", "_").replace("(rs./quintal)", "").strip("_"): v for k, v in rec.items()}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def register_markets(session: Session, records: list[dict]) -> int:
    """Add markets the feed reports in a known district that we do not know yet.

    This is how the app learns the markets of all of India from Agmarknet. A row's
    district is matched within its state (spellings differ: "Nasik"); the market is
    placed at the district centre, since Agmarknet publishes no coordinates. The
    hand-checked pilot districts are not extended: their lists are deliberate.
    Returns the number of markets added (the reference data is reloaded if any).
    """
    ref = load_reference()
    new: dict[str, AgmarknetMarket] = {}
    seen: set[tuple[str, str]] = set()
    for rec in records:
        k = _keys(rec)
        state, district, market = (str(k.get(f) or "").strip() for f in ("state", "district", "market"))
        if not (state and district and market) or (state, market) in seen:
            continue
        seen.add((state, market))
        if ref.market_by_agmarknet_name(market, state):
            continue
        d = ref.district_by_agmarknet_name(state, district)
        if d is None or d.id in ref.curated_districts:
            continue
        m_id = f"{d.id}-{_slug(market)}"[:64]
        if m_id in ref.markets or m_id in new or session.get(AgmarknetMarket, m_id):
            continue
        new[m_id] = AgmarknetMarket(
            id=m_id, name=market, agmarknet_name=market, state=state, district=d.id, lat=d.centre["lat"], lon=d.centre["lon"]
        )
    if new:
        session.add_all(new.values())
        session.commit()
        load_reference.cache_clear()
        log.info("registered %d new Agmarknet markets: %s", len(new), ", ".join(sorted(new)[:30]))
    return len(new)


def drop_demo_prices_where_real(session: Session, rows: list[dict]) -> int:
    """Once real prices reach a district outside the pilot, delete its demo prices.

    Otherwise a district's demo market could still show as "fresh" beside its real
    ones. The pilot keeps its seeded history (real rows win day by day there).
    """
    ref = load_reference()
    districts = {ref.markets[r["market"]].district for r in rows if r["market"] in ref.markets and r.get("source") != "synthetic"}
    districts -= set(ref.curated_districts)
    if not districts:
        return 0
    market_ids = [m for d in districts for m in ref.districts[d].market_ids]
    n = session.execute(delete(Price).where(Price.source == "synthetic", Price.market.in_(market_ids))).rowcount or 0
    session.commit()
    if n:
        log.info("removed %d demo price rows now that %s have real prices", n, ", ".join(sorted(districts)))
    return n


def _match_crop(commodity: str) -> str | None:
    commodity = commodity.strip().lower()
    for c in load_reference().crops.values():
        if any(name.lower() == commodity for name in c.agmarknet_commodities):
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
    keys = _keys(rec)
    crop = _match_crop(str(keys.get("commodity", "")))
    market = _match_market(str(keys.get("market", keys.get("market_name", ""))), str(keys.get("state") or "").strip() or None)
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
        records = list(csv.DictReader(fh))
    register_markets(session, [r for r in records if _match_crop(str(_keys(r).get("commodity", "")))])
    rows = [r for rec in records if (r := normalise_record(rec, source))]
    n = upsert_prices(session, rows, source)
    drop_demo_prices_where_real(session, rows)
    return n


# data.gov.in is often slow or briefly unreachable; a daily job should not give up on one timeout.
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_S = 60.0
# Stop a run when this many calls in a row fail before any succeeds (data.gov.in is down).
GIVE_UP_AFTER = 3
# Pages per commodity (of `limit` rows); one day of onion across India is a few thousand rows.
MAX_PAGES = 20
RETRY_BACKOFF_S = 20.0


def _get_with_retries(url: str, params: dict) -> httpx.Response:
    """GET with retries on timeouts, connection errors and 5xx. Re-raises the last error."""
    last: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, params=params, timeout=FETCH_TIMEOUT_S)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(f"server error {resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # a 4xx (bad key, bad resource id) will not fix itself
            if attempt < FETCH_ATTEMPTS:
                log.warning("data.gov.in attempt %d/%d failed (%s); retrying in %.0fs", attempt, FETCH_ATTEMPTS, exc, RETRY_BACKOFF_S)
                time.sleep(RETRY_BACKOFF_S)
    assert last is not None
    raise last


def fetch_data_gov_in(session: Session, limit: int = 1000) -> int:
    """Pull today's Agmarknet prices for every crop, across India, from data.gov.in.

    Requires DATA_GOV_IN_API_KEY. The resource publishes the current day's
    prices only, so history has to be built by running this daily (or by
    importing Agmarknet CSV exports with `load_csv`). Markets in districts we
    know but have not seen before are registered on the way (register_markets).
    """
    settings = get_settings()
    if not settings.data_gov_in_api_key:
        raise RuntimeError("DATA_GOV_IN_API_KEY is not set")
    ref = load_reference()
    rows: list[dict] = []
    records: list[dict] = []
    unmatched: Counter[str] = Counter()
    failed: list[str] = []
    last_error: Exception | None = None
    n_calls = 0
    try:
        # One call (and further pages) per commodity spelling, for all of India.
        # No state or district filter: Agmarknet has spelt districts differently
        # over the years ("Nasik" / "Nashik"), and a wrong spelling silently
        # returns nothing. Rows are matched to markets by state and name instead.
        # A crop can have several published spellings; an unused one returns nothing.
        for commodity in (name for c in ref.crops.values() for name in c.agmarknet_commodities):
            n_calls += 1
            try:
                for page in range(MAX_PAGES):
                    resp = _get_with_retries(
                        DATA_GOV_URL.format(resource_id=settings.data_gov_in_resource_id),
                        params={
                            "api-key": settings.data_gov_in_api_key,
                            "format": "json",
                            "limit": limit,
                            "offset": page * limit,
                            "filters[commodity]": commodity,
                        },
                    )
                    batch = resp.json().get("records", [])
                    records.extend(batch)
                    if len(batch) < limit:
                        break
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise  # a bad key or request fails every call the same way
                # One slow commodity should not cost the prices of all the others.
                failed.append(commodity)
                last_error = exc
                if len(failed) == n_calls >= GIVE_UP_AFTER:
                    raise  # nothing has worked yet: the service is down, not one commodity
                continue
        if last_error is not None and len(failed) == n_calls:
            raise last_error
    except Exception as exc:  # noqa: BLE001 - any failure is recorded for ops
        record_failure(session, "data_gov_in", repr(exc))
        raise
    if failed:
        log.warning("data.gov.in: %d of %d calls failed after retries, skipped: %s", len(failed), n_calls, ", ".join(failed))
    register_markets(session, records)
    for rec in records:
        if row := normalise_record(rec, "data_gov_in"):
            rows.append(row)
        else:
            keys = _keys(rec)
            unmatched[f"{keys.get('state', '?')} / {keys.get('district', '?')} / {keys.get('market', '?')}"] += 1
    if unmatched:
        log.info(
            "data.gov.in rows for markets not in reference.json (add their names to agmarknet_names if wanted): %s",
            ", ".join(f"{name} x{n}" for name, n in unmatched.most_common(40)),
        )
    n = upsert_prices(session, rows, "data_gov_in")
    drop_demo_prices_where_real(session, rows)
    return n
