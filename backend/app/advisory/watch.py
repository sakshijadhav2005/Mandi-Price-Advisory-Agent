"""Weekly watch of the official pages behind the scheme entries.

Scheme rules change by notification or GR, and the entries in data/schemes/ only change
when a person updates them. This job fetches each scheme's official page, keeps a
fingerprint of its visible text and sends an ops alert naming the schemes to re-check
when the text changes. The first check of a page only records it.

The fingerprint ignores scripts, styles, tags and numbers, so dates, visitor counters and
similar churn do not raise alerts. A page that is only a JavaScript shell never changes
here; such sources have to be checked by hand.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.advisory.schemes import load_schemes
from app.db.models import SourceWatch

log = logging.getLogger(__name__)

_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_DIGITS = re.compile(r"\d+")


def page_fingerprint(html: str) -> str:
    text = _TAG.sub(" ", _SCRIPT.sub(" ", html))
    text = _DIGITS.sub("#", text)
    text = " ".join(text.split()).lower()
    return hashlib.sha256(text.encode()).hexdigest()


def watched_pages() -> dict[str, list[str]]:
    """Official URL -> the scheme ids that rely on it."""
    pages: dict[str, list[str]] = defaultdict(list)
    for scheme in load_schemes().values():
        pages[scheme.url].append(scheme.id)
    return dict(pages)


def check_sources(session: Session, alert=None) -> dict:
    """Fetch every watched page once; returns counts and the changed pages."""
    if alert is None:
        from app.ops import ops_alert as alert
    now = datetime.now(timezone.utc)
    result = {"checked": 0, "new": 0, "unchanged": 0, "changed": [], "failed": []}
    for url, scheme_ids in watched_pages().items():
        row = session.get(SourceWatch, url) or SourceWatch(url=url)
        session.add(row)
        row.checked_at = now
        try:
            resp = httpx.get(url, timeout=45, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; scheme-watch)"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            row.error = str(exc)[:300]
            result["failed"].append(url)
            continue
        row.error = None
        result["checked"] += 1
        fingerprint = page_fingerprint(resp.text)
        if row.fingerprint is None:
            result["new"] += 1
        elif row.fingerprint == fingerprint:
            result["unchanged"] += 1
        else:
            row.changed_at = now
            result["changed"].append({"url": url, "schemes": scheme_ids})
        row.fingerprint = fingerprint
    session.commit()
    if result["changed"]:
        lines = "; ".join(f"{c['url']} ({', '.join(c['schemes'])})" for c in result["changed"])
        alert(f"Official scheme pages changed: {lines}. Re-check these entries in backend/data/schemes/.")
    log.info("source watch: %s", {k: (v if isinstance(v, int) else len(v)) for k, v in result.items()})
    return result
