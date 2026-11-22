"""Evaluate the advisory features on labelled farmer questions (en / hi / mr).

Each question in evaluation/test_sets/advisory_questions.jsonl says which feature should
answer it (route: decision, weather, pesticide, scheme, storage, kcc, out_of_scope), and
optionally the scheme, text the answer must contain and text it must not contain.

The script builds a scratch database with sample content for every feature (two years of
demo prices, one IMD bulletin, approved pesticide rows, an approved storage document in
English and Marathi, a few Kisan Call Centre answers), asks every question and reports
routing accuracy and content checks per language and per feature.

Usage (from the repo root):
    python evaluation/scripts/run_advisory_eval.py [--llm]
Without --llm the template answer writer is evaluated (free, deterministic).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "evaluation" / "test_sets" / "advisory_questions.jsonl"
REPORT = ROOT / "evaluation" / "reports" / "advisory_results.md"
AS_OF = date(2026, 11, 8)

BULLETIN = """AGROMET ADVISORY BULLETIN
Weather based Agromet Advisory committee meeting dated 06.11.2026
District : Pune
30 31 01 02 03 04 05 Date 07 08 09 10 11
0.0 0.0 0.0 0.0 0.0 0.0 0.0 Rainfall (mm) 0.0 0.0 0.0 0.0 0.0
32.0 31.8 30.8 31.5 31.7 30.8 30.8 Max. Temp. (0C) 31 33 33 34 33
13.9 12.1 13.5 13.9 14.1 14.0 11.1 Min. Temp. (0C) 13 14 16 16 16
Weather Summary/ Alert The weather may remain dry in the district.
Extended Range Forecast
Rainfall may remain below normal.
General Advisory Harvested produce should be stored in a safe place.
Onion Vegetative
Growth Stage
To control sap-sucking pests, spray a 5% neem kernel extract.
Note: Farmers should take precautionary measures while spraying.
"""
STORAGE_EN = """# Onion storage

Cure the bulbs in the field for three to five days and store only when the neck is fully dry.

## Storage structure

Use a well ventilated onion store with a raised, slatted floor so that air moves through the heap from below and the bulbs do not rot.
"""
STORAGE_MR = """# कांदा साठवण

कांदा काढणीनंतर शेतातच तीन ते पाच दिवस सुकवावा आणि मान पूर्ण वाळल्यावरच साठवणुकीसाठी घ्यावा.

## कांदा चाळ

