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
    series: Series = defaultdict(list)
    for p in session.scalars(q.order_by(Price.price_date)):
        series[p.market].append(PricePoint(p.price_date, p.min_price, p.modal_price, p.max_price, p.arrivals_tonnes, p.source))
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
