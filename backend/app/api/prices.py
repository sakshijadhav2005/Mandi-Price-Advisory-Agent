from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agent.data import last_ingestion, load_series, today
from app.config import get_settings
from app.db.session import get_db
from app.reference import load_reference

router = APIRouter(prefix="/prices", tags=["prices"])


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
    scope = ref.scope(district, lat, lon)
    as_of = as_of or today()
    stale_after = get_settings().stale_after_days
    series = load_series(db, crop, as_of, lookback_days=days, market=market)
    markets = []
    for m_id in [market] if market else list(scope.market_ids):
        pts = series.get(m_id, [])
        latest = pts[-1] if pts else None
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
        "crop": crop,
        "district": scope.district,
        "unit": "Rs/quintal",
        "as_of": as_of.isoformat(),
        "stale_after_days": stale_after,
        "markets": markets,
        "last_ingestion": last_ingestion(db),
    }
