"""Pilot monitoring (plan phase 4). Enabled only when ADMIN_TOKEN is set."""

from __future__ import annotations

import csv
import hmac
import io
import statistics
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.data import last_ingestion
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
