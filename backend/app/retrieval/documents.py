"""Advisory documents an admin uploads (Markdown, text or PDF).

Uploaded files go into the same bulletin folder as the built-in ones, with the
same front-matter fields, plus `uploaded: <timestamp>` so they can be told
apart (only uploaded documents can be deleted from the admin page). After every
change the advisory index is rebuilt, so the agent answers from the new file on
the next question.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path

from app.retrieval import index as index_mod
from app.retrieval.index import chunk_text, parse_bulletin

ALLOWED_SUFFIXES = {".md", ".txt", ".pdf"}
MAX_BYTES = 10 * 1024 * 1024
_FRONT_MATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


class DocumentError(ValueError):
    pass


def _dir() -> Path:
    return index_mod.BULLETIN_DIR


def _one_line(value: str) -> str:
    return " ".join((value or "").split())[:200]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "document"


def _files() -> list[Path]:
    d = _dir()
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() in ALLOWED_SUFFIXES)


def list_documents() -> list[dict]:
    docs = []
    for path in _files():
        try:
            meta, body = parse_bulletin(path)
        except Exception:  # unreadable file: still show it so the admin can see it
            meta, body = {"id": path.stem, "title": path.stem}, ""
        docs.append(
            {
                "id": meta.get("id", path.stem),
                "title": meta.get("title", path.stem),
                "crop": meta.get("crop", "all"),
                "language": meta.get("language", "en"),
                "source": meta.get("source", "unknown"),
                "published": meta.get("published", ""),
                "state": meta.get("state", "all"),
                "url": meta.get("url") or None,
                "helpline": meta.get("helpline") or None,
                "filename": path.name,
                "format": path.suffix.lower().lstrip("."),
                "chunks": len(chunk_text(body)),
                "words": len(body.split()),
                "uploaded_at": meta.get("uploaded") or None,
                "deletable": bool(meta.get("uploaded")),
            }
        )
    return docs


def _find(doc_id: str) -> Path | None:
    for path in _files():
        try:
            meta, _ = parse_bulletin(path)
        except Exception:
            meta = {}
        if meta.get("id", path.stem) == doc_id:
            return path
    return None


def _unique_id(base: str) -> str:
    taken = {d["id"] for d in list_documents()}
    doc_id, n = base, 2
    while doc_id in taken or (_dir() / f"{doc_id}.md").exists() or (_dir() / f"{doc_id}.pdf").exists():
        doc_id, n = f"{base}-{n}", n + 1
    return doc_id


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise DocumentError(f"Could not read the PDF: {exc}") from exc


def save_document(
    filename: str,
    data: bytes,
    *,
    title: str,
    crop: str,
    language: str,
    source: str,
    published: str,
    state: str = "",
    url: str = "",
    helpline: str = "",
) -> dict:
    """`state`: "all" (or empty) for national documents such as central schemes, else the
    state name as in the district list (e.g. "Maharashtra"); farmers elsewhere never see it."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentError("Only .pdf, .md and .txt files are supported.")
    if len(data) > MAX_BYTES:
        raise DocumentError(f"File is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise DocumentError("The file is empty.")

    if suffix == ".pdf":
        text = _pdf_text(data)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("Text files must be UTF-8.") from exc
        text = _FRONT_MATTER.sub("", text, count=1)  # the form fields replace any front matter
    if len(text.split()) < 5:
        raise DocumentError("No readable text found in the file (a scanned PDF needs OCR first).")

    title = _one_line(title) or Path(filename).stem
    doc_id = _unique_id(_slug(f"{title}-{language}"))
    meta = {
        "id": doc_id,
        "title": title,
        "crop": crop,
        "language": language,
        "source": _one_line(source) or "Uploaded by admin",
        "published": _one_line(published),
        "state": _one_line(state) or "all",
        **({"url": _one_line(url)} if url.strip() else {}),
        **({"helpline": _one_line(helpline)} if helpline.strip() else {}),
        "uploaded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    header = "\n".join(f"{k}: {v}" for k, v in meta.items())

    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    if suffix == ".pdf":
        (d / f"{doc_id}.pdf").write_bytes(data)
        (d / f"{doc_id}.meta").write_text(header + "\n", encoding="utf-8")
    else:
        (d / f"{doc_id}.md").write_text(f"---\n{header}\n---\n{text.strip()}\n", encoding="utf-8")

    index_mod.rebuild_index()
    return next(doc for doc in list_documents() if doc["id"] == doc_id)


def delete_document(doc_id: str) -> None:
    path = _find(doc_id)
    if path is None:
        raise KeyError(doc_id)
    meta, _ = parse_bulletin(path)
    if not meta.get("uploaded"):
        raise DocumentError("Built-in bulletins cannot be deleted from the admin page.")
    path.unlink()
    path.with_suffix(".meta").unlink(missing_ok=True)
    index_mod.rebuild_index()
