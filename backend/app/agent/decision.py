"""Deterministic sell / hold / insufficient-data decision.

The LLM never produces the recommendation or the numbers itself: it calls the
`compute_recommendation` tool, which runs this module. That keeps the decision
reproducible, testable against baselines, and free of invented figures.

Model, per quintal of produce the farmer has today:

    net_now(m)  = modal_latest(m) * (1 - fees) - transport(m)
    net_hold(m) = modal_latest(m) * exp(damping * slope(m) * h) * (1 - loss * h)
                  * (1 - fees) - storage * h - transport(m)

`slope` is a least-squares trend of log modal price over the last 14 days, damped
because short-run trends in mandi prices only partly persist. Holding is
recommended only when the best hold value beats the best sell-now value by a
margin that is large relative to the price volatility over the horizon; small
expected gains default to "sell", which is the lower-risk choice for a small
farmer. Markets whose latest report is older than `stale_after_days` are
excluded, and if no market is fresh the answer is "insufficient_data".
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np

from app.agent.data import PricePoint, Series
from app.reference import Crop, Reference, haversine_km

TREND_WINDOW_DAYS = 14
DAMPING = 0.5
MIN_GAIN_PCT = 2.0
MIN_Z = 0.5
# Seasonal signal: last year's log price change over the same horizon, half-weighted
# because a single past year is a noisy guide. Needs about a year of history.
SEASONAL_WEIGHT = 0.5
SEASON_WINDOW_DAYS = 3
RECENT_DAYS = 30


@dataclass
class MarketAssessment:
    market: str
    latest_date: str | None
    age_days: int | None
    points: int
    status: str  # fresh | stale | missing | sparse
    modal_latest: float | None = None
    min_latest: float | None = None
    max_latest: float | None = None
    avg_7d: float | None = None
    distance_km: float | None = None
    transport_per_qtl: float | None = None
    net_now_per_qtl: float | None = None
    trend_pct_per_day: float | None = None
    seasonal_pct: float | None = None  # last year's change over the same horizon
    expected_price_after_hold: float | None = None
    net_hold_per_qtl: float | None = None
    source: str | None = None


@dataclass
class Recommendation:
    crop: str
    as_of: str
    decision: str  # sell | hold | insufficient_data
    confidence: str  # high | medium | low
    horizon_days: int
    quantity_qtl: float | None
    best_market_now: str | None = None
    best_net_now_per_qtl: float | None = None
    best_market_hold: str | None = None
    best_net_hold_per_qtl: float | None = None
    expected_gain_per_qtl: float | None = None
    expected_gain_pct: float | None = None
    uncertainty_per_qtl: float | None = None
    total_value_now: float | None = None
    reason_codes: list[str] = field(default_factory=list)
    markets: list[MarketAssessment] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def transport_cost_per_qtl(ref: Reference, market_id: str, lat: float, lon: float) -> tuple[float, float]:
    m = ref.markets[market_id]
    t = ref.transport
    km = max(haversine_km(lat, lon, m.lat, m.lon) * t["road_factor"], t["min_distance_km"])
    return round(km, 1), round(t["fixed_per_qtl"] + t["rate_per_qtl_km"] * km, 1)


def _trend(points: list[PricePoint], as_of: date) -> tuple[float, float]:
    """(slope of log price per day, daily log volatility) over the trend window."""
    window = [p for p in points if (as_of - p.price_date).days < TREND_WINDOW_DAYS]
    if len(window) < 3:
        return 0.0, 0.03
    x = np.array([(p.price_date - as_of).days for p in window], dtype=float)
    y = np.log([p.modal_price for p in window])
    slope, intercept = np.polyfit(x, y, 1)
    # Volatility from day-gap-normalised log returns.
    gaps = np.diff(x)
    rets = np.diff(y) / np.sqrt(np.where(gaps <= 0, 1, gaps))
    vol = float(np.std(rets)) if len(rets) >= 2 else 0.03
    return float(slope), max(vol, 0.005)


def _seasonal(points: list[PricePoint], as_of: date, h: int) -> float | None:
    """Log change of the modal price from (as_of - 1 year) to (as_of - 1 year + h), or None."""

    def avg_near(day: date) -> float | None:
        vals = [p.modal_price for p in points if abs((p.price_date - day).days) <= SEASON_WINDOW_DAYS]
        return sum(vals) / len(vals) if len(vals) >= 2 else None

    start = as_of - timedelta(days=365)
    a, b = avg_near(start), avg_near(start + timedelta(days=h))
    if a is None or b is None:
        return None
    return math.log(b / a)


def recommend(
    crop: Crop,
    series: Series,
    as_of: date,
    ref: Reference,
    farmer_lat: float | None = None,
    farmer_lon: float | None = None,
    quantity_qtl: float | None = None,
    horizon_days: int | None = None,
    stale_after_days: int = 3,
    min_points: int = 5,
    district: str | None = None,
) -> Recommendation:
    scope = ref.scope(district, farmer_lat, farmer_lon)
    lat, lon = scope.lat, scope.lon
    h = horizon_days or crop.default_horizon_days
    reasons: list[str] = []
    if h > crop.max_hold_days:
        h = crop.max_hold_days
        reasons.append("horizon_capped_perishable")
    fees = ref.market_fees_pct / 100
    loss = crop.weight_loss_pct_per_day / 100

    rec = Recommendation(
        crop=crop.id,
        as_of=as_of.isoformat(),
        decision="insufficient_data",
        confidence="low",
        horizon_days=h,
        quantity_qtl=quantity_qtl,
        assumptions={
            "market_fees_pct": ref.market_fees_pct,
            "storage_cost_per_qtl_day": crop.storage_cost_per_qtl_day,
            "weight_loss_pct_per_day": crop.weight_loss_pct_per_day,
            "transport_rate_per_qtl_km": ref.transport["rate_per_qtl_km"],
            "transport_fixed_per_qtl": ref.transport["fixed_per_qtl"],
            "trend_damping": DAMPING,
            "seasonal_weight": SEASONAL_WEIGHT,
            "stale_after_days": stale_after_days,
            "farmer_location": {"lat": lat, "lon": lon, "default": not scope.location_known},
            "district": scope.district,
        },
    )

    fresh: list[tuple[MarketAssessment, float]] = []  # (assessment, daily vol)
    for market_id in scope.market_ids:
        history = series.get(market_id, [])
        pts = [p for p in history if (as_of - p.price_date).days < RECENT_DAYS]
        if not pts:
            rec.markets.append(MarketAssessment(market_id, None, None, 0, "missing"))
            continue
        latest = pts[-1]
        age = (as_of - latest.price_date).days
        recent7 = [p.modal_price for p in pts if (as_of - p.price_date).days < 7]
        km, transport = transport_cost_per_qtl(ref, market_id, lat, lon)
        a = MarketAssessment(
            market=market_id,
            latest_date=latest.price_date.isoformat(),
            age_days=age,
            points=len(pts),
            status="fresh",
            modal_latest=latest.modal_price,
            min_latest=latest.min_price,
            max_latest=latest.max_price,
            avg_7d=round(sum(recent7) / len(recent7), 1) if recent7 else None,
            distance_km=km,
            transport_per_qtl=transport,
            source=latest.source,
        )
        if age > stale_after_days:
            a.status = "stale"
        elif len(pts) < min_points:
            a.status = "sparse"
        rec.markets.append(a)
        if a.status != "fresh":
            continue
        slope, vol = _trend(pts, as_of)
        a.trend_pct_per_day = round(100 * (math.exp(slope) - 1), 2)
        a.net_now_per_qtl = round(latest.modal_price * (1 - fees) - transport, 1)
        seasonal = _seasonal(history, as_of, h)
        drift = DAMPING * slope * h
        if seasonal is not None:
            a.seasonal_pct = round(100 * (math.exp(seasonal) - 1), 1)
            drift += SEASONAL_WEIGHT * seasonal
        expected = latest.modal_price * math.exp(drift)
        a.expected_price_after_hold = round(expected, 1)
        a.net_hold_per_qtl = round(
            expected * (1 - loss * h) * (1 - fees) - crop.storage_cost_per_qtl_day * h - transport, 1
        )
        fresh.append((a, vol))

    if any(m.status == "stale" for m in rec.markets):
        reasons.append("some_markets_stale")
    if not fresh:
        reasons.append("no_fresh_prices")
        rec.reason_codes = reasons
        return rec

    best_now, _ = max(fresh, key=lambda t: t[0].net_now_per_qtl)
    best_hold, hold_vol = max(fresh, key=lambda t: t[0].net_hold_per_qtl)
    gain = best_hold.net_hold_per_qtl - best_now.net_now_per_qtl
    sigma = max(best_hold.modal_latest * hold_vol * math.sqrt(h), 1.0)
    z = gain / sigma
    gain_pct = 100 * gain / best_now.net_now_per_qtl if best_now.net_now_per_qtl > 0 else 0.0

    rec.best_market_now = best_now.market
    rec.best_net_now_per_qtl = best_now.net_now_per_qtl
    rec.best_market_hold = best_hold.market
    rec.best_net_hold_per_qtl = best_hold.net_hold_per_qtl
    rec.expected_gain_per_qtl = round(gain, 1)
    rec.expected_gain_pct = round(gain_pct, 1)
    rec.uncertainty_per_qtl = round(sigma, 1)
    if quantity_qtl:
        rec.total_value_now = round(best_now.net_now_per_qtl * quantity_qtl, 0)

    if gain_pct > MIN_GAIN_PCT and z > MIN_Z:
        rec.decision = "hold"
        reasons.append("rising_trend_beats_costs")
        if (best_hold.seasonal_pct or 0) > 0:
            reasons.append("seasonal_rise")
    else:
        rec.decision = "sell"
        if gain <= 0:
            reasons.append("holding_costs_exceed_expected_rise" if (best_hold.trend_pct_per_day or 0) > 0 else "prices_flat_or_falling")
        else:
            reasons.append("expected_gain_too_small_for_risk")
        if crop.max_hold_days <= 5:
            reasons.append("perishable_crop")

    # Confidence: strength of the signal, discounted by data quality.
    strength = min(abs(z) / 1.5, 1.0)
    fresh_share = len(fresh) / len(scope.market_ids)
    recency = 1.0 if (best_now.age_days or 0) <= 1 else 0.8
    score = strength * (0.5 + 0.5 * fresh_share) * recency
    rec.confidence = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
    if best_hold.market != best_now.market and rec.decision == "hold":
        reasons.append("different_market_after_hold")
    rec.reason_codes = reasons
    return rec


# --- Baselines (plan section 10) -------------------------------------------------

def baseline_always(decision: str):
    return lambda *_args, **_kw: decision


def baseline_above_7d_avg(series: Series, as_of: date) -> str:
    """Sell if today's (latest) price is above its 7-day average, averaged over markets."""
    votes = []
    for pts in series.values():
        if not pts or (as_of - pts[-1].price_date).days > 3:
            continue
        recent = [p.modal_price for p in pts if (as_of - p.price_date).days < 7]
        if recent:
            votes.append(pts[-1].modal_price >= sum(recent) / len(recent))
    if not votes:
        return "sell"
    return "sell" if sum(votes) >= len(votes) / 2 else "hold"
