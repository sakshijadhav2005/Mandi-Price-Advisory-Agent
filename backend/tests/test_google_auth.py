"""Google sign-in: ID token checks, account creation, our own JWT afterwards; nullable-phone migration."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.api import auth as auth_mod
from app.config import get_settings
from app.db.session import init_db
from app.main import app

CLIENT_ID = "test-client.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "farmer@example.com",
        "email_verified": True,
        "name": "Test Farmer",
        "iat": now,
        "exp": now + 600,
        **overrides,
    }
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "test"})


@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", CLIENT_ID)
    monkeypatch.setattr(auth_mod, "_google_signing_key", lambda _t: KEY.public_key())


def test_disabled_without_client_id(monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    with TestClient(app) as c:
        assert c.post("/auth/google", json={"credential": google_token()}).status_code == 404
        assert c.get("/meta").json()["google_client_id"] is None


def test_signup_then_login(google_on):
    with TestClient(app) as c:
        assert c.get("/meta").json()["google_client_id"] == CLIENT_ID
        first = c.post("/auth/google", json={"credential": google_token(), "language": "mr"}).json()
        assert first["created"] is True
        assert first["user"]["email"] == "farmer@example.com" and first["user"]["phone"] is None

        again = c.post("/auth/google", json={"credential": google_token(name="Renamed")}).json()
        assert again["created"] is False and again["user"]["id"] == first["user"]["id"]
        assert again["user"]["name"] == "Renamed" and again["user"]["language"] == "mr"

        headers = {"Authorization": f"Bearer {again['token']}"}
        assert c.get("/auth/me", headers=headers).json()["email"] == "farmer@example.com"
        assert c.get("/conversations", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example.com"},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        {"email_verified": False},
    ],
)
def test_rejects_bad_tokens(google_on, overrides):
    with TestClient(app) as c:
        assert c.post("/auth/google", json={"credential": google_token(**overrides)}).status_code == 401


def test_rejects_token_signed_by_another_key(google_on):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(jwt.decode(google_token(), options={"verify_signature": False}), other, algorithm="RS256")
    with TestClient(app) as c:
        assert c.post("/auth/google", json={"credential": forged}).status_code == 401


def test_migration_makes_phone_nullable(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:  # the users table as older versions created it
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, phone VARCHAR(20) NOT NULL, language VARCHAR(8), created_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_users_phone ON users (phone)"))
        conn.execute(text("INSERT INTO users (id, phone, language, created_at) VALUES (7, '+919876543210', 'hi', '2026-01-01 00:00:00')"))
    init_db(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("users")}
    assert cols["phone"]["nullable"] and "google_sub" in cols
    assert {i["name"] for i in inspect(engine).get_indexes("users")} >= {"ix_users_phone", "ix_users_google_sub"}
    with engine.begin() as conn:
        assert conn.execute(text("SELECT phone, language FROM users WHERE id = 7")).one() == ("+919876543210", "hi")
        conn.execute(text("INSERT INTO users (google_sub, language, created_at) VALUES ('g-1', 'en', '2026-11-19 00:00:00')"))
    init_db(engine)  # running again is a no-op


def test_mobile_client_id_accepted(google_on, monkeypatch):
    android = "android-client.apps.googleusercontent.com"
    with TestClient(app) as c:
        assert c.post("/auth/google", json={"credential": google_token(aud=android, sub="mob-1")}).status_code == 401
        monkeypatch.setattr(get_settings(), "google_extra_client_ids", f" {android} , ")
        r = c.post("/auth/google", json={"credential": google_token(aud=android, sub="mob-1")})
        assert r.status_code == 200, r.text
        assert c.post("/auth/google", json={"credential": google_token(aud="someone-else", sub="mob-1")}).status_code == 401
