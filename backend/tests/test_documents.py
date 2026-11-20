"""Admin document upload: stored, indexed right away, answered from, deletable."""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.retrieval import index as index_mod

ADMIN = {"X-Admin-Token": "secret"}
GUEST = {"X-Guest-Id": "doc-tester"}

SCHEME = """PM-KISAN pays eligible farmer families an income support of 6000 rupees a year
in three equal instalments. To register, visit the nearest Common Service Centre with your
Aadhaar card, land records and bank passbook. Check your payment status on the PM-KISAN portal
using your Aadhaar or mobile number."""


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    for f in index_mod.BULLETIN_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(index_mod, "BULLETIN_DIR", tmp_path)
    monkeypatch.setattr(get_settings(), "admin_token", "secret")
    index_mod.rebuild_index()
    yield tmp_path
    monkeypatch.undo()
    index_mod.rebuild_index()


def test_upload_answer_delete(docs_dir):
    with TestClient(app) as c:
        assert c.get("/admin/documents").status_code == 401
        built_in = c.get("/admin/documents", headers=ADMIN).json()
        assert built_in and not any(d["deletable"] for d in built_in)

        r = c.post(
            "/admin/documents",
            headers=ADMIN,
            files={"file": ("pm-kisan.txt", SCHEME.encode(), "text/plain")},
            data={"title": "PM-KISAN income support", "crop": "all", "language": "en", "source": "Ministry of Agriculture"},
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc["deletable"] and doc["chunks"] >= 1
        assert (docs_dir / f"{doc['id']}.md").exists()

        ans = c.post("/chat", json={"message": "How do I register for PM-KISAN?", "language": "en"}, headers=GUEST).json()
        assert "Common Service Centre" in ans["text"]
        assert any(s.get("title") == "PM-KISAN income support" for s in ans["sources"])

        assert c.delete(f"/admin/documents/{built_in[0]['id']}", headers=ADMIN).status_code == 409
        assert c.delete(f"/admin/documents/{doc['id']}", headers=ADMIN).json() == {"deleted": True}
        assert not (docs_dir / f"{doc['id']}.md").exists()
        ans = c.post("/chat", json={"message": "How do I register for PM-KISAN?", "language": "en"}, headers=GUEST).json()
        assert "Common Service Centre" not in ans["text"]


def test_upload_rejects_bad_files(docs_dir):
    with TestClient(app) as c:
        def up(name, data, **form):
            return c.post("/admin/documents", headers=ADMIN, files={"file": (name, data)}, data=form)

        assert up("x.exe", b"MZ...").status_code == 422
        assert up("empty.txt", b"").status_code == 422
        assert up("notes.txt", SCHEME.encode(), crop="mango").status_code == 422
        assert up("notes.txt", SCHEME.encode(), language="fr").status_code == 422
        assert up("scan.pdf", b"%PDF-1.4 not really").status_code == 422
