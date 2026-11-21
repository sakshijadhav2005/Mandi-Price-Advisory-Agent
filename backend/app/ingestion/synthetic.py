"""Synthetic mandi price generator for local development and offline evaluation.

The real target is Agmarknet / data.gov.in data (see prices.py). Until that is
confirmed for the pilot markets (plan section 9 action item), this produces a
plausible daily series so that the agent, API, UI and evaluation harness can be
built and tested end to end. Every row is tagged source="synthetic" and the API
surfaces that tag, so synthetic numbers are never presented as real.

Shape of the series:
- an annual seasonal cycle per crop (onion peaks Sep-Nov before the kharif
  arrival and bottoms out Apr-May during the rabi harvest; tomato is more
  volatile with a summer peak; other vegetables get a rough profile by how
  perishable they are, see `_veg`),
- a shared district-level random walk with occasional shocks,
- small per-market offsets and noise,
- missing days (Sundays and random closures), and one market whose feed stops
  a few days before the end date so the staleness guardrail can be exercised.
"""

from __future__ import annotations

import logging
import math
import threading
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CropProfile:
    base: float  # Rs/qtl
    seasonal_amp: float  # fraction of base
    peak_day_of_year: int
    daily_vol: float  # std of daily log return
    shock_prob: float
    shock_size: float
    spread: float  # (max - min) / modal


PROFILES = {
    "onion": CropProfile(base=2000, seasonal_amp=0.35, peak_day_of_year=300, daily_vol=0.018, shock_prob=0.01, shock_size=0.12, spread=0.45),
    "tomato": CropProfile(base=1500, seasonal_amp=0.45, peak_day_of_year=170, daily_vol=0.035, shock_prob=0.02, shock_size=0.2, spread=0.6),
    # Potato: low daily volatility; cheapest after the Feb-Mar harvest, dearest in Oct-Nov.
    "potato": CropProfile(base=1400, seasonal_amp=0.3, peak_day_of_year=290, daily_vol=0.012, shock_prob=0.008, shock_size=0.1, spread=0.35),
}


def _veg(base: float, peak: int, kind: str) -> CropProfile:
    """Rough profile by how perishable the vegetable is (demo data only)."""
    amp, vol, prob, size, spread = {
        "leafy": (0.5, 0.05, 0.03, 0.25, 0.7),  # spinach, methi, coriander: swing day to day
        "fresh": (0.4, 0.035, 0.02, 0.18, 0.55),  # gourds, okra, brinjal, chilli, beans
        "hardy": (0.3, 0.02, 0.01, 0.12, 0.4),  # cabbage, carrot, pumpkin, roots
        "store": (0.3, 0.015, 0.008, 0.1, 0.35),  # garlic, ginger
    }[kind]
    return CropProfile(base=base, seasonal_amp=amp, peak_day_of_year=peak, daily_vol=vol, shock_prob=prob, shock_size=size, spread=spread)


# Most vegetables are dearest in the summer and monsoon (thin arrivals) and
# cheapest in the winter glut; peas and garlic peak in autumn, okra in winter.
PROFILES |= {
    "brinjal": _veg(2000, 180, "fresh"),
    "cabbage": _veg(1000, 190, "hardy"),
    "cauliflower": _veg(1800, 200, "fresh"),
    "okra": _veg(3000, 20, "fresh"),
    "green_chilli": _veg(3500, 200, "fresh"),
    "capsicum": _veg(3000, 200, "fresh"),
    "carrot": _veg(2200, 230, "hardy"),
    "cucumber": _veg(1600, 130, "fresh"),
    "bitter_gourd": _veg(3000, 30, "fresh"),
    "bottle_gourd": _veg(1500, 30, "fresh"),
    "ridge_gourd": _veg(2800, 30, "fresh"),
    "pumpkin": _veg(1200, 200, "hardy"),
    "green_peas": _veg(4500, 270, "fresh"),
    "beans": _veg(4000, 200, "fresh"),
    "cluster_beans": _veg(4000, 150, "fresh"),
    "drumstick": _veg(5000, 220, "fresh"),
    "radish": _veg(1200, 180, "hardy"),
    "beetroot": _veg(2000, 200, "hardy"),
    "spinach": _veg(1200, 170, "leafy"),
    "fenugreek": _veg(1800, 170, "leafy"),
    "coriander": _veg(2500, 170, "leafy"),
    "garlic": _veg(9000, 330, "store"),
    "ginger": _veg(5000, 150, "store"),
    "sweet_potato": _veg(2200, 250, "hardy"),
    "lemon": _veg(4000, 120, "fresh"),
}

