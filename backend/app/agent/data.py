"""Price data access. Every query takes `as_of` so evaluation never looks ahead."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import IngestionRun, Price


@dataclass(frozen=True)
class PricePoint:
    price_date: date
    min_price: float
    modal_price: float
    max_price: float
    arrivals_tonnes: float | None
    source: str


Series = dict[str, list[PricePoint]]  # market -> points sorted by date ascending


SYNTHETIC_SOURCE = "synthetic"


def today() -> date:
    override = get_settings().as_of_override
    return date.fromisoformat(override) if override else date.today()


def load_series(session: Session, crop: str, as_of: date, lookback_days: int = 30, market: str | None = None) -> Series:
    q = select(Price).where(
        Price.crop == crop,
        Price.price_date <= as_of,
        Price.price_date > as_of - timedelta(days=lookback_days),
    )
    if market:
        q = q.where(Price.market == market)
    # One observation per market and day. When a real source and the synthetic
    # generator both have a row for the same day, the real one wins, so a
    # database that still holds synthetic history never mixes the two.
    best: dict[tuple[str, date], PricePoint] = {}
    for p in session.scalars(q.order_by(Price.price_date)):
        point = PricePoint(p.price_date, p.min_price, p.modal_price, p.max_price, p.arrivals_tonnes, p.source)
        key = (p.market, p.price_date)
        current = best.get(key)
        if current is None or (current.source == SYNTHETIC_SOURCE and p.source != SYNTHETIC_SOURCE):
            best[key] = point
    series: Series = defaultdict(list)
    for (m, _day), point in sorted(best.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        series[m].append(point)
    return dict(series)


def slice_series(full: Series, as_of: date, lookback_days: int = 30) -> Series:
    """In-memory equivalent of load_series, used by the evaluation runner."""
    lo = as_of - timedelta(days=lookback_days)
    out = {}
    for m, pts in full.items():
        sl = [p for p in pts if lo < p.price_date <= as_of]
        if sl:
            out[m] = sl
    return out


def last_ingestion(session: Session) -> dict | None:
    run = session.scalars(select(IngestionRun).where(IngestionRun.job == "prices").order_by(desc(IngestionRun.id)).limit(1)).first()
    if not run:
        return None
    return {"source": run.source, "status": run.status, "rows": run.rows, "at": run.started_at.isoformat(), "message": run.message}
