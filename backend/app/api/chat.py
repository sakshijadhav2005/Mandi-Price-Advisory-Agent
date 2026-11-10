from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.service import answer_query
from app.api.auth import Identity, get_identity
from app.db.models import Conversation, Feedback, Message
from app.db.session import get_db, session_factory

router = APIRouter(tags=["chat"])

HISTORY_TURNS = 6


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: str = "en"
    crop: str | None = None
    quantity_qtl: float | None = Field(default=None, gt=0, le=10000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    conversation_id: int | None = None
    input_mode: str = "text"  # text | voice
    district: str | None = None


def _owned(conv: Conversation, identity: Identity) -> bool:
    if identity.user:
        return conv.user_id == identity.user.id
    return conv.guest_id == identity.guest_id


def _get_or_create_conversation(db: Session, identity: Identity, body: ChatRequest) -> Conversation:
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if not conv or not _owned(conv, identity):
            raise HTTPException(404, "Conversation not found")
        return conv
    conv = Conversation(
        user_id=identity.user.id if identity.user else None,
        guest_id=identity.guest_id,
        title=body.message[:80],
        language=body.language,
    )
    db.add(conv)
    db.flush()
    return conv


def _history(conv: Conversation) -> list[dict]:
    msgs = conv.messages[-HISTORY_TURNS * 2 :]
    return [{"role": m.role, "content": m.text} for m in msgs]


def _serialise_answer(answer, message_id: int, conversation_id: int) -> dict:
    data = asdict(answer)
    data.pop("audit", None)
    return {"conversation_id": conversation_id, "message_id": message_id, **data}


def handle_chat(db: Session, identity: Identity, body: ChatRequest) -> dict:
    conv = _get_or_create_conversation(db, identity, body)
    history = _history(conv)
    answer = answer_query(
        db,
        body.message,
        language=body.language,
        crop=body.crop,
        quantity_qtl=body.quantity_qtl,
        farmer_lat=body.lat,
        farmer_lon=body.lon,
        history=history,
        district=body.district,
    )
    db.add(Message(conversation_id=conv.id, role="user", text=body.message, language=body.language, payload={"input_mode": body.input_mode}))
    payload = asdict(answer)
    msg = Message(conversation_id=conv.id, role="assistant", text=answer.text, language=answer.language, payload=payload)
    db.add(msg)
    db.commit()
    return _serialise_answer(answer, msg.id, conv.id)


@router.post("/chat")
def chat(body: ChatRequest, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    return handle_chat(db, identity, body)


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """Optional streaming channel. Client sends {"auth": {...headers}, ...ChatRequest}; server
    replies with a status event and then the final answer event."""
    await ws.accept()
    try:
        while True:
            raw = json.loads(await ws.receive_text())
            headers = raw.pop("auth", {}) or {}
            try:
                body = ChatRequest(**raw)
            except Exception as exc:
                await ws.send_json({"type": "error", "detail": str(exc)})
                continue
            await ws.send_json({"type": "status", "stage": "working"})

            def run() -> dict:
                db = session_factory()()
                try:
                    identity = get_identity(headers.get("authorization"), headers.get("x-guest-id"), db)
                    return handle_chat(db, identity, body)
                finally:
                    db.close()

            try:
                result = await asyncio.to_thread(run)
                await ws.send_json({"type": "answer", "data": result})
            except HTTPException as exc:
                await ws.send_json({"type": "error", "detail": exc.detail})
    except WebSocketDisconnect:
        return


@router.get("/conversations")
def list_conversations(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Conversation).order_by(Conversation.id.desc()).limit(50)
    q = q.where(Conversation.user_id == identity.user.id) if identity.user else q.where(Conversation.guest_id == identity.guest_id)
    return [
        {"id": c.id, "title": c.title, "language": c.language, "created_at": c.created_at.isoformat(), "messages": len(c.messages)}
        for c in db.scalars(q)
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conversation_id)
    if not conv or not _owned(conv, identity):
        raise HTTPException(404, "Conversation not found")
    msgs = []
    for m in conv.messages:
        item = {"id": m.id, "role": m.role, "text": m.text, "language": m.language, "created_at": m.created_at.isoformat()}
        if m.role == "assistant" and m.payload:
            p = dict(m.payload)
            p.pop("audit", None)
            item["answer"] = p
        msgs.append(item)
    return {"id": conv.id, "title": conv.title, "language": conv.language, "messages": msgs}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conversation_id)
    if not conv or not _owned(conv, identity):
        raise HTTPException(404, "Conversation not found")
    db.delete(conv)
    db.commit()
    return {"deleted": True}


class FeedbackRequest(BaseModel):
    message_id: int
    helpful: bool
    comment: str = Field(default="", max_length=1000)


@router.post("/feedback")
def feedback(body: FeedbackRequest, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    msg = db.get(Message, body.message_id)
    if not msg or msg.role != "assistant" or not _owned(msg.conversation, identity):
        raise HTTPException(404, "Message not found")
    db.add(Feedback(message_id=msg.id, helpful=int(body.helpful), comment=body.comment))
    db.commit()
    return {"saved": True}
