"""Pilot monitoring (plan phase 4). Enabled only when ADMIN_TOKEN is set."""

from __future__ import annotations

import csv
import hmac
import io
import statistics
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.data import last_ingestion, today
from app.config import get_settings
from app.db.models import Feedback, Message, Notification, PriceAlert, User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(404, "Not found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, token):
        raise HTTPException(401, "Admin token required")


def _assistant_rows(db: Session):
    feedback = defaultdict(list)
    for f in db.scalars(select(Feedback)):
        feedback[f.message_id].append(f)
    for m in db.scalars(select(Message).where(Message.role == "assistant").order_by(Message.id)):
        yield m, m.payload or {}, feedback.get(m.id, [])


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(db: Session = Depends(get_db)) -> dict:
    per_lang: dict[str, dict] = defaultdict(lambda: {"answers": 0, "helpful": 0, "not_helpful": 0, "latency": [], "llm": 0, "voice_in": 0})
    decisions, warnings = Counter(), Counter()
    voice_msgs = {m.id + 1 for m in db.scalars(select(Message).where(Message.role == "user")) if (m.payload or {}).get("input_mode") == "voice"}
    for m, p, fbs in _assistant_rows(db):
        s = per_lang[m.language]
        s["answers"] += 1
        s["latency"].append(p.get("latency_ms", 0))
        s["llm"] += p.get("mode") == "llm"
        s["voice_in"] += m.id in voice_msgs
        for f in fbs:
            s["helpful" if f.helpful else "not_helpful"] += 1
        decisions[p.get("decision") or "none"] += 1
        for w in p.get("warnings", []):
            warnings[w.split(":")[0]] += 1
    out_lang = {}
    for lang, s in per_lang.items():
        rated = s["helpful"] + s["not_helpful"]
        lat = sorted(s["latency"])
        out_lang[lang] = {
            "answers": s["answers"],
            "llm_share": s["llm"] / s["answers"],
            "voice_input_share": s["voice_in"] / s["answers"],
            "feedback_count": rated,
            "helpful_rate": s["helpful"] / rated if rated else None,
            "mean_latency_ms": statistics.fmean(lat) if lat else None,
            "p95_latency_ms": lat[int(0.95 * (len(lat) - 1))] if lat else None,
        }
    return {
        "users": len(db.scalars(select(User.id)).all()),
        "per_language": out_lang,
        "decisions": dict(decisions),
        "warnings": dict(warnings),
        "active_alerts": len(db.scalars(select(PriceAlert.id).where(PriceAlert.active == 1)).all()),
        "notifications_sent": len(db.scalars(select(Notification.id)).all()),
        "last_ingestion": last_ingestion(db),
    }


@router.get("/export.csv", dependencies=[Depends(require_admin)])
def export(db: Session = Depends(get_db)) -> StreamingResponse:
    """One row per answer, with the question, decision and feedback (no phone numbers)."""
    questions = {m.id: m.text for m in db.scalars(select(Message).where(Message.role == "user"))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["message_id", "conversation_id", "created_at", "language", "question", "answer", "decision", "confidence", "mode", "latency_ms", "warnings", "helpful", "comment"])
    for m, p, fbs in _assistant_rows(db):
        audit = p.get("audit") or {}
        w.writerow(
            [
                m.id,
                m.conversation_id,
                m.created_at.isoformat(),
                m.language,
                audit.get("question") or questions.get(m.id - 1, ""),
                m.text,
                p.get("decision"),
                p.get("confidence"),
                p.get("mode"),
                p.get("latency_ms"),
                ";".join(p.get("warnings", [])),
                ";".join(str(f.helpful) for f in fbs),
                " | ".join(f.comment for f in fbs if f.comment),
            ]
        )
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=pilot_export.csv"})


# --- advisory content: review status, storage documents ------------------------------------


@router.get("/content", dependencies=[Depends(require_admin)])
def content_status(db: Session = Depends(get_db)) -> dict:
    """What the reviewers still have to do, and what the advisory features have to work with."""
    from app.advisory.schemes import load_schemes, problems_report
    from app.db.models import AdvisoryDocument, AgrometBulletin, KccAnswer, PesticideUse

    def counts(model, column) -> dict:
        return {k: n for k, n in db.execute(select(column, func.count()).select_from(model).group_by(column)).all()}

    latest = db.scalars(select(AgrometBulletin).where(AgrometBulletin.status == "active").order_by(AgrometBulletin.issued_on.desc())).all()
    return {
        "pesticide_rows": counts(PesticideUse, PesticideUse.status),
        "documents": counts(AdvisoryDocument, AdvisoryDocument.status),
        "kcc_answers": db.scalar(select(func.count()).select_from(KccAnswer)) or 0,
        "schemes": {"total": len(load_schemes()), "needs_attention": problems_report(today())},
        "agromet": [{"district": b.district, "issued_on": b.issued_on.isoformat(), "valid_until": b.valid_until.isoformat()} for b in latest],
    }


def _document_out(doc, passages: int) -> dict:
    return {
        "id": doc.id, "title": doc.title, "crop": doc.crop_id, "language": doc.language, "publisher": doc.publisher,
        "url": doc.url, "published": doc.published, "file_name": doc.file_name, "status": doc.status,
        "reviewed_by": doc.reviewed_by, "passages": passages, "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents(db: Session = Depends(get_db)) -> list[dict]:
    from app.db.models import AdvisoryChunk, AdvisoryDocument

    n = dict(db.execute(select(AdvisoryChunk.document_id, func.count()).group_by(AdvisoryChunk.document_id)).all())
    return [_document_out(d, n.get(d.id, 0)) for d in db.scalars(select(AdvisoryDocument).order_by(AdvisoryDocument.id.desc()))]


@router.post("/documents", dependencies=[Depends(require_admin)], status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    crop: str = Form("all"),
    language: str = Form(...),
    publisher: str = Form(...),
    url: str = Form(""),
    published: str = Form(""),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a storage / post-harvest document (PDF, Markdown, text). It is pending until approved."""
    from app.advisory.documents import MAX_BYTES, DocumentError, add_document_bytes
    from app.db.models import AdvisoryChunk

    data = await file.read(MAX_BYTES + 1)
    try:
        doc = add_document_bytes(db, file.filename or "upload.txt", data, title=title, crop=crop, language=language, publisher=publisher, url=url.strip(), published=published.strip())
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _document_out(doc, db.scalar(select(func.count()).select_from(AdvisoryChunk).where(AdvisoryChunk.document_id == doc.id)) or 0)


@router.post("/documents/{doc_id}/{decision}", dependencies=[Depends(require_admin)])
def review_document(doc_id: int, decision: str, reviewer: str = Form(...), db: Session = Depends(get_db)) -> dict:
    """approve / reject a document; the reviewer's name is recorded."""
    from app.advisory.documents import DocumentError
    from app.advisory.documents import review_document as review

    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Use approve or reject")
    try:
        doc = review(db, doc_id, reviewer, approve=decision == "approve")
    except DocumentError as exc:
        raise HTTPException(404 if "no document" in str(exc) else 422, str(exc)) from exc
    return {"id": doc.id, "status": doc.status, "reviewed_by": doc.reviewed_by}

