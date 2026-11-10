"""SQLAlchemy models: prices, users, conversations, feedback, ingestion runs."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Price(Base):
    """One daily price observation for a crop at a market (Rs per quintal)."""

    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("crop", "market", "price_date", "source", name="uq_price_obs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crop: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(64), index=True)
    price_date: Mapped[date] = mapped_column(Date, index=True)
    min_price: Mapped[float] = mapped_column(Float)
    modal_price: Mapped[float] = mapped_column(Float)
    max_price: Mapped[float] = mapped_column(Float)
    arrivals_tonnes: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="unknown")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(32))  # prices | bulletins
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # ok | failed
    rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # For assistant turns: decision, confidence, sources, tool trace, English audit.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    helpful: Mapped[int] = mapped_column(Integer)  # 1 or 0
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    """A mobile device registered for push notifications (Expo push token)."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    push_token: Mapped[str] = mapped_column(String(200), unique=True)
    platform: Mapped[str] = mapped_column(String(16), default="unknown")
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PriceAlert(Base):
    """Notify when a crop's modal price at a market (or the best nearby market) crosses a threshold."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    crop: Mapped[str] = mapped_column(String(32))
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)  # None = best market in the district
    district: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction: Mapped[str] = mapped_column(String(8))  # above | below
    threshold: Mapped[float] = mapped_column(Float)  # Rs per quintal, modal price
    language: Mapped[str] = mapped_column(String(8), default="en")
    active: Mapped[int] = mapped_column(Integer, default=1)
    last_triggered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    """In-app inbox entry (web) and record of push deliveries (mobile)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("price_alerts.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    pushed: Mapped[int] = mapped_column(Integer, default=0)
    read: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
