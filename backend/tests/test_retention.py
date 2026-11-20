"""Chat history older than HISTORY_RETENTION_DAYS (30) is deleted."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Conversation, Feedback, Message
from app.db.retention import purge_old_history

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _conv(session, *ages_days):
    conv = Conversation(guest_id="retention-guest", title="t", created_at=NOW - timedelta(days=max(ages_days)))
    session.add(conv)
    session.flush()
    msgs = [Message(conversation_id=conv.id, role="user", text=f"q{a}", created_at=NOW - timedelta(days=a)) for a in ages_days]
    session.add_all(msgs)
    session.flush()
    return conv, msgs


def test_purge_keeps_30_days(session):
    old_conv, (old_msg,) = _conv(session, 31)
    mixed_conv, (mixed_old, mixed_new) = _conv(session, 45, 2)
    new_conv, (new_msg,) = _conv(session, 29)
    session.add(Feedback(message_id=old_msg.id, helpful=1))
    session.commit()

    out = purge_old_history(session, now=NOW)
    assert out["messages"] >= 2 and out["conversations"] >= 1

    ids = set(session.scalars(select(Message.id)))
    assert old_msg.id not in ids and mixed_old.id not in ids
    assert {mixed_new.id, new_msg.id} <= ids
    convs = set(session.scalars(select(Conversation.id)))
    assert old_conv.id not in convs and {mixed_conv.id, new_conv.id} <= convs
    assert not session.scalars(select(Feedback).where(Feedback.message_id == old_msg.id)).first()


def test_zero_days_keeps_everything(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "history_retention_days", 0)
    _, (msg,) = _conv(session, 400)
    session.commit()
    assert purge_old_history(session, now=NOW) == {"messages": 0, "conversations": 0}
    assert session.get(Message, msg.id) is not None
