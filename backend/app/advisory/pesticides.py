"""Safe spraying: approved uses of pesticides on the app's crops, from the official CIB&RC
"Major uses of pesticides" lists (PPQS, Ministry of Agriculture).

Doses and waiting periods are safety-critical, so nothing reaches a farmer unreviewed:

1. `manage.py import-pesticides` reads the list PDFs, keeps the rows for the app's crops,
   stores them as "pending" and writes a review CSV (original cells included, doubtful
   rows flagged).
2. A reviewer marks rows `yes` (and may correct values) and runs
   `manage.py approve-pesticides review.csv --reviewer NAME`.
3. Answers use only approved rows, from the newest list that has approved rows.
4. `check_for_newer_list` looks at the PPQS page for a newer "as on" date (monthly).

The waiting period is the days to wait between the last spray and harvest; it decides
when sprayed produce can be harvested and sold.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import PesticideUse
from app.reference import load_reference

log = logging.getLogger(__name__)

PPQS_PAGE = "https://ppqs.gov.in/divisions/cib-rc/major-uses-of-pesticides"
CSV_FIELDS = [
    "id", "approve", "crop", "chemical", "pest", "dose_ai_per_ha", "dose_formulation_per_ha", "dilution_l_per_ha",
    "waiting_days", "flag", "list", "list_date", "source_file", "page", "original_cells",
]
_LIST_KIND = (("bio-insecticide", "bio-insecticides"), ("bio-fungicide", "bio-fungicides"), ("insecticide", "insecticides"),
              ("fungicide", "fungicides"), ("herbicide", "herbicides"), ("pgr", "plant growth regulators"))
_FORMULATION = re.compile(r"\d|%|\b(?:WP|EC|SC|SL|WG|WDG|DP|GR|CS|OD|SG|SP|FS|ZC|EW|SE|LF|AS)\b")
_NO_WAITING = ("", "-", "--", "nil", "na", "n.a", "not applicable")
MAX_PLAUSIBLE_WAITING = 120


class PesticideError(Exception):
    pass


# --- reading the list PDFs -----------------------------------------------------------------


def _crop_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for crop in load_reference().crops.values():
        for n in (crop.name, *crop.aliases):
            if n.isascii():
                names.setdefault(n.lower(), crop.id)
    return names


def crops_in(cell: str, names: dict[str, str]) -> list[str]:
    """App crop ids named in a list's crop cell ("Tomato", "Cabbage & Cauliflower", "Paddy(Rice)")."""
    text = re.sub(r"\(.*?\)", "", (cell or "").lower()).strip()
    parts = [p.strip(" .") for p in re.split(r"[/,&]| and ", text) if p.strip()]
    return [names[p] for p in parts if p in names]


def base_name(chemical: str) -> str:
    """'Mancozeb 75% WP' -> 'mancozeb'; '(Streptomycin Sulphate 9% + ...) SP' -> 'streptomycin sulphate'."""
    m = re.match(r"[\s(]*([A-Za-z][A-Za-z\-]+(?:\s+[A-Za-z][A-Za-z\-]+)?)", chemical)
    if not m:
        return ""
    return " ".join(w for w in m.group(1).lower().split() if not _FORMULATION.fullmatch(w.upper()))


def _waiting_is_last(header_rows: list[list[str]]) -> bool:
    """True when the table's header puts 'Waiting period ...' in the last column."""
    width = max(len(r) for r in header_rows)
    last = " ".join(r[width - 1] for r in header_rows if len(r) == width).lower()
    return "waiting" in last


def _list_date(first_page_text: str, filename: str) -> date:
    for source in (first_page_text, filename.replace("-", ".")):
        if m := re.search(r"(\d{2})[.](\d{2})[.](\d{4})", source):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if m := re.search(r"(\d{4})[.](\d{2})[.](\d{2})", source):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise PesticideError(f"no 'as on' date in {filename}")


def _list_kind(filename: str) -> str:
    low = filename.lower()
    return next((kind for key, kind in _LIST_KIND if key in low), "pesticides")


def _waiting(raw: str) -> tuple[int | None, str | None]:
    """(days, doubt). "-", "Nil" or blank means no waiting period is stated; that is a fact, not a doubt."""
    raw = raw.strip().rstrip(".")
    if m := re.fullmatch(r"(\d{1,3})\s*(?:days?)?", raw, re.I):
        days = int(m.group(1))
        return days, ("implausible waiting period" if days > MAX_PLAUSIBLE_WAITING else None)
    if raw.lower() in _NO_WAITING:
        return (0 if raw.lower() == "nil" else None), None
    return None, f"waiting period not a single number: {raw!r}"