साठवणुकीसाठी हवेशीर कांदा चाळ वापरा. चाळीचा तळ जमिनीपासून उंच ठेवा म्हणजे खालून हवा खेळती राहते आणि कांदा सडत नाही.
"""
KCC_ROWS = [
    {"QueryText": "onion bulb size small what to do", "KccAns": "Give irrigation at proper intervals and apply recommended fertilizer doses as per soil test", "Crop": "Onion"},
    {"QueryText": "कांद्याचा आकार लहान राहतो काय करावे", "KccAns": "कांद्याला वेळेवर पाणी द्यावे आणि माती परीक्षणानुसार खताची मात्रा द्यावी, तण काढावे", "Crop": "Onion"},
    {"QueryText": "tomato flower drop problem", "KccAns": "Maintain even soil moisture, avoid excess nitrogen and keep the field free of weeds", "Crop": "Tomato"},
]
PESTICIDES = [
    ("Mancozeb 75% WP", "tomato", "Late blight", 5),
    ("Azoxystrobin 23% SC", "tomato", "Early blight", 3),
    ("Thiamethoxam 25% WG", "onion", "Thrips", 7),
]
ROUTE_ORDER = ("scheme", "pesticide", "storage", "kcc", "weather", "decision")


def seed(session) -> None:
    """Sample content for every advisory feature (idempotent per fresh database)."""
    from sqlalchemy import func, select

    from app.advisory.agromet import parse_bulletin
    from app.advisory.documents import add_document_bytes, review_document
    from app.advisory.kcc import import_rows
    from app.db.models import AgrometBulletin, PesticideUse, Price
    from app.ingestion.prices import bulk_insert_prices
    from app.ingestion.synthetic import generate

    if not session.scalar(select(func.count()).select_from(Price)):
        bulk_insert_prices(session, generate(AS_OF - timedelta(days=120), AS_OF), "synthetic")
    parsed = parse_bulletin(BULLETIN)
    session.add(
        AgrometBulletin(
            district="pune", issued_on=parsed.issued_on, valid_until=parsed.valid_until, status="active", sha256="eval" + "0" * 60,
            source_url="https://mausam.imd.gov.in/eval/Pune.pdf", data=parsed.as_json(),
        )
    )
    for chemical, crop, pest, days in PESTICIDES:
        session.add(
            PesticideUse(
                list_kind="fungicides", list_date=date(2026, 9, 30), chemical=chemical, crop_id=crop, pest=pest,
                dose_formulation_per_ha="1500", dilution_l_per_ha="500", waiting_days=days, source_file="eval.pdf", page=1,
                status="approved", reviewed_by="evaluation",
            )
        )
    session.commit()
    for name, text, lang, title in (("en.md", STORAGE_EN, "en", "Onion storage"), ("mr.md", STORAGE_MR, "mr", "कांदा साठवण")):
        doc = add_document_bytes(session, name, text.encode(), title=title, crop="onion", language=lang, publisher="ICAR-DOGR")
        review_document(session, doc.id, "evaluation")
    base = {"StateName": "MAHARASHTRA", "DistrictName": "PUNE", "QueryType": "Cultural Practices", "CreatedOn": "2025-06-10T10:00:00"}
    import_rows(session, [base | r for r in KCC_ROWS], AS_OF)


def route_of(answer) -> str:
    tools = {step["tool"] for step in answer.trace}
    kinds = {s["kind"] for s in answer.sources}
    found = {
        "scheme": "scheme" in kinds or "list_schemes" in tools,
        "pesticide": "lookup_pesticide" in tools,
        "storage": "document" in kinds,
        "kcc": "kcc" in kinds,
        "weather": "get_district_advisory" in tools,
        "decision": "compute_recommendation" in tools,
    }
    return next((r for r in ROUTE_ORDER if found[r]), "out_of_scope")


def evaluate(session, use_llm: bool = False) -> dict:
    from app.agent.service import answer_query

    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for q in rows:
        ans = answer_query(session, q["question"], language=q["lang"], as_of=AS_OF, use_llm=use_llm, district=q.get("district", "pune"))
        route = route_of(ans)
        problems = []
        if route != q["route"]:
            problems.append(f"route {route} (expected {q['route']})")
        if q.get("scheme") and not any(s["id"] == f"scheme:{q['scheme']}" for s in ans.sources):
            problems.append(f"scheme {q['scheme']} not cited")
        problems += [f"missing {c!r}" for c in q.get("contains", []) if c not in ans.text]
        problems += [f"must not contain {c!r}" for c in q.get("not_contains", []) if c in ans.text]
        results.append({"id": q["id"], "lang": q["lang"], "route": q["route"], "got": route, "ok": not problems, "problems": problems, "answer": ans.text})
    by: dict[str, dict[str, list[int]]] = {"lang": defaultdict(list), "route": defaultdict(list)}
    for r in results:
        by["lang"][r["lang"]].append(int(r["ok"]))
        by["route"][r["route"]].append(int(r["ok"]))
    return {
        "questions": len(results),
        "passed": sum(r["ok"] for r in results),
        "routing_accuracy": round(sum(r["route"] == r["got"] for r in results) / len(results), 3),
        "by_language": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by["lang"].items())},
        "by_feature": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by["route"].items())},
        "failures": [r for r in results if not r["ok"]],
    }


def write_report(report: dict, use_llm: bool) -> None:
    lines = [
        f"# Advisory evaluation ({'LLM' if use_llm else 'template answer writer'})",
        "",
        f"{report['passed']}/{report['questions']} questions pass; routing accuracy {report['routing_accuracy']:.0%}.",
        "",
        "| Language | Passed |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in report["by_language"].items()],
        "",
        "| Feature | Passed |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in report["by_feature"].items()],
        "",
    ]
    if report["failures"]:
        lines += ["## Failures", ""] + [f"- `{f['id']}`: {'; '.join(f['problems'])}" for f in report["failures"]]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--llm", action="store_true", help="evaluate the LLM answer writer (needs credentials, costs money)")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="advisory-eval-"))
    os.environ.update(
        DATABASE_URL=f"sqlite:///{(tmp / 'eval.db').as_posix()}", AS_OF_OVERRIDE=AS_OF.isoformat(), AGROMET_DISTRICTS="pune",
        KCC_DISTRICTS="pune", LOCKED_DISTRICT="", LLM_ENABLED="true" if args.llm else "false",
    )
    sys.path.insert(0, str(ROOT / "backend"))
    from app.db.session import init_db, session_scope

    init_db()
    with session_scope() as session:
        seed(session)
        report = evaluate(session, use_llm=args.llm)
    write_report(report, args.llm)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, ensure_ascii=False, indent=2))
    for f in report["failures"]:
        print(f"FAIL {f['id']}: {'; '.join(f['problems'])}\n    {f['answer'][:200]}")
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
