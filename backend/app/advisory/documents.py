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
    return text_from_bytes(path.name, path.read_bytes())


def text_from_bytes(file_name: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise DocumentError("file is larger than 20 MB")
    if Path(file_name).suffix.lower() == ".pdf":
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
    return add_document_bytes(session, path.name, path.read_bytes(), title=title, crop=crop, language=language, publisher=publisher, url=url, published=published)


def add_document_bytes(
    session: Session, file_name: str, data: bytes, *, title: str, crop: str, language: str, publisher: str, url: str = "", published: str = ""
) -> AdvisoryDocument:
    """Store a document as pending (from the command line or an admin upload)."""
    if Path(file_name).suffix.lower() not in ALLOWED:
        raise DocumentError("only .pdf, .md and .txt files")
    crop = crop.strip().lower() or "all"
    if crop != "all" and crop not in load_reference().crops:
        raise DocumentError(f"unknown crop {crop!r}; use 'all' or one of: {', '.join(load_reference().crops)}")
    if language not in LANGUAGES:
        raise DocumentError(f"language must be one of {LANGUAGES}")
    if not title.strip() or not publisher.strip():
        raise DocumentError("give a title and the publisher (who issued the document)")
    if url and not url.startswith("https://"):
        raise DocumentError("the source link must start with https://")
    text = text_from_bytes(file_name, data)
    passages = split_passages(text)
    if sum(len(p.split()) for _, p in passages) < 30:
        raise DocumentError("no readable text found (a scanned PDF needs OCR first)")
    sha = hashlib.sha256(data).hexdigest()
    if session.scalar(select(AdvisoryDocument).where(AdvisoryDocument.sha256 == sha)):
        raise DocumentError("this file was already added")
    doc = AdvisoryDocument(
        title=title.strip()[:300], crop_id=crop, language=language, publisher=publisher.strip()[:200],
        url=url or None, published=published or None, sha256=sha, file_name=Path(file_name).name[:300], status="pending",
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


CROP_BOOST = 3.0  # a document about the crop asked beats a general ("all") one of similar relevance
LANGUAGE_BOOST = 2.0  # passages in the farmer's language first; others only when nothing in it matches


def search(session: Session, question: str, crop_id: str | None, k: int = 3, language: str | None = None) -> list[dict]:
    """Best passages from approved documents for the crop (or crop-independent documents),
    preferring crop-specific documents and the farmer's language."""
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
    def weight(hit) -> float:
        doc = rows[hit.key][1]
        w = hit.score
        if crop_id and doc.crop_id == crop_id:
            w *= CROP_BOOST
        if language and doc.language == language:
            w *= LANGUAGE_BOOST
        return w

    ranked = sorted(index.search(question, k=max(k * 10, 30)), key=lambda h: -weight(h))
    out = []
    for hit in ranked[:k]:
        chunk, doc = rows[hit.key]
        out.append(
            {
                "document_id": doc.id, "title": doc.title, "publisher": doc.publisher, "url": doc.url, "published": doc.published,
                "language": doc.language, "crop": doc.crop_id, "heading": chunk.heading, "text": chunk.text,
                "score": hit.score, "matched": hit.matched,
            }
        )
    return out