def _doubts(pest: str, doses: list[str], chemical: str) -> str | None:
    """Why a parsed row may be wrong, for the reviewer's attention."""
    for value in doses:
        numbers = re.findall(r"\d+(?:\.\d+)?", value)
        if len(numbers) > 1 and " " in value.strip() and "-" not in value and "+" not in value:
            return "several values in one cell (row may cover more than one pest)"
    first_word = base_name(chemical).split(" ")[0]
    if first_word and any(first_word in v.lower() for v in doses):
        return "chemical name text inside a dose cell (wrapped table row)"
    if pest.count('"') % 2 or (pest[:1].isalpha() and pest[:1].islower()):
        return "pest text continues from the previous row"
    return None


def parse_list_pdf(path: Path) -> list[dict]:
    """Rows of one CIB&RC list for the app's crops, as plain dicts (not yet stored)."""
    import pdfplumber  # optional dependency: pip install -e ".[pesticides]"

    names = _crop_names()
    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        list_date = _list_date(pdf.pages[0].extract_text() or "", path.name)
        kind = _list_kind(path.name)
        chemical = None
        crop_cell = ""
        pest = ""
        waiting_last = False
        for pno, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                cells_rows = [[" ".join((c or "").split()) for c in row] for row in table]
                # A table that starts with its header says where the waiting period is;
                # tables continued on the next page keep the last header's answer.
                if any("waiting" in c.lower() or "a. i" in c.lower() for r in cells_rows[:3] for c in r):
                    waiting_last = _waiting_is_last(cells_rows[:3])
                for cells in cells_rows:
                    nonempty = [c for c in cells if c]
                    joined = " ".join(cells).lower()
                    if not nonempty or any(k in joined for k in ("waiting period", "dosage per ha", "common name")):
                        continue
                    if len(nonempty) == 1 and cells[0]:
                        if re.match(r"^\d+\.\s", cells[0]) or crops_in(cells[0], names):
                            continue  # a section title ("1. Fungicides single product")
                        if _FORMULATION.search(cells[0]):
                            chemical, crop_cell, pest = cells[0], "", ""
                        continue
                    if not chemical or len(cells) < 4:
                        continue
                    if cells[0]:
                        crop_cell, pest = cells[0], cells[1]
                    elif cells[1]:
                        pest = cells[1]
                    crop_ids = crops_in(crop_cell, names)
                    if not crop_ids:
                        continue
                    # The doses are the filled cells between the pest and the last column:
                    # a.i., formulation, dilution (some tables have an empty spacer column).
                    if waiting_last:
                        waiting_raw, middle = cells[-1], [c for c in cells[2:-1] if c]
                        waiting_days, doubt = _waiting(waiting_raw)
                    else:
                        waiting_raw, middle = "(list has no waiting-period column)", [c for c in cells[2:] if c]
                        waiting_days, doubt = None, None
                    dilution = middle[-1] if len(middle) >= 1 else ""
                    formulation = middle[-2] if len(middle) >= 2 else ""
                    ai = middle[-3] if len(middle) >= 3 else ""
                    flag = doubt or _doubts(pest, [ai, formulation, dilution], chemical)
                    for crop_id in crop_ids:
                        rows.append(
                            {
                                "list_kind": kind,
                                "list_date": list_date,
                                "chemical": chemical,
                                "crop_id": crop_id,
                                "crop_cell": crop_cell,
                                "pest": pest,
                                "dose_ai_per_ha": ai,
                                "dose_formulation_per_ha": formulation,
                                "dilution_l_per_ha": dilution,
                                "waiting_days": waiting_days,
                                "waiting_raw": waiting_raw,
                                "flag": flag,
                                "source_file": path.name,
                                "page": pno,
                                "original": cells,
                            }
                        )
    return rows


# --- import, review, approve -----------------------------------------------------------------


