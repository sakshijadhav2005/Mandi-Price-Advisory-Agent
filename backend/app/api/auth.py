"""Phone-number OTP login with JWT access tokens.

In OTP dev mode the code is logged (and returned in the response) instead of
being sent by SMS; an SMS gateway plugs into `send_sms`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import OtpCode, User
from app.db.session import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

PHONE_RE = re.compile(r"^(?:\+?91|0)?[6-9]\d{9}$")
OTP_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5


def normalise_phone(phone: str) -> str:
    digits = re.sub(r"[\s-]", "", phone)
    if not PHONE_RE.match(digits):
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number")
    return "+91" + digits[-10:]


def _hash(phone: str, code: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def send_sms(phone: str, text: str) -> None:
    raise NotImplementedError("Connect an SMS gateway here")


def issue_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "iat": now, "exp": now + timedelta(hours=s.jwt_ttl_hours)}, s.jwt_secret, algorithm="HS256")


class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)
    language: str | None = None


@router.post("/otp/request")
def request_otp(body: OtpRequest, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    phone = normalise_phone(body.phone)
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(OtpCode(phone=phone, code_hash=_hash(phone, code), expires_at=datetime.now(timezone.utc) + OTP_TTL))
    db.commit()
    if s.otp_dev_mode:
        log.info("DEV OTP for %s: %s", phone, code)
        return {"sent": True, "dev_code": code}
    send_sms(phone, f"Your Mandi Advisor code is {code}")
    return {"sent": True}


@router.post("/otp/verify")
def verify_otp(body: OtpVerify, db: Session = Depends(get_db)) -> dict:
    phone = normalise_phone(body.phone)
    otp = db.scalars(
        select(OtpCode).where(OtpCode.phone == phone, OtpCode.used == 0).order_by(OtpCode.id.desc()).limit(1)
    ).first()
    now = datetime.now(timezone.utc)
    if not otp or otp.expires_at.replace(tzinfo=otp.expires_at.tzinfo or timezone.utc) < now:
        raise HTTPException(400, "Code expired. Request a new one.")
    if otp.attempts >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many attempts. Request a new code.")
    otp.attempts += 1
    if not hmac.compare_digest(otp.code_hash, _hash(phone, body.code)):
        db.commit()
        raise HTTPException(400, "Incorrect code")
    otp.used = 1
    user = db.scalars(select(User).where(User.phone == phone)).first()
    if not user:
        user = User(phone=phone, language=body.language or "en")
        db.add(user)
    elif body.language:
        user.language = body.language
    db.commit()
    return {"token": issue_token(user), "user": {"id": user.id, "phone": user.phone, "language": user.language}}


@dataclass
class Identity:
    user: User | None
    guest_id: str | None


def get_identity(
    authorization: str | None = Header(default=None),
    x_guest_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Identity:
    s = get_settings()
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = jwt.decode(authorization[7:], s.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(401, "Invalid or expired token")
        user = db.get(User, int(claims["sub"]))
        if not user:
            raise HTTPException(401, "Unknown user")
        return Identity(user=user, guest_id=None)
    if s.auth_required:
        raise HTTPException(401, "Login required")
    if not x_guest_id or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", x_guest_id):
        raise HTTPException(401, "Send an X-Guest-Id header or log in")
    return Identity(user=None, guest_id=x_guest_id)


@router.get("/me")
def me(identity: Identity = Depends(get_identity)) -> dict:
    if identity.user:
        return {"id": identity.user.id, "phone": identity.user.phone, "language": identity.user.language}
    return {"guest_id": identity.guest_id}
