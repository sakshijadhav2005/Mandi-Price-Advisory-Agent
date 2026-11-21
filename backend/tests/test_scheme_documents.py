"""Scheme documents: state filtering, official link and helpline in answers and sources."""

import pytest
from fastapi.testclient import TestClient

from app.agent.service import answer_query
from app.agent.tools import ToolContext, applies_to_state, run_tool
from app.config import get_settings
from app.main import app
from app.retrieval import index as index_mod

ADMIN = {"X-Admin-Token": "secret"}

CENTRAL = """---
id: central-insurance-en
title: Central crop insurance scheme
crop: all
language: en
state: all
url: https://example.gov.in/insurance
helpline: 14447
---
The crop insurance scheme covers notified crops against drought, flood and hail. Farmers enrol through their bank before the cut-off date.
"""
MAHARASHTRA = """---
id: mh-solar-pump-en
title: Maharashtra solar pump scheme
crop: all
language: en
state: Maharashtra
url: https://example.maharashtra.gov.in/solar
---
The solar pump scheme gives farmers an off-grid solar pump for irrigation. Apply online with your land records.
"""
PUNJAB = """---
id: pb-solar-pump-en
title: Punjab solar pump scheme
crop: all
language: en
state: Punjab
---
The solar pump scheme in Punjab gives farmers a subsidised solar pump for irrigation. Apply through the state agency.
"""


@pytest.fixture
def scheme_docs(tmp_path, monkeypatch):
    for name, text in {"central.md": CENTRAL, "mh.md": MAHARASHTRA, "pb.md": PUNJAB}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(index_mod, "BULLETIN_DIR", tmp_path)
    monkeypatch.setattr(get_settings(), "admin_token", "secret")
    index_mod.rebuild_index()
    yield tmp_path
    monkeypatch.undo()
    index_mod.rebuild_index()


def test_applies_to_state():
    assert applies_to_state({}, "Maharashtra")
    assert applies_to_state({"state": "all"}, "Punjab")
    assert applies_to_state({"state": "Central"}, "Punjab")
    assert applies_to_state({"state": "maharashtra"}, "Maharashtra")
    assert not applies_to_state({"state": "Punjab"}, "Maharashtra")


def test_farmer_only_sees_own_state_documents(scheme_docs, session):
    def titles(district):
        ctx = ToolContext(session=session, as_of=None, district=district)
        result, err = run_tool(ctx, "search_advisories", {"query": "solar pump scheme for irrigation", "crop": None})
        assert not err
        return {h["title"] for h in result["results"]}, result

    nashik, result = titles("nashik")
    assert "Maharashtra solar pump scheme" in nashik and "Punjab solar pump scheme" not in nashik
    mh = next(h for h in result["results"] if h["title"] == "Maharashtra solar pump scheme")
    assert mh["url"] == "https://example.maharashtra.gov.in/solar" and mh["state"] == "Maharashtra"

    amritsar, _ = titles("amritsar")
    assert "Punjab solar pump scheme" in amritsar and "Maharashtra solar pump scheme" not in amritsar


def test_offline_answer_points_to_official_source(scheme_docs, session):
    ans = answer_query(session, "How do I enrol in the crop insurance scheme?", language="en", district="nashik", use_llm=False)
    assert "Central crop insurance scheme" in ans.text
    assert "https://example.gov.in/insurance / 14447" in ans.text
    src = next(s for s in ans.sources if s["kind"] == "advisory" and s["title"] == "Central crop insurance scheme")
    assert src["url"] == "https://example.gov.in/insurance" and src["helpline"] == "14447"


def test_upload_with_state_link_and_helpline(scheme_docs):
    body = "The farm pond scheme pays for digging a farm pond to store rain water for irrigation in dry months."
    with TestClient(app) as c:
        bad = c.post("/admin/documents", headers=ADMIN, files={"file": ("p.txt", body.encode(), "text/plain")}, data={"state": "Atlantis"})
        assert bad.status_code == 422
        bad = c.post("/admin/documents", headers=ADMIN, files={"file": ("p.txt", body.encode(), "text/plain")}, data={"url": "javascript:alert(1)"})
        assert bad.status_code == 422
        r = c.post(
            "/admin/documents",
            headers=ADMIN,
            files={"file": ("pond.txt", body.encode(), "text/plain")},
            data={"title": "Farm pond scheme", "state": "Maharashtra", "url": "https://mahadbt.maharashtra.gov.in", "helpline": "1800-120-8040"},
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert (doc["state"], doc["url"], doc["helpline"]) == ("Maharashtra", "https://mahadbt.maharashtra.gov.in", "1800-120-8040")
