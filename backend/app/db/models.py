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


class AgmarknetMarket(Base):
    """A market found in the Agmarknet feed outside the hand-checked pilot markets.

    Registered by the price ingestion under the district it reports; its position
    is the district centre (Agmarknet publishes no coordinates).
    """

    __tablename__ = "agmarknet_markets"
    __table_args__ = (UniqueConstraint("state", "agmarknet_name", name="uq_agmarknet_market"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    agmarknet_name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(80))
    district: Mapped[str] = mapped_column(String(64), index=True)  # our district id
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)  # None for Google-only accounts
    language: Mapped[str] = mapped_column(String(8), default="en")
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)  # Google account id
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email/password accounts only
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


class AgrometBulletin(Base):
    """One IMD district agromet advisory bulletin (issued twice a week).

    `status` is "active" for the latest bulletin of a district and "superseded" once a newer
    one arrives. Answers use a bulletin only while it is active and `valid_until` has not
    passed; old rows and their PDFs are deleted after AGROMET_RETENTION_DAYS.
    """

    __tablename__ = "agromet_bulletins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    district: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    issued_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    source_url: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)  # parsed forecast table and sections
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PesticideUse(Base):
    """One approved use of a pesticide on an app crop, from the CIB&RC "Major uses" lists.

    Imported as "pending"; only rows a reviewer marked "approved" are used in answers.
    `waiting_days` is the days between the last spray and harvest.
    """

    __tablename__ = "pesticide_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_kind: Mapped[str] = mapped_column(String(40))  # insecticides, fungicides, herbicides, ...
    list_date: Mapped[date] = mapped_column(Date, index=True)  # the list's "as on" date
    chemical: Mapped[str] = mapped_column(String(200))
    crop_id: Mapped[str] = mapped_column(String(32), index=True)
    pest: Mapped[str] = mapped_column(String(300), default="")
    dose_ai_per_ha: Mapped[str] = mapped_column(String(120), default="")
    dose_formulation_per_ha: Mapped[str] = mapped_column(String(120), default="")
    dilution_l_per_ha: Mapped[str] = mapped_column(String(120), default="")
    waiting_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waiting_raw: Mapped[str] = mapped_column(String(60), default="")
    flag: Mapped[str | None] = mapped_column(String(200), nullable=True)  # why a reviewer should look closely
    source_file: Mapped[str] = mapped_column(String(200))
    page: Mapped[int] = mapped_column(Integer)
    original: Mapped[list | None] = mapped_column(JSON, nullable=True)  # the row's cells as printed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | approved | rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdvisoryDocument(Base):
    """A crop advisory document (storage, post-harvest, handling) from an official source.

    Added as "pending"; answers use it only after a reviewer approves it.
    """

    __tablename__ = "advisory_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    crop_id: Mapped[str] = mapped_column(String(32), index=True)  # an app crop id, or "all"
    language: Mapped[str] = mapped_column(String(8))
    publisher: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    file_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | approved | rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdvisoryChunk(Base):
    """One passage of an advisory document (split at headings / paragraphs)."""

    __tablename__ = "advisory_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("advisory_documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)


class KccAnswer(Base):
    """A Kisan Call Centre question and the expert's answer, for one district.

    Imported from the data.gov.in KCC transcripts (API or CSV). Answers that name a
    pesticide or dose are not imported: doses come only from the reviewed CIB&RC list.
    """

    __tablename__ = "kcc_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asked_on: Mapped[date] = mapped_column(Date, index=True)
    state: Mapped[str] = mapped_column(String(60))
    district: Mapped[str] = mapped_column(String(32), index=True)  # app district id
    block: Mapped[str] = mapped_column(String(100), default="")
    crop_raw: Mapped[str] = mapped_column(String(120), default="")
    crop_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    query_type: Mapped[str] = mapped_column(String(120), default="")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)


class SourceWatch(Base):
    """Last seen fingerprint of an official page behind a scheme entry (weekly watch)."""

    __tablename__ = "source_watch"

    url: Mapped[str] = mapped_column(String(500), primary_key=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)

