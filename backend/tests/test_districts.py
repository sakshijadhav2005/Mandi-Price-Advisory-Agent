"""Phase 5 expansion: several districts, a third crop, schema migration."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.agent.decision import recommend
from app.agent.service import answer_query
from app.db.session import init_db
from app.main import app
from app.reference import detect_crop, detect_district, load_reference
from tests.test_decision import series_with_trend

AS_OF = date(2026, 11, 8)
GUEST = {"X-Guest-Id": "district-test-0001"}
PUNE_MARKETS = {"pune", "chakan", "manchar", "junnar", "baramati"}


def test_scope_by_district_location_and_default():
    ref = load_reference()
    assert set(ref.scope("pune").market_ids) == PUNE_MARKETS
    assert ref.scope().district == "nashik"  # default
    near_manchar = ref.scope(lat=19.0, lon=73.94)
    assert near_manchar.district == "pune" and near_manchar.market_ids[0] == "manchar"
    assert "lasalgaon" not in near_manchar.market_ids
    # explicit district wins over location, but transport is measured from the farmer
    explicit = ref.scope("nashik", lat=19.0, lon=73.94)
    assert set(explicit.market_ids) == set(ref.districts["nashik"].market_ids) and explicit.location_known


def test_detects_new_crop_and_district_names():
    assert detect_crop("मेरे पास 50 क्विंटल आलू है") == "potato"
    assert detect_crop("बटाटा कधी विकावा?") == "potato"
    assert detect_district("Pune market rate?") == "pune"
    assert detect_district("नाशिक मध्ये कांदा") == "nashik"


def test_recommendation_uses_only_district_markets():
    ref = load_reference()
    rec = recommend(ref.crops["onion"], series_with_trend(0.0, markets=list(ref.markets)), AS_OF, ref, district="pune")
    assert {m.market for m in rec.markets} == PUNE_MARKETS
    assert rec.best_market_now in PUNE_MARKETS
    assert rec.assumptions["district"] == "pune"


def test_potato_cold_storage_can_justify_holding():
    ref = load_reference()
    rec = recommend(ref.crops["potato"], series_with_trend(0.8), AS_OF, ref)
    assert rec.horizon_days == 14
    assert rec.decision == "hold"  # low storage loss: a steady rise beats cold-storage rent


def test_pune_chat_and_prices(session):
    ans = answer_query(session, "बटाटा आता विकू की थांबू?", language="mr", as_of=AS_OF, use_llm=False, district="pune")
    assert ans.recommendation["crop"] == "potato"
    assert ans.recommendation["best_market_now"] in PUNE_MARKETS
    assert all(s["market"] in PUNE_MARKETS for s in ans.sources if s["kind"] == "price")
    assert any(s["kind"] == "advisory" for s in ans.sources) or "बटाटा" in ans.text
    with TestClient(app) as c:
        data = c.get("/prices", params={"crop": "potato", "district": "pune"}).json()
        assert data["district"] == "pune" and {m["market"] for m in data["markets"]} == PUNE_MARKETS
        assert c.get("/prices", params={"crop": "onion", "district": "mumbai"}).status_code == 404
        r = c.post("/chat", json={"message": "potato sell?", "language": "en", "district": "pune"}, headers=GUEST).json()
        assert r["recommendation"]["best_market_now"] in PUNE_MARKETS


def test_question_naming_a_district_overrides_setting(session):
    ans = answer_query(session, "Should I sell onion at Pune?", language="en", as_of=AS_OF, use_llm=False, district="nashik")
    assert ans.recommendation["assumptions"]["district"] == "pune"


def test_storage_question_for_potato_uses_potato_bulletin(session):
    ans = answer_query(session, "How do I store potatoes?", language="en", as_of=AS_OF, use_llm=False)
    assert ans.text.startswith("From the crop advisory (Potato curing and storage):")


def test_migration_adds_new_nullable_column(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:  # an alerts table from before districts existed
        conn.execute(text("CREATE TABLE price_alerts (id INTEGER PRIMARY KEY, crop VARCHAR(32), direction VARCHAR(8), threshold FLOAT)"))
    init_db(engine)
    assert "district" in {c["name"] for c in inspect(engine).get_columns("price_alerts")}


def test_seasonal_signal_from_last_year():
    from datetime import timedelta

    from app.agent.data import PricePoint
    from app.agent.decision import _seasonal

    ref = load_reference()
    flat_recent = series_with_trend(0.0, days=20)
    # Last year the price rose 20% over the same 7 days (a step, so the +/-3-day averages see it exactly).
    last_year = []
    for i in range(-10, 20):
        d = AS_OF - timedelta(days=365) + timedelta(days=i)
        price = 2000.0 if i <= 3 else 2400.0
        last_year.append(PricePoint(d, price, price, price, None, "test"))
    with_season = {m: last_year + pts for m, pts in flat_recent.items()}
    assert abs(_seasonal(with_season["nashik"], AS_OF, 7) - __import__("math").log(1.2)) < 0.02
    flat = recommend(ref.crops["onion"], flat_recent, AS_OF, ref)
    seasonal = recommend(ref.crops["onion"], with_season, AS_OF, ref)
    assert flat.decision == "sell"
    assert seasonal.decision == "hold" and "seasonal_rise" in seasonal.reason_codes
    assert seasonal.markets[0].seasonal_pct == 20.0
    # No history a year back: the signal is simply absent.
    assert _seasonal(flat_recent["nashik"], AS_OF, 7) is None


def test_storage_word_in_a_sell_or_hold_question_is_a_decision_question():
    from app.translation.languages import is_advisory_question

    assert is_advisory_question("How should I store onions?")
    assert is_advisory_question("कांदा साठवण कशी करावी?")
    assert is_advisory_question("टमाटर को खराब होने से कैसे बचाएं?")
    assert not is_advisory_question("I have potatoes in cold storage. Hold or sell?")
    assert not is_advisory_question("माझा बटाटा शीतगृहात आहे, साठवू की विकू?")
    assert not is_advisory_question("Should I sell my onion now?")


def test_cold_storage_sell_or_hold_question_gets_a_decision_answer(session):
    ans = answer_query(session, "I have potatoes in cold storage. Hold or sell?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert ans.text.startswith(("Sell now", "Hold"))