def import_lists(session: Session, folder: Path, review_csv: Path) -> dict:
    """Read every list PDF in `folder`, store the rows as pending (replacing pending rows of
    the same list date) and write the review CSV."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise PesticideError(f"no PDF lists in {folder}")
    parsed = [row for pdf in pdfs for row in parse_list_pdf(pdf)]
    dates = {r["list_date"] for r in parsed}
    session.execute(delete(PesticideUse).where(PesticideUse.status == "pending", PesticideUse.list_date.in_(dates)))
    stored = []
    for r in parsed:
        row = PesticideUse(
            list_kind=r["list_kind"],
            list_date=r["list_date"],
            chemical=r["chemical"][:200],
            crop_id=r["crop_id"],
            pest=r["pest"][:300],
            dose_ai_per_ha=r["dose_ai_per_ha"][:120],
            dose_formulation_per_ha=r["dose_formulation_per_ha"][:120],
            dilution_l_per_ha=r["dilution_l_per_ha"][:120],
            waiting_days=r["waiting_days"],
            waiting_raw=r["waiting_raw"][:60],
            flag=r["flag"],
            source_file=r["source_file"],
            page=r["page"],
            original=r["original"],
            status="pending",
        )
        session.add(row)
        stored.append(row)
    session.commit()
    write_review_csv(stored, review_csv)
    return {
        "rows": len(stored),
        "flagged": sum(1 for r in stored if r.flag),
        "lists": len(pdfs),
        "list_dates": sorted(d.isoformat() for d in dates),
    }


def write_review_csv(rows: list[PesticideUse], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    crops = load_reference().crops
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel opens it as UTF-8
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (r.crop_id, r.chemical, r.pest)):
            writer.writerow(
                {
                    "id": r.id,
                    "approve": "",
                    "crop": crops[r.crop_id].name,
                    "chemical": r.chemical,
                    "pest": r.pest,
                    "dose_ai_per_ha": r.dose_ai_per_ha,
                    "dose_formulation_per_ha": r.dose_formulation_per_ha,
                    "dilution_l_per_ha": r.dilution_l_per_ha,
                    "waiting_days": "" if r.waiting_days is None else r.waiting_days,
                    "flag": r.flag or "",
                    "list": r.list_kind,
                    "list_date": r.list_date.isoformat(),
                    "source_file": r.source_file,
                    "page": r.page,
                    "original_cells": " | ".join(r.original or []),
                }
            )


def approve_from_csv(session: Session, path: Path, reviewer: str) -> dict:
    """Apply a reviewed CSV: rows marked yes become approved (with any corrected values),
    rows marked no are rejected, unmarked rows stay pending."""
    reviewer = reviewer.strip()
    if not reviewer:
        raise PesticideError("give the reviewer's name (--reviewer)")
    counts = {"approved": 0, "rejected": 0, "unchanged": 0}
    now = datetime.now(timezone.utc)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh):
            decision = (rec.get("approve") or "").strip().lower()
            row = session.get(PesticideUse, int(rec["id"])) if (rec.get("id") or "").strip().isdigit() else None
            if row is None or decision not in ("yes", "y", "no", "n"):
                counts["unchanged"] += 1
                continue
            if decision.startswith("y"):
                waiting = (rec.get("waiting_days") or "").strip()
                if waiting and not re.fullmatch(r"\d{1,3}", waiting):
                    raise PesticideError(f"row {row.id}: waiting_days must be whole days, or blank when the list gives none")
                row.waiting_days = int(waiting) if waiting else None
                for field in ("pest", "dose_ai_per_ha", "dose_formulation_per_ha", "dilution_l_per_ha"):
                    setattr(row, field, (rec.get(field) or "").strip()[:300])
                row.status = "approved"
                counts["approved"] += 1
            else:
                row.status = "rejected"
                counts["rejected"] += 1
            row.reviewed_by, row.reviewed_at = reviewer[:120], now
    session.commit()
    return counts


# --- answering -------------------------------------------------------------------------------


def latest_approved_date(session: Session) -> date | None:
    return session.scalar(select(func.max(PesticideUse.list_date)).where(PesticideUse.status == "approved"))


def approved_chemicals(session: Session) -> list[str]:
    """Base names of approved chemicals ("mancozeb"), for spotting them in a question."""
    newest = latest_approved_date(session)
    if newest is None:
        return []
    names = session.scalars(
        select(PesticideUse.chemical).where(PesticideUse.status == "approved", PesticideUse.list_date == newest)
    ).all()
    return sorted({b for b in (base_name(n) for n in names) if b})


def find_uses(
    session: Session, crop_id: str, chemical: str | None = None, pest: str | None = None, limit: int = 8
) -> tuple[date | None, list[PesticideUse]]:
    """Approved uses on a crop from the newest approved list, optionally for one chemical / pest."""
    newest = latest_approved_date(session)
    if newest is None:
        return None, []
    rows = session.scalars(
        select(PesticideUse)
        .where(PesticideUse.status == "approved", PesticideUse.list_date == newest, PesticideUse.crop_id == crop_id)
        .order_by(PesticideUse.chemical, PesticideUse.pest)
    ).all()
    if chemical:
        key = chemical.lower().strip()
        rows = [r for r in rows if key in r.chemical.lower() or (base_name(r.chemical) and base_name(r.chemical) in key)]
    if pest:
        words = re.findall(r"[a-z]{4,}", pest.lower())
        rows = [r for r in rows if any(w in r.pest.lower() for w in words)] or rows
    return newest, list(rows[:limit])


def check_for_newer_list(session: Session) -> dict:
    """Is a newer 'as on' date published on the PPQS page than the newest list stored?"""
    resp = httpx.get(PPQS_PAGE, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    found = []
    for d, m, y in re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", resp.text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    published = max(found, default=None)
    stored = session.scalar(select(func.max(PesticideUse.list_date)))
    return {
        "published": published.isoformat() if published else None,
        "stored": stored.isoformat() if stored else None,
        "newer": bool(published and (stored is None or published > stored)),
    }
