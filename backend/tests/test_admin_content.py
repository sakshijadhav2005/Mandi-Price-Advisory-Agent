"""Admin: advisory content status and storage-document upload / review."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import AdvisoryChunk, AdvisoryDocument
from app.main import app

ADMIN = {"X-Admin-Token": "secret"}
DOC = """# Onion storage

Cure the bulbs in the field for three to five days and store only when the neck is fully dry.

Use a well ventilated onion store with a raised, slatted floor so that air moves through the heap from below.
"""


@pytest.fixture
def admin(monkeypatch, session):
    monkeypatch.setattr(get_settings(), "admin_token", "secret")
    session.execute(delete(AdvisoryChunk))
    session.execute(delete(AdvisoryDocument))
    session.commit()
    with TestClient(app) as c:
        yield c
    session.execute(delete(AdvisoryChunk))
    session.execute(delete(AdvisoryDocument))
    session.commit()


def upload(c, **fields):
    data = {"title": "Onion storage", "crop": "onion", "language": "en", "publisher": "ICAR-DOGR"} | fields
    return c.post("/admin/documents", headers=ADMIN, files={"file": ("onion.md", DOC.encode(), "text/markdown")}, data=data)


def test_needs_the_admin_token(admin):
    assert admin.get("/admin/content").status_code == 401
    assert admin.get("/admin/documents").status_code == 401
    assert admin.get("/admin/content", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert admin.post("/admin/documents", files={"file": ("a.md", DOC.encode())}, data={"title": "t", "language": "en", "publisher": "p"}).status_code == 401


def test_upload_review_and_status(admin):
    r = upload(admin)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "pending" and doc["passages"] >= 1 and doc["publisher"] == "ICAR-DOGR"
    assert upload(admin).status_code == 422  # same file again
    assert upload(admin, crop="mango").status_code == 422
    listed = admin.get("/admin/documents", headers=ADMIN).json()
    assert [d["id"] for d in listed] == [doc["id"]]
    assert admin.post(f"/admin/documents/{doc['id']}/approve", headers=ADMIN, data={"reviewer": " "}).status_code == 422
    ok = admin.post(f"/admin/documents/{doc['id']}/approve", headers=ADMIN, data={"reviewer": "Dr. Reviewer"}).json()
    assert ok == {"id": doc["id"], "status": "approved", "reviewed_by": "Dr. Reviewer"}
    assert admin.post("/admin/documents/999999/approve", headers=ADMIN, data={"reviewer": "x"}).status_code == 404
    assert admin.post(f"/admin/documents/{doc['id']}/delete", headers=ADMIN, data={"reviewer": "x"}).status_code == 404
    status = admin.get("/admin/content", headers=ADMIN).json()
    assert status["documents"] == {"approved": 1}
    assert status["schemes"]["total"] >= 8 and any("not reviewed" in x for x in status["schemes"]["needs_attention"])
    assert set(status) == {"pesticide_rows", "documents", "kcc_answers", "schemes", "agromet"}
