"""Synthetic mandi price generator for local development and offline evaluation.

The real target is Agmarknet / data.gov.in data (see prices.py). Until that is
confirmed for the pilot markets (plan section 9 action item), this produces a
plausible daily series so that the agent, API, UI and evaluation harness can be
built and tested end to end. Every row is tagged source="synthetic" and the API
surfaces that tag, so synthetic numbers are never presented as real.

Shape of the series:
- an annual seasonal cycle per crop (onion peaks Sep-Nov before the kharif
  arrival and bottoms out Apr-May during the rabi harvest; tomato is more
  volatile with a summer peak),
- a shared district-level random walk with occasional shocks,
- small per-market offsets and noise,
- missing days (Sundays and random closures), and one market whose feed stops
  a few days before the end date so the staleness guardrail can be exercised.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np


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
    markets = markets or list(ref.markets)
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
