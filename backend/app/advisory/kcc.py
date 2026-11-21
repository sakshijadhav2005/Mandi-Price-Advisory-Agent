"""Everyday crop questions answered from Kisan Call Centre (KCC) records.

The KCC transcripts on data.gov.in hold farmers' questions and the experts' answers, with
state, district, crop, query type and date (fields StateName, DistrictName, BlockName,
Season, Sector, Category, Crop, QueryType, QueryText, KccAns, CreatedOn). Rows come from
the data.gov.in API (`KCC_RESOURCE_ID`) or a CSV export downloaded from data.gov.in.

Cleaning before anything is stored:
- only the districts in KCC_DISTRICTS and the last KCC_YEARS years;
- weather, scheme and market questions are skipped (other features answer those);
- old rows that store Devanagari as numbers ("2350236723602366") are decoded;
- answers that name a pesticide, a formulation or a dose are dropped: doses and waiting
  periods come only from the reviewed CIB&RC list;
- duplicates (same question and answer) are kept once.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.advisory.search import BM25, guess_language
from app.config import get_settings
from app.db.models import KccAnswer, PesticideUse
from app.reference import detect_crop, load_reference

log = logging.getLogger(__name__)

API_URL = "https://api.data.gov.in/resource/{resource_id}"
SKIP_QUERY_TYPES = ("weather", "government scheme", "market information", "market price", "price")
_FORMULATION = re.compile(r"\b\d+(?:\.\d+)?\s*%?\s*(?:ec|wp|sc|sl|wg|wdg|dp|gr|cs|od|sg|sp|fs|ew|se|zc)\b", re.I)
_DOSE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ml|gm|g|gram|grams|kg|litre|liter|lit|l)\s*(?:/|per)\s*(?:l|lit|litre|liter|acre|ha|hectare|pump|tank|plant)\b"
    r"|(?:मिली|मि\.ली|ग्रॅम|ग्राम|ग्रॅ\.?|लिटर)\s*(?:प्रति|/)",
    re.I,
)
_SPRAY_WITH_NUMBER = re.compile(r"(?:spray|फवारणी|फवारा|छिड़काव|छिडकाव)[^.।]*\d|\d[^.।]*(?:spray|फवारणी|फवारा|छिड़काव|छिडकाव)", re.I)
_CHEMICAL_STEMS = (
    "imidacloprid", "chlorpyrifos", "mancozeb", "carbendazim", "cypermethrin", "monocrotophos", "profenofos", "thiamethoxam",
    "acephate", "dimethoate", "quinalphos", "emamectin", "fipronil", "oxychloride", "carbofuran", "phorate", "methyl bromide",
    "endosulfan", "glyphosate", "paraquat", "atrazine", "metalaxyl", "hexaconazole", "propiconazole", "tebuconazole",
    "streptocycline", "thiram", "captan", "malathion", "deltamethrin", "lambda", "spinosad", "chlorantraniliprole",
    "flubendiamide", "indoxacarb", "dichlorvos", "triazophos", "pendimethalin", "oxyfluorfen",
)
# Typical pesticide name endings, as whole-word endings only ("hexaconazole", "profenofos",
# "insecticide") so that "carbon" or "phosphorus" in fertiliser advice do not match.
_CHEMICAL_ENDINGS = re.compile(r"[a-z]{3,}(?:conazole|thrin|fos|cide|carb|zeb)\b", re.I)
_DEVANAGARI_RUN = re.compile(r"(?:23\d\d|24[0-3]\d){2,}")


class KccError(ValueError):
    pass


def decode_numbers(text: str) -> str:
    """Old KCC rows store Devanagari as code points: "2350236723602366" -> "मिसा"."""
    return _DEVANAGARI_RUN.sub(lambda m: "".join(chr(int(m.group(0)[i: i + 4])) for i in range(0, len(m.group(0)), 4)), text)


def _known_chemicals(session: Session) -> tuple[str, ...]:
    from app.advisory.pesticides import base_name

    names = {base_name(n) for n in session.scalars(select(PesticideUse.chemical).distinct())}
    return tuple(sorted(n for n in names if len(n) > 4))


def names_a_chemical(text: str, extra: tuple[str, ...] = ()) -> bool:
    low = text.lower()
    if _FORMULATION.search(text) or _DOSE.search(text) or _SPRAY_WITH_NUMBER.search(text) or _CHEMICAL_ENDINGS.search(text):
        return True
    return any(stem in low for stem in (*_CHEMICAL_STEMS, *extra))


def _parse_date(row: dict) -> date | None:
    raw = (row.get("CreatedOn") or row.get("created_on") or "").strip()
    day_part = re.split(r"[T ]", raw, maxsplit=1)[0]  # "2024-03-05T10:20:00" / "05-03-2024 10:20"
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(day_part, fmt).date()
        except ValueError:
            continue
    year, month = row.get("year") or row.get("Year"), row.get("month") or row.get("Month")
    if year and month:
        try:
            return date(int(year), int(month), int(row.get("Day") or 1))
        except (TypeError, ValueError):
            return None
    return None


def _district_ids() -> dict[str, str]:
    """KCC DistrictName (upper case) -> app district id, for the configured districts."""
    ref = load_reference()
    wanted = get_settings().kcc_district_list
    return {ref.districts[d].name.upper(): d for d in wanted if d in ref.districts}


def import_rows(session: Session, rows: Iterable[dict], today: date) -> dict:
    districts = _district_ids()
    since = today - timedelta(days=365 * get_settings().kcc_years)
    chemicals = _known_chemicals(session)
    counts = {"read": 0, "stored": 0, "other_district": 0, "old_or_undated": 0, "skipped_type": 0, "names_chemical": 0, "empty": 0, "duplicate": 0}
    seen: set[str] = set(session.scalars(select(KccAnswer.dedupe_key)))
    for row in rows:
        counts["read"] += 1
        district = districts.get((row.get("DistrictName") or "").strip().upper())
        if district is None:
            counts["other_district"] += 1
            continue
        asked = _parse_date(row)
        if asked is None or asked < since or asked > today:
            counts["old_or_undated"] += 1
            continue
        query_type = (row.get("QueryType") or "").strip()
        if any(s in query_type.lower() for s in SKIP_QUERY_TYPES):
            counts["skipped_type"] += 1
            continue
        question = " ".join(decode_numbers(row.get("QueryText") or "").split())
        answer = " ".join(decode_numbers(row.get("KccAns") or "").split())
        if len(question) < 5 or len(answer.split()) < 4:
            counts["empty"] += 1
            continue
        if names_a_chemical(answer, chemicals):
            counts["names_chemical"] += 1
            continue
        key = hashlib.sha256(f"{district}|{question.lower()}|{answer.lower()}".encode()).hexdigest()
        if key in seen:
            counts["duplicate"] += 1
            continue
        seen.add(key)
        crop_raw = (row.get("Crop") or "").strip()
        session.add(
            KccAnswer(
                asked_on=asked, state=(row.get("StateName") or "").strip()[:60], district=district,
                block=(row.get("BlockName") or "").strip()[:100], crop_raw=crop_raw[:120],
                crop_id=detect_crop(crop_raw) or detect_crop(question), query_type=query_type[:120],
                question=question[:2000], answer=answer[:4000], language=guess_language(answer), dedupe_key=key,
            )
        )
        counts["stored"] += 1
    session.commit()
    return counts


def import_csv(session: Session, path: Path, today: date) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return import_rows(session, csv.DictReader(fh), today)


def fetch_api(session: Session, today: date, page_size: int = 500, max_pages: int = 200) -> dict:
    """Download the configured districts from the data.gov.in KCC API (needs KCC_RESOURCE_ID)."""
    s = get_settings()
    if not s.kcc_resource_id:
        raise KccError("set KCC_RESOURCE_ID (the KCC transcripts resource id from data.gov.in), or use import-kcc with a CSV")
    url = API_URL.format(resource_id=s.kcc_resource_id)
    ref = load_reference()
    totals: dict[str, int] = {}
    for district_id in s.kcc_district_list:
        district = ref.districts[district_id]
        rows: list[dict] = []
        for page in range(max_pages):
            params = {
                "api-key": s.data_gov_in_api_key, "format": "json", "limit": page_size, "offset": page * page_size,
                "filters[StateName]": district.state.upper(), "filters[DistrictName]": district.name.upper(),
            }
            batch = _get(url, params).json().get("records", [])
            rows.extend(batch)
            if len(batch) < page_size:
                break
        for k, v in import_rows(session, rows, today).items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _get(url: str, params: dict) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt < 2:
                time.sleep(15)
    assert last is not None
    raise last


def purge_old(session: Session, today: date) -> int:
    cutoff = today - timedelta(days=365 * get_settings().kcc_years)
    n = session.execute(delete(KccAnswer).where(KccAnswer.asked_on < cutoff)).rowcount or 0
    session.commit()
    return n


def search(session: Session, question: str, crop_id: str | None, district: str, language: str, k: int = 3) -> list[dict]:
    """Similar questions answered by KCC experts for the district (and crop), best first;
    answers in the farmer's language are preferred when they match about as well."""
    q = select(KccAnswer).where(KccAnswer.district == district)
    if crop_id:
        q = q.where(KccAnswer.crop_id == crop_id)
    rows = session.scalars(q).all()
    if not rows:
        return []
    hits = BM25([(i, f"{r.question} {r.answer}") for i, r in enumerate(rows)]).search(question, k=k * 3, min_content_terms=2)
    ranked = sorted(hits, key=lambda h: -(h.score * (1.2 if rows[h.key].language == language else 1.0)))
    return [
        {
            "id": rows[h.key].id, "question": rows[h.key].question, "answer": rows[h.key].answer, "asked_on": rows[h.key].asked_on.isoformat(),
            "crop": rows[h.key].crop_id, "language": rows[h.key].language, "query_type": rows[h.key].query_type,
            "score": h.score, "matched": h.matched,
        }
        for h in ranked[:k]
    ]
