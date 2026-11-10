"""Build the labelled historical decision-point test set (plan section 10).

Each decision point is (crop, as_of date). Its label is what would actually have
been best, using prices the agent could NOT see at decision time:

    sell  if the best net price available on as_of (after transport and fees)
          >= the best net price realised `h` days later (after storage cost,
          storage weight loss, transport and fees),
    hold  otherwise.

A share of points are "outage" cases: the feed is cut `outage_days` before as_of
for every market. Their expected answer is insufficient_data.

Usage (from the repo root):
    python evaluation/scripts/build_test_set.py --per-crop 100 --outages 20
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.data import PricePoint, Series  # noqa: E402
from app.agent.decision import transport_cost_per_qtl  # noqa: E402
from app.db.models import Price  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.reference import load_reference  # noqa: E402
from sqlalchemy import select  # noqa: E402

OUT = ROOT / "evaluation" / "test_sets" / "decision_points.jsonl"


def load_full_series(crop: str) -> Series:
    series: Series = {}
    with session_scope() as s:
        for p in s.scalars(select(Price).where(Price.crop == crop).order_by(Price.price_date)):
            series.setdefault(p.market, []).append(
                PricePoint(p.price_date, p.min_price, p.modal_price, p.max_price, p.arrivals_tonnes, p.source)
            )
    return series


def price_on(points: list[PricePoint], d: date, tolerance: int) -> float | None:
    """Modal price reported on d, or the nearest report within +/- tolerance days."""
    best = None
    for p in points:
        gap = abs((p.price_date - d).days)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, p.modal_price)
    return best[1] if best else None


def district_series(series: Series, district: str) -> Series:
    ids = set(load_reference().districts[district].market_ids)
    return {m: pts for m, pts in series.items() if m in ids}


def realised_outcome(crop_id: str, series: Series, as_of: date, h: int, district: str) -> dict | None:
    ref = load_reference()
    crop = ref.crops[crop_id]
    centre = ref.districts[district].centre
    lat, lon = centre["lat"], centre["lon"]
    fees, loss = ref.market_fees_pct / 100, crop.weight_loss_pct_per_day / 100
    now_vals, hold_vals = {}, {}
    for m, pts in district_series(series, district).items():
        _, transport = transport_cost_per_qtl(ref, m, lat, lon)
        past = [p for p in pts if p.price_date <= as_of]
        if past and (as_of - past[-1].price_date).days <= 3:
            now_vals[m] = past[-1].modal_price * (1 - fees) - transport
        future = price_on(pts, as_of + timedelta(days=h), tolerance=1)
        if future is not None:
            hold_vals[m] = future * (1 - loss * h) * (1 - fees) - crop.storage_cost_per_qtl_day * h - transport
    if not now_vals or not hold_vals:
        return None
    best_now, best_hold = max(now_vals.values()), max(hold_vals.values())
    return {
        "label": "hold" if best_hold > best_now else "sell",
        "realised_net_now": round(best_now, 1),
        "realised_net_hold": round(best_hold, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-crop", type=int, default=100)
    ap.add_argument("--outages", type=int, default=20, help="outage cases per crop")
    ap.add_argument("--outage-days", type=int, default=5)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    ref = load_reference()
    rows = []
    for district, crop_id in ((d, c) for d in ref.districts for c in ref.crops):
        crop = ref.crops[crop_id]
        series = district_series(load_full_series(crop_id), district)
        all_dates = sorted({p.price_date for pts in series.values() for p in pts})
        if not all_dates:
            raise SystemExit("No prices in the database. Run `python backend/manage.py seed-synthetic` first.")
        h = crop.default_horizon_days
        lo, hi = all_dates[0] + timedelta(days=30), all_dates[-1] - timedelta(days=h + 1)
        candidates = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        rng.shuffle(candidates)
        n = 0
        for d in candidates:
            if n >= args.per_crop:
                break
            outcome = realised_outcome(crop_id, series, d, h, district)
            if outcome:
                rows.append({"id": f"{district}-{crop_id}-{d.isoformat()}", "district": district, "crop": crop_id, "as_of": d.isoformat(), "horizon_days": h, "case": "normal", **outcome})
                n += 1
        for d in candidates[n : n + args.outages]:
            rows.append(
                {
                    "id": f"{district}-{crop_id}-{d.isoformat()}-outage",
                    "district": district,
                    "crop": crop_id,
                    "as_of": d.isoformat(),
                    "horizon_days": h,
                    "case": "outage",
                    "outage_days": args.outage_days,
                    "label": "insufficient_data",
                }
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    normal = [r for r in rows if r["case"] == "normal"]
    holds = sum(r["label"] == "hold" for r in normal)
    print(f"wrote {len(rows)} decision points to {OUT} ({len(normal)} normal: {holds} hold / {len(normal) - holds} sell; {len(rows) - len(normal)} outage)")


if __name__ == "__main__":
    main()
