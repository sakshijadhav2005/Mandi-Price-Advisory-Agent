"""Weekly watch of official scheme pages: baseline, unchanged, changed (alert), failures."""

import httpx
import pytest
from sqlalchemy import delete

from app.advisory import watch
from app.advisory.watch import check_sources, page_fingerprint, watched_pages
from app.db.models import SourceWatch


@pytest.fixture
def clean(session):
    session.execute(delete(SourceWatch))
    session.commit()
    yield
    session.execute(delete(SourceWatch))
    session.commit()


def serve(monkeypatch, pages: dict[str, str], fail: set[str] = frozenset()):
    def fake_get(url, **kw):
        if url in fail:
            raise httpx.ConnectError("refused", request=httpx.Request("GET", url))
        return httpx.Response(200, text=pages.get(url, "<p>default</p>"), request=httpx.Request("GET", url))

    monkeypatch.setattr(watch.httpx, "get", fake_get)


def test_fingerprint_ignores_scripts_tags_and_numbers():
    a = "<html><script>var t=1</script><p>PM-KISAN pays Rs 6000</p><p>Visitors: 1234</p></html>"
    b = "<html><script>var t=2</script><div>PM-KISAN pays Rs 6000</div><p>Visitors: 98765</p></html>"
    assert page_fingerprint(a) == page_fingerprint(b)
    assert page_fingerprint(a) != page_fingerprint(a.replace("pays", "no longer pays"))


def test_first_run_records_then_alerts_only_on_change(clean, session, monkeypatch):
    pages = watched_pages()
    assert "https://pmkisan.gov.in" in pages and "pm-kisan" in pages["https://pmkisan.gov.in"]
    alerts = []
    serve(monkeypatch, {})
    first = check_sources(session, alert=alerts.append)
    assert first["new"] == len(pages) and alerts == []
    second = check_sources(session, alert=alerts.append)
    assert second["unchanged"] == len(pages) and alerts == []
    serve(monkeypatch, {"https://pmkisan.gov.in": "<p>New eligibility rules from 1 April</p>"}, fail={"https://pmfby.gov.in"})
    third = check_sources(session, alert=alerts.append)
    assert third["changed"] == [{"url": "https://pmkisan.gov.in", "schemes": ["pm-kisan"]}]
    assert third["failed"] == ["https://pmfby.gov.in"]
    assert len(alerts) == 1 and "pm-kisan" in alerts[0]
    assert session.get(SourceWatch, "https://pmfby.gov.in").error
