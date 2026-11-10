from datetime import date, timedelta

from app.agent.data import PricePoint
from app.agent.decision import baseline_above_7d_avg, recommend
from app.reference import load_reference

AS_OF = date(2026, 11, 8)


def series_with_trend(daily_pct: float, days: int = 20, base: float = 2000.0, last_age: int = 0, markets=None):
    ref = load_reference()
    out = {}
    for m in markets or ref.markets:
        pts = []
        for i in range(days, last_age - 1, -1):
            price = base * (1 + daily_pct / 100) ** (days - i)
            pts.append(PricePoint(AS_OF - timedelta(days=i), price * 0.8, price, price * 1.2, None, "test"))
        out[m] = pts
    return out


def test_strong_rise_in_storable_crop_recommends_hold():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], series_with_trend(1.5), AS_OF, ref)
    assert rec.decision == "hold"
    assert rec.expected_gain_per_qtl > 0
    assert "rising_trend_beats_costs" in rec.reason_codes


def test_falling_prices_recommend_sell_with_high_confidence():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], series_with_trend(-1.5), AS_OF, ref)
    assert rec.decision == "sell"
    assert rec.confidence == "high"


def test_perishable_crop_sells_even_on_mild_rise():
    ref = load_reference()
    rec = recommend(ref.crops["tomato"], series_with_trend(0.8), AS_OF, ref)
    assert rec.decision == "sell"
    assert "perishable_crop" in rec.reason_codes


def test_horizon_is_capped_for_perishables():
    ref = load_reference()
    rec = recommend(ref.crops["tomato"], series_with_trend(0.0), AS_OF, ref, horizon_days=10)
    assert rec.horizon_days == ref.crops["tomato"].max_hold_days
    assert "horizon_capped_perishable" in rec.reason_codes


def test_stale_data_gives_insufficient_data():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], series_with_trend(1.0, last_age=5), AS_OF, ref, stale_after_days=3)
    assert rec.decision == "insufficient_data"
    assert "no_fresh_prices" in rec.reason_codes
    assert all(m.status == "stale" for m in rec.markets)


def test_no_data_gives_insufficient_data():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], {}, AS_OF, ref)
    assert rec.decision == "insufficient_data"


def test_stale_markets_are_excluded_but_others_used():
    ref = load_reference()
    fresh = series_with_trend(0.0, markets=["nashik", "lasalgaon"])
    stale = series_with_trend(0.0, last_age=6, markets=["yeola"])
    rec = recommend(ref.crops["onion"], {**fresh, **stale}, AS_OF, ref)
    assert rec.decision == "sell"
    assert "some_markets_stale" in rec.reason_codes
    statuses = {m.market: m.status for m in rec.markets}
    assert statuses["yeola"] == "stale" and statuses["manmad"] == "missing"


def test_transport_cost_can_change_best_market():
    ref = load_reference()
    series = series_with_trend(0.0, markets=["nashik", "manmad"])
    # Manmad slightly higher price but much farther from a farmer in Nashik city.
    series["manmad"] = [PricePoint(p.price_date, p.min_price, p.modal_price + 40, p.max_price, None, "test") for p in series["manmad"]]
    rec = recommend(ref.crops["onion"], series, AS_OF, ref, farmer_lat=20.0059, farmer_lon=73.79)
    assert rec.best_market_now == "nashik"


def test_quantity_total():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], series_with_trend(0.0), AS_OF, ref, quantity_qtl=10)
    assert rec.total_value_now == round(rec.best_net_now_per_qtl * 10, 0)


def test_baseline_rule():
    rising = series_with_trend(1.0)
    falling = series_with_trend(-1.0)
    assert baseline_above_7d_avg(rising, AS_OF) == "sell"
    assert baseline_above_7d_avg(falling, AS_OF) == "hold"
