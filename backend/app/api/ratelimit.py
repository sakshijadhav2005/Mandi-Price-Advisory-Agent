"""Limits on login attempts, OTP requests and signups (brute force and SMS abuse).

A sliding window per key: failed password logins per account and per IP address, OTP
requests per phone number and per IP, signups per IP. Over the limit the API answers
429 with a Retry-After header. A successful login clears the account's failures.

Two backends (RATE_LIMIT_BACKEND):
- "memory" (default): counters in this process; fastest, right for a single server process.
- "database": counters in the auth_events table, shared by every process and server that
  uses the same database (several workers, or several machines behind a load balancer).

The client IP is `request.client.host`; set up the proxy to pass the real address if one
is in front of the app.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select

from app.config import get_settings

_lock = threading.Lock()
_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request | None) -> str:
    return (request.client.host if request and request.client else "") or "unknown"


def _window_s(window_s: float | None) -> float:
    return window_s if window_s is not None else get_settings().auth_window_minutes * 60


def _shared() -> bool:
    return get_settings().rate_limit_backend == "database"


def _too_many(wait_s: float) -> HTTPException:
    wait = max(1, math.ceil(wait_s))
    return HTTPException(429, f"Too many attempts. Try again in {math.ceil(wait / 60)} minutes.", headers={"Retry-After": str(wait)})


def check(kind: str, key: str, limit: int, window_s: float | None = None) -> None:
    """Raise 429 when `key` already has `limit` events of `kind` in the window."""
    window = _window_s(window_s)
    if _shared():
        from app.db.models import AuthEvent
        from app.db.session import session_scope

        since = datetime.now(timezone.utc) - timedelta(seconds=window)
        with session_scope() as s:
            count, oldest = s.execute(
                select(func.count(), func.min(AuthEvent.at)).where(AuthEvent.kind == kind, AuthEvent.key == key, AuthEvent.at > since)
            ).one()
        if count >= limit:
            oldest = oldest.replace(tzinfo=oldest.tzinfo or timezone.utc)
            raise _too_many((oldest + timedelta(seconds=window) - datetime.now(timezone.utc)).total_seconds())
        return
    now = time.monotonic()
    with _lock:
        q = _events[(kind, key)]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            raise _too_many(q[0] + window - now)


def hit(kind: str, key: str) -> None:
    if _shared():
        from app.db.models import AuthEvent
        from app.db.session import session_scope

        with session_scope() as s:
            s.add(AuthEvent(kind=kind, key=key[:254], at=datetime.now(timezone.utc)))
            s.commit()
        return
    with _lock:
        _events[(kind, key)].append(time.monotonic())


def clear(kind: str, key: str) -> None:
    if _shared():
        from app.db.models import AuthEvent
        from app.db.session import session_scope

        with session_scope() as s:
            s.execute(delete(AuthEvent).where(AuthEvent.kind == kind, AuthEvent.key == key))
            s.commit()
        return
    with _lock:
        _events.pop((kind, key), None)


def purge_old(session) -> int:
    """Delete shared counter rows older than the window (hourly, with the history cleanup)."""
    from app.db.models import AuthEvent

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_window_s(None))
    n = session.execute(delete(AuthEvent).where(AuthEvent.at < cutoff)).rowcount or 0
    session.commit()
    return n


def reset() -> None:
    """Forget every counter (tests)."""
    with _lock:
        _events.clear()
    if _shared():
        from app.db.models import AuthEvent
        from app.db.session import session_scope

        with session_scope() as s:
            s.execute(delete(AuthEvent))
            s.commit()
