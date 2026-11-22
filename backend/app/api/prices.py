from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.data import last_ingestion, load_series, today
from app.config import get_settings
from app.db.models import Price
from app.db.session import get_db
from app.reference import effective_district, load_reference, locked_district

router = APIRouter(prefix="/prices", tags=["prices"])


@dataclass
class _Point:
    price_date: date
    min_price: float
    modal_price: float
    max_price: float
    source: str


def _summary(markets: list[dict]) -> dict | None:
    """Modal-price summary over the period, across the markets shown (None without data)."""
    points = [(h["date"], h["modal"], m["market"]) for m in markets for h in m["history"]]
    if not points:
        return None
    by_date = sorted(points)
    low = min(points, key=lambda p: p[1])
    high = max(points, key=lambda p: p[1])
    first_day, last_day = by_date[0][0], by_date[-1][0]
    first = [v for d, v, _ in points if d == first_day]
    last = [v for d, v, _ in points if d == last_day]
    first_avg, last_avg = sum(first) / len(first), sum(last) / len(last)
    return {
        "from": first_day,
        "to": last_day,
        "days_with_prices": len({d for d, _, _ in points}),
        "lowest": {"modal": low[1], "date": low[0], "market": low[2]},
        "highest": {"modal": high[1], "date": high[0], "market": high[2]},
        "average": round(sum(v for _, v, _ in points) / len(points), 2),
        "change_pct": round((last_avg - first_avg) / first_avg * 100, 1) if first_avg else None,
    }


@router.get("")
def prices(
    crop: str,
    market: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    as_of: date | None = None,
    district: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    db: Session = Depends(get_db),
) -> dict:
    ref = load_reference()
    if crop not in ref.crops:
        raise HTTPException(404, f"Unknown crop {crop!r}")
    if market and market not in ref.markets:
        raise HTTPException(404, f"Unknown market {market!r}")
    if district and district not in ref.districts:
        raise HTTPException(404, f"Unknown district {district!r}")
    district = effective_district(district)
    scope = ref.scope(district, lat, lon)
    if market and locked_district() and market not in scope.market_ids:
        raise HTTPException(404, f"Market {market!r} is outside {ref.districts[district].name}")
    as_of = as_of or today()
    stale_after = get_settings().stale_after_days
    series = load_series(db, crop, as_of, lookback_days=days, markets=[market] if market else scope.market_ids)
    markets = []
    for m_id in [market] if market else list(scope.market_ids):
        pts = series.get(m_id, [])
        latest = pts[-1] if pts else None
        if latest is None:
            # Nothing in the window: show the last real price before it, with its date.
            latest = db.scalars(
                select(Price)
                .where(Price.crop == crop, Price.market == m_id, Price.price_date <= as_of, Price.source != "synthetic")
                .order_by(Price.price_date.desc())
                .limit(1)
            ).first()
            if latest is not None:
                latest = _Point(latest.price_date, latest.min_price, latest.modal_price, latest.max_price, latest.source)
        age = (as_of - latest.price_date).days if latest else None
        markets.append(
            {
                "market": m_id,
                "market_name": ref.markets[m_id].name,
                "names": ref.markets[m_id].names,
                "status": "missing" if latest is None else ("fresh" if age <= stale_after else "stale"),
                "age_days": age,
                "latest": None
                if latest is None
                else {"date": latest.price_date.isoformat(), "min": latest.min_price, "modal": latest.modal_price, "max": latest.max_price},
                "source": latest.source if latest else None,
                "history": [
                    {"date": p.price_date.isoformat(), "min": p.min_price, "modal": p.modal_price, "max": p.max_price} for p in pts
                ],
            }
        )
    return {
        "summary": _summary(markets),
        "crop": crop,
        "district": scope.district,
        "unit": "Rs/quintal",
        "as_of": as_of.isoformat(),
        "stale_after_days": stale_after,
        "markets": markets,
        "last_ingestion": last_ingestion(db),
    }
