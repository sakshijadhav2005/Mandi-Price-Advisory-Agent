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
        assert {cr["id"] for cr in meta["crops"]} == {"onion", "tomato", "potato"}
        assert {d["id"] for d in meta["districts"]} == {"nashik", "pune"}
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
