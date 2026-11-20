"""Chat history retention: questions and answers are kept for HISTORY_RETENTION_DAYS (30).

Older messages are deleted together with their feedback, then any conversation
left with no messages is deleted too. The server runs this at startup and every
hour; `python manage.py purge-history` runs it by hand. Set the setting to 0 to
keep history forever.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Conversation, Feedback, Message

log = logging.getLogger(__name__)


def history_cutoff(now: datetime | None = None) -> datetime | None:
    days = get_settings().history_retention_days
    if days <= 0:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def purge_old_history(db: Session, now: datetime | None = None) -> dict:
    cutoff = history_cutoff(now)
    if cutoff is None:
        return {"messages": 0, "conversations": 0}
    old = select(Message.id).where(Message.created_at < cutoff)
    db.execute(delete(Feedback).where(Feedback.message_id.in_(old)))
    n_messages = db.execute(delete(Message).where(Message.created_at < cutoff)).rowcount or 0
    empty = ~exists().where(Message.conversation_id == Conversation.id)
    n_convs = db.execute(delete(Conversation).where(empty, Conversation.created_at < cutoff)).rowcount or 0
    db.commit()
    if n_messages or n_convs:
        log.info("history retention: deleted %d messages and %d conversations older than %s", n_messages, n_convs, cutoff.date())
    return {"messages": n_messages, "conversations": n_convs}
