"""Weekly district farm advice from the IMD agromet advisory bulletin.

The Gramin Krishi Mausam Sewa unit for each district (for Pune: AMFU, College of
Agriculture, Pune) publishes a bulletin twice a week with last week's weather, a
5-day forecast and crop-by-crop advice. IMD keeps the current one at a fixed URL per
district (AGROMET_URL_TEMPLATE), so the cycle is:

1. download it (twice a day, from the scheduler),
2. check it is a real PDF and not the one already stored (SHA-256),
3. read the issue date, the forecast table and the sections,
4. store it; the district's previous bulletin becomes "superseded",
5. answers use only the district's active bulletin while `valid_until` has not passed,
6. bulletins and their PDFs older than AGROMET_RETENTION_DAYS are deleted.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.db.models import AgrometBulletin
from app.reference import Reference, load_reference

log = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_S = 60.0
RETRY_BACKOFF_S = 15.0
DEFAULT_VALID_DAYS = 4  # when the forecast table cannot be read: the next bulletin is due by then
MAX_VALID_DAYS = 7  # never trust a bulletin longer than a week, whatever its table says


class AgrometError(Exception):
    """The download is not a usable bulletin (not a PDF, no text, no issue date)."""


# --- parsing -------------------------------------------------------------------------

_DATE = r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})"
_ISSUE_PATTERNS = (
    re.compile(r"meeting\s+dated\s+" + _DATE, re.I),
    re.compile(r"\bDate\s*:\s*" + _DATE, re.I),
)
_NUM = r"-?\d+(?:\.\d+)?"
_ROW_LABELS = {
    "rain_mm": re.compile(r"Rainfall\s*\(\s*mm\s*\)", re.I),
    "tmax_c": re.compile(r"Max\.?\s*Temp\.?\s*\(\s*0?\s*C\s*\)", re.I),
    "tmin_c": re.compile(r"Min\.?\s*Temp\.?\s*\(\s*0?\s*C\s*\)", re.I),
}
# Headings that start a section; crop headings are found separately.
_SECTION_STARTS = {
    "weather_summary": re.compile(r"Weather\s+Summary\s*/\s*Alert", re.I),
    "extended_range": re.compile(r"Extended\s+Range\s+Forecast", re.I),
    "general": re.compile(r"General\s+Advisory", re.I),
}
# Bulletin headings that are not app crops but end the previous crop's section.
_OTHER_HEADINGS = (
    "paddy", "rice", "sugarcane", "chickpea", "gram", "pigeon pea", "tur", "rabi sorghum", "kharif sorghum",
    "sorghum", "jowar", "wheat", "rabi maize", "kharif maize", "maize", "bajra", "pearl millet", "soybean",
    "groundnut", "cotton", "sunflower", "safflower", "pomegranate", "banana", "grapes", "grape", "fig",
    "custard apple", "custard", "mango", "guava", "citrus", "orange", "sapota", "papaya", "orchard management",
    "orchard", "animal management", "animal", "livestock", "poultry", "kharif", "rabi", "summer", "note:", "source:",
)
_STAGE_WORDS = re.compile(r"stage|sowing|vegetative|maturity|growth|flowering|fruiting|harvest|pod|nursery|transplant|planting|management", re.I)
_STAGE_START = re.compile(r"(?:\(|-)?\s*(?:" + _STAGE_WORDS.pattern + r")", re.I)


@dataclass
class ParsedBulletin:
    issued_on: date
    valid_until: date
    forecast: list[dict]  # [{date, rain_mm, tmax_c, tmin_c}]
    sections: dict[str, str]  # weather_summary, extended_range, general
    crops: dict[str, str]  # app crop id -> advice text

    def as_json(self) -> dict:
        return {
            "forecast": self.forecast,
            "sections": self.sections,
            "crops": self.crops,
        }


def _clean(text: str) -> str:
    text = text.replace("", "•").replace("•", "•")
    text = re.sub(r"\s+", " ", text).strip()
    # The PDF table splits words at odd places: "i midacloprid", "c ypermethrin", "threshin g".
    # Re-join a stray single letter (never "a", a real word) to the word next to it.
    text = re.sub(r"(?<![\w.%])([b-hj-z]) ([a-z]{3,})", r"\1\2", text)
    text = re.sub(r"(?<![\w.%])i ([a-z]{4,})", r"i\1", text)
    return re.sub(r"([a-z]{3,}) ([b-hj-z])(?=[\s.,;:)]|$)", r"\1\2", text)


def _issue_date(text: str) -> date | None:
    for pattern in _ISSUE_PATTERNS:
        if m := pattern.search(text):
            day, month, year = (int(g) for g in m.groups())
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _day_to_date(day: int, issued: date) -> date | None:
    """Forecast columns give only the day of month; place it in the issue month or the next."""
    month, year = issued.month, issued.year
    if day < issued.day - 7:  # e.g. issued 29 Nov, column "2" means 2 Dec
        month, year = (1, year + 1) if month == 12 else (month + 1, year)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _forecast(lines: list[str], issued: date) -> list[dict]:
    """The weather table: values after each row label are the forecast days."""
    days: list[int] = []
    for line in lines:
        if re.search(r"\bDate\b", line) and len(re.findall(r"\b\d{1,2}\b", line)) >= 4:
            after = line[re.search(r"\bDate\b", line).end():]
            days = [int(x) for x in re.findall(r"\b\d{1,2}\b", after)]
            break
    if not days:
        return []
    rows: dict[str, list[float]] = {}
    for key, label in _ROW_LABELS.items():
        for line in lines:
            if m := label.search(line):
                rows[key] = [float(x) for x in re.findall(_NUM, line[m.end():])]
                break
    out = []
    for i, day in enumerate(days):
        when = _day_to_date(day, issued)
        if when is None:
            continue
        out.append({"date": when.isoformat(), **{k: (v[i] if i < len(v) else None) for k, v in rows.items()}})
    return out


def _crop_names(ref: Reference) -> dict[str, str]:
    """English bulletin heading -> app crop id (crop name and Latin-script aliases)."""
    names: dict[str, str] = {}
    for crop in ref.crops.values():
        for n in (crop.name, *crop.aliases):
            if n.isascii() and len(n) > 2:
                names.setdefault(n.lower(), crop.id)
    return names


def _heading_at(lines: list[str], i: int, names: dict[str, str]) -> tuple[str, int] | None:
    """(heading, lines used) when lines[i] starts a crop section.

    A heading is a crop name followed by its growth stage ("Onion Vegetative Growth Stage"),
    or a crop name alone on its line with the stage on the next lines ("Brinjal" / "Vegetative").
    The PDF table often wraps a heading mid-word ("Pomegranat" / "e"), so a very short next
    line is joined on. A sentence that merely starts with a crop name ("chickpea (gram), wheat
    ... should be planned") is not a heading.
    """

    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()

    line = norm(lines[i])
    nxt = lines[i + 1] if i + 1 < len(lines) else ""
    joined = line + norm(nxt) if nxt and len(nxt.strip()) <= 3 else None
    for candidate, used in ((line, 1), (joined, 2)):
        if not candidate:
            continue
        for name in sorted([*names, *_OTHER_HEADINGS], key=len, reverse=True):
            if name.endswith(":"):
                if candidate.startswith(name):
                    return name, used
                continue
            if candidate != name and not candidate.startswith(name + " "):
                continue
            rest = candidate[len(name):].strip()
            if rest:
                if _STAGE_START.match(rest):
                    return name, used
            elif _STAGE_WORDS.search(norm(" ".join(lines[i + used: i + used + 3]))):
                return name, used
    return None


def parse_bulletin(text: str, ref: Reference | None = None) -> ParsedBulletin:
    ref = ref or load_reference()
    issued = _issue_date(text)
    if issued is None:
        raise AgrometError("no issue date found in the bulletin")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    forecast = _forecast(lines, issued)
    last = max((date.fromisoformat(f["date"]) for f in forecast), default=None)
    valid_until = min(last, issued + timedelta(days=MAX_VALID_DAYS)) if last else issued + timedelta(days=DEFAULT_VALID_DAYS)

    # Walk the lines once, cutting at section headings and crop headings.
    names = _crop_names(ref)
    current: str | None = None
    buckets: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        started = next((key for key, rx in _SECTION_STARTS.items() if rx.search(line)), None)
        if started:
            current = started
            line = _SECTION_STARTS[started].split(line, maxsplit=1)[-1]
            buckets.setdefault(current, []).append(line)
            i += 1
            continue
        if current == "general" or current == "other" or (current and current.startswith("crop:")):
            if hit := _heading_at(lines, i, names):
                heading, used = hit
                crop_id = names.get(heading)
                current = f"crop:{crop_id}" if crop_id else "other"
                head_text = re.sub(r"\s+", " ", "".join(lines[i: i + used]) if used == 2 else lines[i]).strip()
                buckets.setdefault(current, []).append(head_text[len(heading):])
                i += used
                continue
        if current:
            buckets.setdefault(current, []).append(line)
        i += 1

    sections = {key: _clean(" ".join(buckets.get(key, []))) for key in _SECTION_STARTS}
    sections["extended_range"] = re.sub(r"^\(ERFS\)\s*", "", sections["extended_range"])
    crops = {k.split(":", 1)[1]: _clean(" ".join(v)) for k, v in buckets.items() if k.startswith("crop:")}
    return ParsedBulletin(issued, valid_until, forecast, sections, {k: v for k, v in crops.items() if v})


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # a corrupt file must not stop the run for other districts
        raise AgrometError(f"could not read the PDF: {exc}") from exc


# --- download and store --------------------------------------------------------------


def bulletin_url(district_id: str) -> str:
    district = load_reference().districts[district_id]
    return get_settings().agromet_url_template.format(name=quote(district.name), id=district_id)


def _download(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            resp = httpx.get(url, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
            if resp.status_code < 500:
                resp.raise_for_status()  # a 404 will not fix itself
                return resp.content
            last = httpx.HTTPStatusError(f"server error {resp.status_code}", request=resp.request, response=resp)
        except httpx.HTTPStatusError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
        if attempt < FETCH_ATTEMPTS:
            log.warning("agromet download attempt %d/%d failed (%s); retrying", attempt, FETCH_ATTEMPTS, last)
            time.sleep(RETRY_BACKOFF_S)
    assert last is not None
    raise last


def _pdf_dir() -> Path:
    s = get_settings()
    return Path(s.agromet_dir) if s.agromet_dir else DATA_DIR / "agromet"


def fetch_bulletin(session: Session, district_id: str) -> dict:
    """Download, check and store one district's current bulletin. Returns what happened."""
    url = bulletin_url(district_id)
    data = _download(url)
    if data[:5] != b"%PDF-":
        raise AgrometError("the download is not a PDF")
    if len(data) > MAX_BYTES:
        raise AgrometError("the PDF is larger than 10 MB")
    sha = hashlib.sha256(data).hexdigest()
    if existing := session.scalar(select(AgrometBulletin).where(AgrometBulletin.sha256 == sha)):
        return {"district": district_id, "status": "unchanged", "issued_on": existing.issued_on.isoformat()}

    text = pdf_text(data)
    if len(text.split()) < 50:
        raise AgrometError("no readable text in the PDF (scanned?)")
    parsed = parse_bulletin(text)

    active = session.scalars(
        select(AgrometBulletin).where(AgrometBulletin.district == district_id, AgrometBulletin.status == "active")
    ).all()
    if any(b.issued_on > parsed.issued_on for b in active):
        return {"district": district_id, "status": "older_than_stored", "issued_on": parsed.issued_on.isoformat()}

    folder = _pdf_dir() / district_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{parsed.issued_on.isoformat()}-{sha[:8]}.pdf"
    path.write_bytes(data)

    for old in active:
        old.status = "superseded"
    session.add(
        AgrometBulletin(
            district=district_id,
            issued_on=parsed.issued_on,
            valid_until=parsed.valid_until,
            status="active",
            sha256=sha,
            source_url=url,
            file_path=str(path),
            data=parsed.as_json(),
        )
    )
    session.commit()
    log.info("agromet: stored %s bulletin of %s (valid until %s)", district_id, parsed.issued_on, parsed.valid_until)
    return {
        "district": district_id,
        "status": "stored",
        "issued_on": parsed.issued_on.isoformat(),
        "valid_until": parsed.valid_until.isoformat(),
        "crops": sorted(parsed.crops),
    }


def fetch_all(session: Session, today: date) -> list[dict]:
    """Fetch every configured district. One district's failure does not stop the others;
    a district left without a valid bulletin is reported as `stale`."""
    from app.ops import ops_alert

    results = []
    for district_id in get_settings().agromet_district_list:
        if district_id not in load_reference().districts:
            results.append({"district": district_id, "status": "error", "error": "unknown district id"})
            continue
        try:
            results.append(fetch_bulletin(session, district_id))
        except (AgrometError, httpx.HTTPError) as exc:
            session.rollback()
            log.warning("agromet: %s failed: %s", district_id, exc)
            results.append({"district": district_id, "status": "error", "error": str(exc)[:300]})
        if current_bulletin(session, district_id, today) is None:
            results[-1]["stale"] = True
            ops_alert(f"Agromet: no valid IMD bulletin for {district_id} ({results[-1].get('error') or results[-1]['status']}).")
    return results


def current_bulletin(session: Session, district_id: str, today: date) -> AgrometBulletin | None:
    """The district's active bulletin, only while it is still valid."""
    return session.scalars(
        select(AgrometBulletin)
        .where(
            AgrometBulletin.district == district_id,
            AgrometBulletin.status == "active",
            AgrometBulletin.issued_on <= today,
            AgrometBulletin.valid_until >= today,
        )
        .order_by(AgrometBulletin.issued_on.desc())
        .limit(1)
    ).first()


def purge_old_bulletins(session: Session, today: date) -> int:
    """Delete bulletins (and their PDFs) issued more than AGROMET_RETENTION_DAYS ago."""
    days = get_settings().agromet_retention_days
    if days <= 0:
        return 0
    old = session.scalars(select(AgrometBulletin).where(AgrometBulletin.issued_on < today - timedelta(days=days))).all()
    root = _pdf_dir().resolve()
    for b in old:
        if b.file_path:
            path = Path(b.file_path).resolve()
            if root in path.parents:  # only ever delete inside the agromet folder
                path.unlink(missing_ok=True)
        session.delete(b)
    session.commit()
    if old:
        log.info("agromet: deleted %d old bulletins", len(old))
    return len(old)
