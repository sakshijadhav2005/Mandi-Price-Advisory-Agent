"""Operations alerts for the people running the service (plan section 6:
"Failed ingestion raises an alert and updates the freshness status").

The freshness status is updated by IngestionRun rows; this module tells a human.
Set OPS_ALERT_WEBHOOK_URL to a Slack, Discord ("/slack" suffix) or Teams incoming
webhook. Without it, alerts are only logged at ERROR level (and reach Sentry if set).
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def run_daily(fetch_prices, check_alerts) -> dict:
    """One run of the daily job: ingest prices, then price alerts. Never raises.

    Alerts a human when ingestion fails or returns no rows (stale data ahead), and
    when the price-alert check fails.
    """
    out = {"rows": None, "ingestion": "ok", "alerts": "ok"}
    try:
        out["rows"] = fetch_prices()
        if not out["rows"]:
            out["ingestion"] = "empty"
            ops_alert("Daily price ingestion returned 0 rows. Prices will go stale; check the data source.")
    except Exception as exc:  # also recorded as a failed IngestionRun by the loader
        out["ingestion"] = "failed"
        ops_alert(f"Daily price ingestion failed: {exc!r}"[:500])
    try:
        check_alerts()
    except Exception as exc:
        out["alerts"] = "failed"
        ops_alert(f"Price alert check failed: {exc!r}"[:500])
    return out


def ops_alert(text: str) -> bool:
    """Log the alert and post it to the webhook. Returns True if the webhook accepted it."""
    log.error("OPS ALERT: %s", text)
    url = get_settings().ops_alert_webhook_url
    if not url:
        return False
    try:
        resp = httpx.post(url, json={"text": f"[Mandi Advisor] {text}"}, timeout=10)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("could not deliver ops alert: %s", exc)
        return False
