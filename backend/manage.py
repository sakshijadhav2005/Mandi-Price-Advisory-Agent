"""Management commands.

    python manage.py init-db
    python manage.py seed-synthetic [--days 730] [--end 2026-11-08]
    python manage.py import-csv path/to/agmarknet_export.csv [--source pilot_ground_truth]
    python manage.py fetch-data-gov            # needs DATA_GOV_IN_API_KEY
    python manage.py fetch-agromet             # this week's IMD district advice (AGROMET_DISTRICTS)
    python manage.py purge-synthetic           # drop the demo prices once real ones arrive
    python manage.py purge-history             # delete chat history older than HISTORY_RETENTION_DAYS (30)
    python manage.py check-alerts              # evaluate price alerts, send push notifications
    python manage.py daily                     # once: fetch prices and district advice, check alerts
    python manage.py schedule                  # runs `daily` at --at, and fetch-agromet at 14:00 and 20:00
    python manage.py ask "kanda vikava ka?" --lang mr [--offline]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path

from sqlalchemy import delete

from app.agent.data import today
from app.db.models import Price
from app.db.session import init_db, session_scope
from app.ingestion import prices as price_ingest
from app.ingestion.synthetic import generate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("manage")


def cmd_init_db(_args) -> None:
    init_db()
    log.info("database ready")


def cmd_seed_synthetic(args) -> None:
    init_db()
    end = date.fromisoformat(args.end) if args.end else today()
    start = end - timedelta(days=args.days)
    rows = generate(start, end, seed=args.seed)
    with session_scope() as s:
        s.execute(delete(Price).where(Price.source == "synthetic"))
        n = price_ingest.bulk_insert_prices(s, rows, "synthetic")
    log.info("inserted %d synthetic price rows (%s .. %s)", n, start, end)


def cmd_purge_synthetic(_args) -> None:
    """Delete the synthetic demo prices. Run this once real prices are flowing."""
    init_db()
    with session_scope() as s:
        n = s.execute(delete(Price).where(Price.source == "synthetic")).rowcount
        s.commit()
    log.info("deleted %d synthetic price rows", n)


def cmd_purge_history(_args) -> None:
    """Delete chat questions/answers older than HISTORY_RETENTION_DAYS (the server also does this hourly)."""
    from app.db.retention import purge_old_history

    init_db()
    with session_scope() as s:
        log.info("history retention: %s", purge_old_history(s))


def cmd_import_csv(args) -> None:
    init_db()
    with session_scope() as s:
        n = price_ingest.load_csv(s, Path(args.path), source=args.source)
    log.info("imported %d rows from %s as source=%s", n, args.path, args.source)


def cmd_fetch_data_gov(_args) -> int:
    init_db()
    with session_scope() as s:
        n = price_ingest.fetch_data_gov_in(s)
    log.info("fetched %d rows from data.gov.in", n)
    return n


def cmd_fetch_agromet(_args) -> list[dict]:
    """Download this week's IMD agromet bulletin for each district in AGROMET_DISTRICTS."""
    from app.advisory.agromet import fetch_all

    init_db()
    with session_scope() as s:
        results = fetch_all(s, today())
    for r in results:
        log.info("agromet %s: %s", r["district"], r)
    return results


def cmd_daily(args) -> None:
    """One daily run (for cron / Task Scheduler): fetch prices, check alerts, alert ops on failure."""
    from app.ops import run_daily

    log.info("daily job: %s", run_daily(lambda: cmd_fetch_data_gov(args), lambda: cmd_check_alerts(args)))
    try:
        cmd_fetch_agromet(args)
    except Exception:  # district advice must never break the price job
        log.exception("agromet fetch failed")


def cmd_check_alerts(_args) -> None:
    from app.alerts import check_alerts

    init_db()
    with session_scope() as s:
        n = check_alerts(s, today())
    log.info("created %d alert notifications", n)


def cmd_schedule(args) -> None:
    """Minimal scheduler: `daily` at --at, and the IMD bulletin check at 14:00 and 20:00
    (bulletins come out on meeting days, at no fixed hour). For production use cron,
    systemd timers or Celery beat."""
    init_db()
    jobs = [(datetime.strptime(args.at, "%H:%M").time(), "daily"), (dt_time(14, 0), "agromet"), (dt_time(20, 0), "agromet")]
    while True:
        now = datetime.now()
        upcoming = []
        for at, job in jobs:
            target = datetime.combine(now.date(), at)
            upcoming.append((target if target > now else target + timedelta(days=1), job))
        target, job = min(upcoming)
        log.info("next job %s at %s", job, target)
        time.sleep((target - now).total_seconds())
        if job == "daily":
            cmd_daily(args)
        else:
            try:
                cmd_fetch_agromet(args)
            except Exception:
                log.exception("agromet fetch failed")


def cmd_ask(args) -> None:
    from dataclasses import asdict

    from app.agent.service import answer_query

    init_db()
    with session_scope() as s:
        ans = answer_query(s, args.question, language=args.lang, crop=args.crop, use_llm=not args.offline)
    out = asdict(ans)
    if not args.verbose:
        out = {k: out[k] for k in ("text", "decision", "confidence", "mode", "warnings", "latency_ms", "usage")} | {
            "disclaimer": ans.disclaimer,
            "sources": [x["id"] for x in ans.sources],
            "trace": [f"{t['tool']}: {t['summary']}" for t in ans.trace],
        }
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sp = sub.add_parser("seed-synthetic")
    sp.add_argument("--days", type=int, default=730)
    sp.add_argument("--end", default="")
    sp.add_argument("--seed", type=int, default=7)
    sp.set_defaults(func=cmd_seed_synthetic)
    sp = sub.add_parser("import-csv")
    sp.add_argument("path")
    sp.add_argument("--source", default="agmarknet_csv", help="e.g. pilot_ground_truth for prices farmers actually received")
    sp.set_defaults(func=cmd_import_csv)
    sub.add_parser("fetch-data-gov").set_defaults(func=cmd_fetch_data_gov)
    sub.add_parser("fetch-agromet").set_defaults(func=cmd_fetch_agromet)
    sub.add_parser("purge-synthetic").set_defaults(func=cmd_purge_synthetic)
    sub.add_parser("purge-history").set_defaults(func=cmd_purge_history)
    sub.add_parser("check-alerts").set_defaults(func=cmd_check_alerts)
    sub.add_parser("daily").set_defaults(func=cmd_daily)
    sp = sub.add_parser("schedule")
    sp.add_argument("--at", default="18:30", help="local time HH:MM (Agmarknet updates through the day)")
    sp.set_defaults(func=cmd_schedule)
    sp = sub.add_parser("ask")
    sp.add_argument("question")
    sp.add_argument("--lang", default="en")
    sp.add_argument("--crop", default=None)
    sp.add_argument("--offline", action="store_true", help="skip the LLM and use the template writer")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(func=cmd_ask)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
