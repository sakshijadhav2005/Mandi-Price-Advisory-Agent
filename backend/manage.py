"""Management commands.

    python manage.py init-db
    python manage.py seed-synthetic [--days 730] [--end 2026-11-08]
    python manage.py import-csv path/to/agmarknet_export.csv [--source pilot_ground_truth]
    python manage.py fetch-data-gov            # needs DATA_GOV_IN_API_KEY
    python manage.py fetch-agromet             # this week's IMD district advice (AGROMET_DISTRICTS)
    python manage.py import-pesticides [folder]           # CIB&RC lists -> pending rows + review CSV
    python manage.py approve-pesticides review.csv --reviewer "Name"   # make reviewed rows usable
    python manage.py check-pesticide-list      # is a newer CIB&RC list published?
    python manage.py check-schemes             # validate scheme entries; list unreviewed / outdated ones
    python manage.py add-document FILE --title T --crop onion --language mr --publisher "ICAR-DOGR" [--url U]
    python manage.py approve-document ID --reviewer "Name"   # (reject-document, list-documents)
    python manage.py import-kcc kcc.csv        # Kisan Call Centre answers from a data.gov.in CSV export
    python manage.py fetch-kcc                 # the same from the data.gov.in API (KCC_RESOURCE_ID)
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


PESTICIDE_DIR = Path(__file__).parent / "data" / "rag-sources" / "3-pesticides"
PESTICIDE_REVIEW = Path(__file__).parent / "data" / "pesticides" / "review.csv"


def cmd_import_pesticides(args) -> None:
    from app.advisory.pesticides import import_lists

    init_db()
    with session_scope() as s:
        out = import_lists(s, Path(args.folder), Path(args.review))
    log.info("imported %s; review the rows in %s, then run approve-pesticides", out, args.review)


def cmd_approve_pesticides(args) -> None:
    from app.advisory.pesticides import approve_from_csv

    init_db()
    with session_scope() as s:
        log.info("pesticide review applied: %s", approve_from_csv(s, Path(args.csv), args.reviewer))


def cmd_check_pesticide_list(_args) -> dict:
    from app.advisory.pesticides import check_for_newer_list
    from app.ops import ops_alert

    init_db()
    with session_scope() as s:
        out = check_for_newer_list(s)
    log.info("pesticide list check: %s", out)
    if out["newer"]:
        ops_alert(f"A newer CIB&RC pesticide list ({out['published']}) is published; stored: {out['stored']}. Download it, run import-pesticides and review.")
    return out


def cmd_check_schemes(_args) -> list[str]:
    """Validate data/schemes/*.json (exits with an error on a broken file) and list entries
    that need a person: not reviewed yet, or information older than about six months."""
    from app.advisory.schemes import load_schemes, problems_report

    schemes = load_schemes()
    issues = problems_report(today())
    log.info("%d scheme entries are valid", len(schemes))
    for line in issues:
        log.info("needs attention: %s", line)
    return issues


def cmd_add_document(args) -> None:
    from app.advisory.documents import add_document

    init_db()
    with session_scope() as s:
        doc = add_document(s, Path(args.file), title=args.title, crop=args.crop, language=args.language, publisher=args.publisher, url=args.url or "", published=args.published or "")
        log.info("added document %d (%s) as pending; review it, then: approve-document %d --reviewer NAME", doc.id, doc.title, doc.id)


def cmd_review_document(args) -> None:
    from app.advisory.documents import review_document

    init_db()
    with session_scope() as s:
        doc = review_document(s, args.id, args.reviewer, approve=args.approve)
        log.info("document %d is now %s (reviewed by %s)", doc.id, doc.status, doc.reviewed_by)


def cmd_list_documents(_args) -> None:
    from sqlalchemy import func, select

    from app.db.models import AdvisoryChunk, AdvisoryDocument

    init_db()
    with session_scope() as s:
        for doc in s.scalars(select(AdvisoryDocument).order_by(AdvisoryDocument.id)):
            n = s.scalar(select(func.count()).select_from(AdvisoryChunk).where(AdvisoryChunk.document_id == doc.id))
            print(f"{doc.id:4} {doc.status:9} {doc.language} {doc.crop_id:12} {n:3} passages  {doc.title} ({doc.publisher})")


def cmd_import_kcc(args) -> None:
    from app.advisory.kcc import import_csv

    init_db()
    with session_scope() as s:
        log.info("KCC import: %s", import_csv(s, Path(args.csv), today()))


def cmd_fetch_kcc(_args) -> dict:
    from app.advisory.kcc import fetch_api, purge_old

    init_db()
    with session_scope() as s:
        out = fetch_api(s, today())
        out["deleted_old"] = purge_old(s, today())
    log.info("KCC fetch: %s", out)
    return out


def cmd_daily(args) -> None:
    """One daily run (for cron / Task Scheduler): fetch prices, check alerts, alert ops on failure."""
    from app.ops import run_daily

    log.info("daily job: %s", run_daily(lambda: cmd_fetch_data_gov(args), lambda: cmd_check_alerts(args)))
    try:
        cmd_fetch_agromet(args)
    except Exception:  # district advice must never break the price job
        log.exception("agromet fetch failed")
    if date.today().day == 1:  # the CIB&RC lists and scheme rules change a few times a year: check monthly
        try:
            cmd_check_pesticide_list(args)
        except Exception:
            log.exception("pesticide list check failed")
        try:
            from app.ops import ops_alert

            if issues := [i for i in cmd_check_schemes(args) if "older than" in i]:
                ops_alert("Scheme entries need re-checking: " + "; ".join(issues))
        except Exception:
            log.exception("scheme check failed")
        from app.config import get_settings

        if get_settings().kcc_resource_id:  # new KCC answers once a month
            try:
                cmd_fetch_kcc(args)
            except Exception:
                log.exception("KCC fetch failed")


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
    sp = sub.add_parser("import-pesticides")
    sp.add_argument("folder", nargs="?", default=str(PESTICIDE_DIR))
    sp.add_argument("--review", default=str(PESTICIDE_REVIEW))
    sp.set_defaults(func=cmd_import_pesticides)
    sp = sub.add_parser("approve-pesticides")
    sp.add_argument("csv")
    sp.add_argument("--reviewer", required=True)
    sp.set_defaults(func=cmd_approve_pesticides)
    sub.add_parser("check-pesticide-list").set_defaults(func=cmd_check_pesticide_list)
    sub.add_parser("check-schemes").set_defaults(func=cmd_check_schemes)
    sp = sub.add_parser("add-document")
    sp.add_argument("file")
    sp.add_argument("--title", required=True)
    sp.add_argument("--crop", default="all")
    sp.add_argument("--language", required=True, choices=["en", "hi", "mr"])
    sp.add_argument("--publisher", required=True)
    sp.add_argument("--url")
    sp.add_argument("--published")
    sp.set_defaults(func=cmd_add_document)
    for name, approve in (("approve-document", True), ("reject-document", False)):
        sp = sub.add_parser(name)
        sp.add_argument("id", type=int)
        sp.add_argument("--reviewer", required=True)
        sp.set_defaults(func=cmd_review_document, approve=approve)
    sub.add_parser("list-documents").set_defaults(func=cmd_list_documents)
    sp = sub.add_parser("import-kcc")
    sp.add_argument("csv")
    sp.set_defaults(func=cmd_import_kcc)
    sub.add_parser("fetch-kcc").set_defaults(func=cmd_fetch_kcc)
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
