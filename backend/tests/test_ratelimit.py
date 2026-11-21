"""Brute-force limits on password login, OTP requests and signups."""

import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _email() -> str:
    return f"limit-{uuid.uuid4().hex[:8]}@example.com"


def test_account_locks_after_repeated_wrong_passwords():
    email = _email()
    with TestClient(app) as c:
        assert c.post("/auth/signup", json={"name": "A", "email": email, "password": "secret1"}).status_code == 201
        for _ in range(get_settings().auth_max_failures):
            assert c.post("/auth/login", json={"identifier": email, "password": "wrong"}).status_code == 401
        locked = c.post("/auth/login", json={"identifier": email, "password": "secret1"})
        assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0  # even the right password waits
        # Another account is not affected by this account's lock.
        other = _email()
        c.post("/auth/signup", json={"name": "B", "email": other, "password": "secret1"})
        assert c.post("/auth/login", json={"identifier": other, "password": "secret1"}).status_code == 200


def test_success_clears_failures():
    email = _email()
    with TestClient(app) as c:
        c.post("/auth/signup", json={"name": "A", "email": email, "password": "secret1"})
        for _ in range(get_settings().auth_max_failures - 1):
            c.post("/auth/login", json={"identifier": email, "password": "wrong"})
        assert c.post("/auth/login", json={"identifier": email, "password": "secret1"}).status_code == 200
        for _ in range(get_settings().auth_max_failures - 1):
            assert c.post("/auth/login", json={"identifier": email, "password": "wrong"}).status_code == 401


def test_ip_limit_across_accounts(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_ip_max_attempts", 3)
    with TestClient(app) as c:
        for _ in range(3):
            assert c.post("/auth/login", json={"identifier": _email(), "password": "x"}).status_code == 401
        assert c.post("/auth/login", json={"identifier": _email(), "password": "x"}).status_code == 429


def test_otp_requests_per_phone_are_limited():
    with TestClient(app) as c:
        for _ in range(get_settings().otp_max_requests):
            assert c.post("/auth/otp/request", json={"phone": "9876500011"}).status_code == 200
        assert c.post("/auth/otp/request", json={"phone": "9876500011"}).status_code == 429
        assert c.post("/auth/otp/request", json={"phone": "9876500012"}).status_code == 200


def test_signups_per_ip_are_limited(monkeypatch):
    monkeypatch.setattr(get_settings(), "signup_max_per_ip", 2)
    with TestClient(app) as c:
        for _ in range(2):
            assert c.post("/auth/signup", json={"name": "A", "email": _email(), "password": "secret1"}).status_code == 201
        assert c.post("/auth/signup", json={"name": "A", "email": _email(), "password": "secret1"}).status_code == 429
