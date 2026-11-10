"""Price alerts: evaluate thresholds after each ingestion and notify owners.

Mobile devices get an Expo push notification; every alert also lands in the
in-app inbox (GET /alerts/notifications), which is what the web app shows.
An alert fires at most once per price report date.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.data import load_series
from app.config import get_settings
from app.db.models import Device, Notification, PriceAlert
from app.reference import load_reference
from app.translation.templates import inr, t

log = logging.getLogger(__name__)


def _latest_price(session: Session, alert: PriceAlert, as_of: date) -> tuple[str, float, date] | None:
    stale_after = get_settings().stale_after_days
    series = load_series(session, alert.crop, as_of, lookback_days=stale_after + 1, market=alert.market)
    best = None
    allowed = {alert.market} if alert.market else set(load_reference().scope(alert.district).market_ids)
    for market, pts in series.items():
        if market not in allowed:
            continue
        p = pts[-1]
        if (as_of - p.price_date).days > stale_after:
            continue
        better = best is None or (p.modal_price > best[1] if alert.direction == "above" else p.modal_price < best[1])
        if better:
            best = (market, p.modal_price, p.price_date)
    return best


def send_expo_push(tokens: list[str], title: str, body: str, data: dict | None = None) -> bool:
    if not tokens:
        return False
    s = get_settings()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if s.expo_access_token:
        headers["Authorization"] = f"Bearer {s.expo_access_token}"
    messages = [{"to": tok, "title": title, "body": body, "sound": "default", "data": data or {}} for tok in tokens]
    try:
        resp = httpx.post(s.expo_push_url, json=messages, headers=headers, timeout=20)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("expo push failed: %s", exc)
        return False


def check_alerts(session: Session, as_of: date) -> int:
    """Evaluate all active alerts. Returns the number of notifications created."""
    ref = load_reference()
    created = 0
    for alert in session.scalars(select(PriceAlert).where(PriceAlert.active == 1)):
        if alert.crop not in ref.crops:
            continue
        hit = _latest_price(session, alert, as_of)
        if not hit:
            continue
        market, price, price_date = hit
        crossed = price >= alert.threshold if alert.direction == "above" else price <= alert.threshold
        if not crossed or alert.last_triggered_on == price_date:
            continue
        lang = alert.language
        crop_name = ref.crops[alert.crop].display(lang)
        title = t(lang, "alert.title", crop=crop_name)
        body = t(
            lang,
            f"alert.{alert.direction}",
            crop=crop_name,
            market=ref.markets[market].display(lang),
            price=inr(price),
            date=price_date.isoformat(),
            threshold=inr(alert.threshold),
        )
        owner = Device.user_id == alert.user_id if alert.user_id else Device.guest_id == alert.guest_id
        tokens = [d.push_token for d in session.scalars(select(Device).where(owner))]
        pushed = send_expo_push(tokens, title, body, {"alert_id": alert.id, "crop": alert.crop, "market": market})
        session.add(
            Notification(alert_id=alert.id, user_id=alert.user_id, guest_id=alert.guest_id, title=title, body=body, pushed=int(pushed))
        )
        alert.last_triggered_on = price_date
        created += 1
    session.commit()
    return created
