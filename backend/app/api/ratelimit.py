"""Limits on login attempts, OTP requests and signups (brute force and SMS abuse).

A sliding window per key: failed password logins per account and per IP address, OTP
requests per phone number and per IP, signups per IP. Over the limit the API answers
429 with a Retry-After header. A successful login clears the account's failures.

The counters live in memory, so each server process counts on its own (fine for one
process; behind several workers the effective limit is per worker). The client IP is
`request.client.host`; set up the proxy to pass the real address if one is in front.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import get_settings

_lock = threading.Lock()
_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request | None) -> str:
    return (request.client.host if request and request.client else "") or "unknown"


def _prune(q: deque[float], now: float, window: float) -> None:
    while q and q[0] <= now - window:
        q.popleft()


def check(kind: str, key: str, limit: int, window_s: float | None = None) -> None:
    """Raise 429 when `key` already has `limit` events of `kind` in the window."""
    window = window_s if window_s is not None else get_settings().auth_window_minutes * 60
    now = time.monotonic()
    with _lock:
        q = _events[(kind, key)]
        _prune(q, now, window)
        if len(q) >= limit:
            wait = max(1, math.ceil(q[0] + window - now))
            raise HTTPException(429, f"Too many attempts. Try again in {math.ceil(wait / 60)} minutes.", headers={"Retry-After": str(wait)})


def hit(kind: str, key: str) -> None:
    with _lock:
        _events[(kind, key)].append(time.monotonic())


def clear(kind: str, key: str) -> None:
    with _lock:
        _events.pop((kind, key), None)


def reset() -> None:
    """Forget every counter (tests)."""
    with _lock:
        _events.clear()
