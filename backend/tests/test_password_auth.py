"""Email + password signup and login."""

import uuid

from fastapi.testclient import TestClient

from app.api.auth import check_password, hash_password
from app.main import app


def _email() -> str:
    return f"farmer-{uuid.uuid4().hex[:8]}@Example.com"


def test_hash_round_trip():
    h = hash_password("kanda123")
    assert h.startswith("scrypt$") and "kanda123" not in h
    assert check_password("kanda123", h)
    assert not check_password("wrong", h)
    assert not check_password("kanda123", None)
    assert not check_password("kanda123", "garbage")


def test_signup_then_login_by_email_and_phone():
    email = _email()
    phone = f"98{uuid.uuid4().int % 10**8:08d}"
    with TestClient(app) as c:
        r = c.post("/auth/signup", json={"name": " Ramesh ", "email": email, "phone": phone, "password": "secret1", "language": "mr"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token"] and body["user"]["email"] == email.lower() and body["user"]["name"] == "Ramesh"
        assert c.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"}).json()["id"] == body["user"]["id"]

        assert c.post("/auth/login", json={"identifier": email.upper(), "password": "secret1"}).status_code == 200
        assert c.post("/auth/login", json={"identifier": phone, "password": "secret1"}).status_code == 200
        assert c.post("/auth/login", json={"identifier": email, "password": "nope"}).status_code == 401
        assert c.post("/auth/login", json={"identifier": "nobody@example.com", "password": "secret1"}).status_code == 401

        # duplicates are refused
        assert c.post("/auth/signup", json={"name": "X", "email": email, "password": "secret1"}).status_code == 409
        assert c.post("/auth/signup", json={"name": "X", "email": _email(), "phone": phone, "password": "secret1"}).status_code == 409


def test_signup_validation():
    with TestClient(app) as c:
        assert c.post("/auth/signup", json={"name": "A", "email": "not-an-email", "password": "secret1"}).status_code == 422
        assert c.post("/auth/signup", json={"name": "A", "email": _email(), "password": "123"}).status_code == 422
        assert c.post("/auth/signup", json={"name": "A", "email": _email(), "phone": "12345", "password": "secret1"}).status_code == 422
        # phone is optional
        assert c.post("/auth/signup", json={"name": "A", "email": _email(), "phone": "", "password": "secret1"}).status_code == 201
