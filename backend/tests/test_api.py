from fastapi.testclient import TestClient

from app.main import app

GUEST = {"X-Guest-Id": "test-guest-0001"}


def client():
    return TestClient(app)


def test_meta_and_health():
    with client() as c:
        assert c.get("/health").json() == {"ok": True}
        meta = c.get("/meta").json()
        assert set(meta["languages"]) == {"en", "hi", "mr"}
        ids = {cr["id"] for cr in meta["crops"]}
        assert {"onion", "tomato", "potato", "brinjal", "okra", "cauliflower", "spinach"} <= ids
        assert all(cr["names"].get("hi") and cr["names"].get("mr") for cr in meta["crops"])
        ids = [d["id"] for d in meta["districts"]]
        assert ids[:2] == ["nashik", "pune"] and len(ids) > 700  # the pilot first, then all of India
        assert {"Maharashtra", "Uttar Pradesh", "Tamil Nadu", "Ladakh"} <= set(meta["states"])
        assert meta["today"] == "2026-11-08"


def test_prices_endpoint_flags_stale_market():
    with client() as c:
        data = c.get("/prices", params={"crop": "onion", "days": 14}).json()
        statuses = {m["market"]: m["status"] for m in data["markets"]}
        assert statuses["manmad"] == "stale"  # synthetic feed for Manmad stops early
        assert statuses["nashik"] == "fresh"
        assert c.get("/prices", params={"crop": "wheat"}).status_code == 404


def test_chat_flow_history_and_feedback():
    with client() as c:
        r = c.post("/chat", json={"message": "मी कांदा विकू की थांबू?", "language": "mr"}, headers=GUEST)
        assert r.status_code == 200, r.text
        ans = r.json()
        assert ans["decision"] in {"sell", "hold"}
        assert ans["language"] == "mr"
        assert ans["sources"] and ans["disclaimer"]
        conv_id = ans["conversation_id"]

        r2 = c.post("/chat", json={"message": "and tomato?", "language": "en", "conversation_id": conv_id}, headers=GUEST)
        assert r2.json()["recommendation"]["crop"] == "tomato"

        convs = c.get("/conversations", headers=GUEST).json()
        assert convs[0]["id"] == conv_id and convs[0]["messages"] == 4
        detail = c.get(f"/conversations/{conv_id}", headers=GUEST).json()
        assert detail["messages"][1]["answer"]["decision"] == ans["decision"]

        other = {"X-Guest-Id": "someone-else-0002"}
        assert c.get(f"/conversations/{conv_id}", headers=other).status_code == 404

        fb = c.post("/feedback", json={"message_id": ans["message_id"], "helpful": True}, headers=GUEST)
        assert fb.json() == {"saved": True}


def test_chat_requires_identity():
    with client() as c:
        assert c.post("/chat", json={"message": "onion?"}).status_code == 401


def test_otp_login():
    with client() as c:
        code = c.post("/auth/otp/request", json={"phone": "98765 43210"}).json()["dev_code"]
        assert c.post("/auth/otp/verify", json={"phone": "9876543210", "code": "000000" if code != "000000" else "111111"}).status_code == 400
        tok = c.post("/auth/otp/verify", json={"phone": "9876543210", "code": code, "language": "hi"}).json()["token"]
        me = c.get("/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
        assert me["phone"] == "+919876543210" and me["language"] == "hi"
        assert c.post("/auth/otp/request", json={"phone": "12345"}).status_code == 422


def test_voice_not_configured_returns_501():
    with client() as c:
        r = c.post("/voice/speak", json={"text": "hello"}, headers=GUEST)
        assert r.status_code == 501


def test_websocket_chat():
    with client() as c, c.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "tomato sell?", "language": "hi", "auth": {"x-guest-id": "ws-guest-0003"}})
        assert ws.receive_json()["type"] == "status"
        msg = ws.receive_json()
        assert msg["type"] == "answer" and msg["data"]["recommendation"]["crop"] == "tomato"


def test_prices_last_real_price_and_summary(session):
    from datetime import date

    from sqlalchemy import delete

    from app.db.models import Price

    day = date(2029, 12, 1)
    session.add(Price(crop="onion", market="pune", price_date=day, min_price=4200, modal_price=4700, max_price=5200, source="agmarknet_csv"))
    session.add(Price(crop="onion", market="pune", price_date=date(2029, 12, 3), min_price=4400, modal_price=5170, max_price=5600, source="agmarknet_csv"))
    session.commit()
    try:
        with client() as c:
            # A week with no prices at all: the last real price is shown with its own date.
            data = c.get("/prices", params={"crop": "onion", "days": 7, "district": "pune", "as_of": "2030-01-01"}).json()
            pune = next(m for m in data["markets"] if m["market"] == "pune")
            assert pune["latest"]["date"] == "2029-12-03" and pune["status"] == "stale" and pune["history"] == []
            assert data["summary"] is None
            # A window with the records: history, and a summary over it.
            data = c.get("/prices", params={"crop": "onion", "days": 10, "district": "pune", "as_of": "2029-12-05"}).json()
            s = data["summary"]
            assert s["lowest"]["modal"] == 4700 and s["highest"]["modal"] == 5170 and s["highest"]["date"] == "2029-12-03"
            assert s["days_with_prices"] == 2 and s["change_pct"] == 10.0 and s["average"] == 4935
    finally:
        session.execute(delete(Price).where(Price.source == "agmarknet_csv", Price.price_date >= day))
        session.commit()


def test_prices_real_market_shows_only_real_others_keep_demo(session):
    from datetime import date

    from sqlalchemy import delete

    from app.db.models import Price

    with client() as c:
        before = c.get("/prices", params={"crop": "onion", "days": 7, "district": "pune", "as_of": "2026-11-08"}).json()
        assert any(m["source"] == "synthetic" for m in before["markets"])  # only demo prices so far
    day = date(2026, 11, 6)
    session.add(Price(crop="onion", market="pune", price_date=day, min_price=4200, modal_price=4700, max_price=5200, source="agmarknet_csv"))
    session.commit()
    try:
        with client() as c:
            data = c.get("/prices", params={"crop": "onion", "days": 7, "district": "pune", "as_of": "2026-11-08"}).json()
            pune = next(m for m in data["markets"] if m["market"] == "pune")
            assert pune["source"] == "agmarknet_csv"
            assert pune["history"] == [{"date": "2026-11-06", "min": 4200, "modal": 4700, "max": 5200}]
            others = [m for m in data["markets"] if m["market"] != "pune"]
            # Markets without a real price still show their (demo) prices instead of nothing.
            assert others and all(m["source"] == "synthetic" and m["history"] and m["latest"] for m in others)
    finally:
        session.execute(delete(Price).where(Price.source == "agmarknet_csv", Price.price_date == day))
        session.commit()
