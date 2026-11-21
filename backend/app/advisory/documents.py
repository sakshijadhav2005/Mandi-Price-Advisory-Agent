"""Storage and post-harvest advice from reviewed official documents (DOGR, CPRI, KVK, MPKV ...).

1. `manage.py add-document FILE --title ... --crop onion --language mr --publisher ...`
   reads a PDF, Markdown or text file, splits it into passages at headings and
   paragraphs, and stores it as "pending".
2. `manage.py approve-document ID --reviewer NAME` makes it usable (`reject-document`
   removes it from answers; `list-documents` shows the status of each).
3. Answers search only approved documents, for the crop asked about (or "all"), and
   quote the best passage with its title and publisher.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.search import BM25
from app.db.models import AdvisoryChunk, AdvisoryDocument
from app.reference import load_reference

ALLOWED = {".pdf", ".md", ".txt"}
MAX_BYTES = 20 * 1024 * 1024
CHUNK_WORDS = 120
LANGUAGES = ("en", "hi", "mr")


class DocumentError(ValueError):
    pass


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise DocumentError("file is larger than 20 MB")
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        try:
            return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception as exc:
            raise DocumentError(f"could not read the PDF: {exc}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentError("text files must be UTF-8") from exc


def split_passages(text: str) -> list[tuple[str, str]]:
    """(heading, passage) pairs: a Markdown heading or a short line ending without a full
    stop starts a section; paragraphs are packed into passages of about CHUNK_WORDS words."""
    heading = ""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append((heading, " ".join(buf)))
            buf.clear()

    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        md = re.match(r"^#{1,6}\s+(.*)$", para)
        if md or (len(para.split()) <= 8 and not re.search(r"[.।!?:;]$", para)):
            flush()
            heading = (md.group(1) if md else para)[:300]
            continue
        if buf and len(" ".join(buf + [para]).split()) > CHUNK_WORDS:
            flush()
        buf.append(para)
    flush()
    return out


def add_document(session: Session, path: Path, *, title: str, crop: str, language: str, publisher: str, url: str = "", published: str = "") -> AdvisoryDocument:
    if path.suffix.lower() not in ALLOWED:
        raise DocumentError("only .pdf, .md and .txt files")
    crop = crop.strip().lower() or "all"
    if crop != "all" and crop not in load_reference().crops:
        raise DocumentError(f"unknown crop {crop!r}; use 'all' or one of: {', '.join(load_reference().crops)}")
    if language not in LANGUAGES:
        raise DocumentError(f"language must be one of {LANGUAGES}")
    if not title.strip() or not publisher.strip():
        raise DocumentError("give a --title and the --publisher (who issued the document)")
    if url and not url.startswith("https://"):
        raise DocumentError("the source link must start with https://")
    text = read_text(path)
    passages = split_passages(text)
    if sum(len(p.split()) for _, p in passages) < 30:
        raise DocumentError("no readable text found (a scanned PDF needs OCR first)")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if session.scalar(select(AdvisoryDocument).where(AdvisoryDocument.sha256 == sha)):
        raise DocumentError("this file was already added")
    doc = AdvisoryDocument(
        title=title.strip()[:300], crop_id=crop, language=language, publisher=publisher.strip()[:200],
        url=url or None, published=published or None, sha256=sha, file_name=path.name[:300], status="pending",
    )
    session.add(doc)
    session.flush()
    for i, (heading, passage) in enumerate(passages):
        session.add(AdvisoryChunk(document_id=doc.id, position=i, heading=heading, text=passage))
    session.commit()
    return doc


def review_document(session: Session, doc_id: int, reviewer: str, approve: bool = True) -> AdvisoryDocument:
    doc = session.get(AdvisoryDocument, doc_id)
    if doc is None:
        raise DocumentError(f"no document {doc_id}")
    if not reviewer.strip():
        raise DocumentError("give the reviewer's name (--reviewer)")
    doc.status = "approved" if approve else "rejected"
    doc.reviewed_by, doc.reviewed_at = reviewer.strip()[:120], datetime.now(timezone.utc)
    session.commit()
    return doc


def search(session: Session, question: str, crop_id: str | None, k: int = 3) -> list[dict]:
    """Best passages from approved documents for the crop (or crop-independent documents)."""
    q = (
        select(AdvisoryChunk, AdvisoryDocument)
        .join(AdvisoryDocument, AdvisoryChunk.document_id == AdvisoryDocument.id)
        .where(AdvisoryDocument.status == "approved")
    )
    if crop_id:
        q = q.where(AdvisoryDocument.crop_id.in_([crop_id, "all"]))
    rows = session.execute(q).all()
    if not rows:
        return []
    index = BM25([(i, f"{doc.title} {chunk.heading} {chunk.text}") for i, (chunk, doc) in enumerate(rows)])
    out = []
    for hit in index.search(question, k=k):
        chunk, doc = rows[hit.key]
        out.append(
            {
                "document_id": doc.id, "title": doc.title, "publisher": doc.publisher, "url": doc.url, "published": doc.published,
                "language": doc.language, "crop": doc.crop_id, "heading": chunk.heading, "text": chunk.text,
                "score": hit.score, "matched": hit.matched,
            }
        )
    return out
