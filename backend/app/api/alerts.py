from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Identity, get_identity
from app.db.models import Device, Notification, PriceAlert
from app.db.session import get_db
from app.reference import load_reference

router = APIRouter(tags=["alerts"])

MAX_ALERTS = 10


def _owner_filter(model, identity: Identity):
    return model.user_id == identity.user.id if identity.user else model.guest_id == identity.guest_id


def _owner_fields(identity: Identity) -> dict:
    return {"user_id": identity.user.id if identity.user else None, "guest_id": identity.guest_id}


class DeviceIn(BaseModel):
    push_token: str = Field(min_length=10, max_length=200)
    platform: Literal["android", "ios", "web", "unknown"] = "unknown"
    language: str = "en"


@router.post("/devices")
def register_device(body: DeviceIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    device = db.scalars(select(Device).where(Device.push_token == body.push_token)).first()
    if device is None:
        device = Device(push_token=body.push_token)
        db.add(device)
    device.platform, device.language = body.platform, body.language
    device.user_id, device.guest_id = _owner_fields(identity).values()
    db.commit()
    return {"registered": True}


class AlertIn(BaseModel):
    crop: str
    market: str | None = None
    direction: Literal["above", "below"]
    threshold: float = Field(gt=0, lt=100000)
    language: str = "en"
    district: str | None = None


def _alert_out(a: PriceAlert) -> dict:
    return {
        "id": a.id,
        "crop": a.crop,
        "market": a.market,
        "district": a.district,
        "direction": a.direction,
        "threshold": a.threshold,
        "language": a.language,
        "active": bool(a.active),
        "last_triggered_on": a.last_triggered_on.isoformat() if a.last_triggered_on else None,
    }


@router.get("/alerts")
def list_alerts(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> list[dict]:
    return [_alert_out(a) for a in db.scalars(select(PriceAlert).where(_owner_filter(PriceAlert, identity)).order_by(PriceAlert.id))]


@router.post("/alerts")
def create_alert(body: AlertIn, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    ref = load_reference()
    if body.crop not in ref.crops:
        raise HTTPException(422, f"Unknown crop {body.crop!r}")
    if body.market and body.market not in ref.markets:
        raise HTTPException(422, f"Unknown market {body.market!r}")
    if body.district and body.district not in ref.districts:
        raise HTTPException(422, f"Unknown district {body.district!r}")
    existing = db.scalars(select(PriceAlert).where(_owner_filter(PriceAlert, identity), PriceAlert.active == 1)).all()
    if len(existing) >= MAX_ALERTS:
        raise HTTPException(429, f"At most {MAX_ALERTS} active alerts")
    alert = PriceAlert(**body.model_dump(), **_owner_fields(identity))
    db.add(alert)
    db.commit()
    return _alert_out(alert)


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    alert = db.get(PriceAlert, alert_id)
    if not alert or not db.scalar(select(PriceAlert.id).where(PriceAlert.id == alert_id, _owner_filter(PriceAlert, identity))):
        raise HTTPException(404, "Alert not found")
    alert.active = 0
    db.commit()
    return {"deleted": True}


@router.get("/alerts/notifications")
def notifications(unread_only: bool = False, identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Notification).where(_owner_filter(Notification, identity)).order_by(Notification.id.desc()).limit(50)
    if unread_only:
        q = q.where(Notification.read == 0)
    return [
        {"id": n.id, "title": n.title, "body": n.body, "read": bool(n.read), "created_at": n.created_at.isoformat()}
        for n in db.scalars(q)
    ]


@router.post("/alerts/notifications/read")
def mark_read(identity: Identity = Depends(get_identity), db: Session = Depends(get_db)) -> dict:
    for n in db.scalars(select(Notification).where(_owner_filter(Notification, identity), Notification.read == 0)):
        n.read = 1
    db.commit()
    return {"ok": True}