DEFAULT_PROFILE = CropProfile(base=1800, seasonal_amp=0.3, peak_day_of_year=200, daily_vol=0.025, shock_prob=0.015, shock_size=0.15, spread=0.5)

MARKET_OFFSETS = {
    "lasalgaon": 0.03, "pimpalgaon": 0.01, "nashik": -0.02, "yeola": -0.01, "manmad": -0.03,
    "pune": 0.04, "chakan": 0.02, "manchar": 0.0, "junnar": -0.02, "baramati": -0.03,
}


def generate(
    start: date,
    end: date,
    crops: list[str] | None = None,
    markets: list[str] | None = None,
    seed: int = 7,
    stale_market: str | None = "manmad",
    stale_days: int = 5,
) -> list[dict]:
    from app.reference import load_reference

    rng = np.random.default_rng(seed)
    ref = load_reference()
    crops = crops or list(ref.crops)
    markets = markets or ref.curated_market_ids  # all-India markets get demo data on demand
    n_days = (end - start).days + 1
    rows: list[dict] = []

    for crop in crops:
        p = PROFILES.get(crop, DEFAULT_PROFILE)
        # District-level latent log price: seasonality + mean-reverting walk + shocks.
        walk = np.zeros(n_days)
        for i in range(1, n_days):
            shock = rng.normal(0, p.shock_size) if rng.random() < p.shock_prob else 0.0
            walk[i] = 0.97 * walk[i - 1] + rng.normal(0, p.daily_vol) + shock

        for market in markets:
            offset = MARKET_OFFSETS.get(market, 0.0)
            market_noise = 0.0
            for i in range(n_days):
                d = start + timedelta(days=i)
                if market == stale_market and (end - d).days < stale_days:
                    continue  # feed for this market stops before the end date
                if d.weekday() == 6 or rng.random() < 0.04:
                    continue  # Sunday or random closure / missing report
                doy = d.timetuple().tm_yday
                season = p.seasonal_amp * math.cos(2 * math.pi * (doy - p.peak_day_of_year) / 365.25)
                market_noise = 0.6 * market_noise + rng.normal(0, 0.012)
                modal = p.base * math.exp(season + walk[i] + offset + market_noise)
                half = modal * p.spread / 2 * rng.uniform(0.7, 1.1)
                rows.append(
                    {
                        "crop": crop,
                        "market": market,
                        "price_date": d,
                        "min_price": round(max(modal - half, 100), 0),
                        "modal_price": round(modal, 0),
                        "max_price": round(modal + half, 0),
                        "arrivals_tonnes": round(float(rng.uniform(50, 900)), 1),
                        "source": "synthetic",
                    }
                )
    return rows


# ---------------------------------------------------------------- demo data on demand

DEMO_DAYS = 730
_ensured: set[str] = set()
_lock = threading.Lock()


def ensure_demo_prices(session: Session, market_ids: Iterable[str], end: date) -> int:
    """Give markets outside the pilot two years of demo prices the first time they are used.

    Seeding every market in India up front would be tens of millions of rows; this
    fills one district (about 20,000 rows) when a farmer there first asks. Markets
    that already have any price row, real or synthetic, are left alone, and the
    rows are tagged "synthetic" so the app labels them as demo data. Writes in its
    own session so the caller's transaction is untouched. Returns rows written.
    """
    from app.config import get_settings
    from app.db.models import Price
    from app.reference import load_reference

    if not get_settings().demo_prices:
        return 0
    ref = load_reference()
    todo = [m for m in dict.fromkeys(market_ids) if m not in _ensured and m in ref.markets and ref.markets[m].district not in ref.curated_districts]
    if not todo:
        return 0
    with _lock:
        todo = [m for m in todo if m not in _ensured]
        if not todo:
            return 0
        with Session(bind=session.get_bind()) as own:
            have = set(own.scalars(select(Price.market).where(Price.market.in_(todo)).distinct()))
            by_district: dict[str, list[str]] = {}
            for m in todo:
                if m not in have:
                    by_district.setdefault(ref.markets[m].district, []).append(m)
            written = 0
            for district, markets in by_district.items():
                # Seeded by district, so a district always gets the same demo series.
                rows = generate(end - timedelta(days=DEMO_DAYS), end, markets=markets, seed=zlib.crc32(district.encode()), stale_market=None)
                own.bulk_insert_mappings(Price, rows)
                written += len(rows)
            if written:
                own.commit()
                log.info("demo prices: %d rows for %s", written, ", ".join(by_district))
        _ensured.update(todo)
    return written
