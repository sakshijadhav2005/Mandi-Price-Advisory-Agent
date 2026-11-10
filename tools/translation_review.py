"""Native-speaker review of Hindi / Marathi text (plan day 11-12).

export: writes docs/review/translations_<lang>.csv with every farmer-facing string
        (app UI, answer templates, glossary) next to the English source. Opens in Excel.
apply:  reads the reviewed CSV and writes corrections back into the language files.

Reviewer instructions: for each row, leave `status` as `ok`, or write the corrected
text in `correction` (status becomes `fix`). Keep {placeholders} and {{placeholders}}
exactly as they are. Add any note in `comment`.

    python tools/translation_review.py export mr
    python tools/translation_review.py apply mr docs/review/translations_mr.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "packages" / "i18n" / "src" / "locales"
PACK_DIR = ROOT / "backend" / "data" / "languages"
OUT_DIR = ROOT / "docs" / "review"
FIELDS = ["id", "where", "english", "current", "status", "correction", "comment"]
PLACEHOLDER = re.compile(r"\{\{?\w+\}?\}")


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def rows_for(lang: str) -> list[dict]:
    rows = []
    ui_en = dict(_flatten(json.loads((UI_DIR / "en.json").read_text(encoding="utf-8"))))
    ui = dict(_flatten(json.loads((UI_DIR / f"{lang}.json").read_text(encoding="utf-8"))))
    for key, value in ui.items():
        rows.append({"id": f"ui:{key}", "where": "App screen text", "english": ui_en.get(key, ""), "current": value})
    pack_en = json.loads((PACK_DIR / "en.json").read_text(encoding="utf-8"))
    pack = json.loads((PACK_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for key, value in pack["templates"].items():
        rows.append({"id": f"answer:{key}", "where": "Spoken/written answer", "english": pack_en["templates"].get(key, ""), "current": value})
    for term, renderings in pack.get("glossary", {}).items():
        rows.append({"id": f"glossary:{term}", "where": "Agricultural term (comma-separated, preferred first)", "english": term, "current": ", ".join(renderings)})
    for r in rows:
        r.update(status="ok", correction="", comment="")
    return rows


def export(lang: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"translations_{lang}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM so Excel shows Devanagari
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows_for(lang))
    return path


def _set_path(obj, dotted: str, value):
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", dotted)
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        key = int(part[1:-1]) if part.startswith("[") else part
        if last:
            obj[key] = value
        else:
            obj = obj[key]


def apply(lang: str, csv_path: Path) -> int:
    ui_file, pack_file = UI_DIR / f"{lang}.json", PACK_DIR / f"{lang}.json"
    ui = json.loads(ui_file.read_text(encoding="utf-8"))
    pack = json.loads(pack_file.read_text(encoding="utf-8"))
    current = {r["id"]: r for r in rows_for(lang)}
    changed, errors = 0, []
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            fix = (row.get("correction") or "").strip()
            if not fix:
                continue
            rid = row["id"]
            if rid not in current:
                errors.append(f"{rid}: unknown id")
                continue
            want = sorted(PLACEHOLDER.findall(current[rid]["english"] or current[rid]["current"]))
            if rid.startswith(("ui:", "answer:")) and sorted(PLACEHOLDER.findall(fix)) != want:
                errors.append(f"{rid}: placeholders must stay {want}, got {sorted(PLACEHOLDER.findall(fix))}")
                continue
            kind, key = rid.split(":", 1)
            if kind == "ui":
                _set_path(ui, key, fix)
            elif kind == "answer":
                pack["templates"][key] = fix
            elif kind == "glossary":
                pack["glossary"][key] = [x.strip() for x in fix.split(",") if x.strip()]
            changed += 1
    if errors:
        print("Not applied (fix these rows and run again):", *errors, sep="\n  ")
    ui_file.write_text(json.dumps(ui, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pack["review_status"] = "reviewed"
    pack_file.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("lang")
    a = sub.add_parser("apply")
    a.add_argument("lang")
    a.add_argument("csv", type=Path)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "export":
        path = export(args.lang)
        print(f"{path} ({len(rows_for(args.lang))} strings)")
    else:
        print(f"applied {apply(args.lang, args.csv)} corrections")


if __name__ == "__main__":
    main()
