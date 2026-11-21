"""Weekly district advice from the IMD agromet bulletin: parse, download, expire, delete, answer."""

from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, select

from app.advisory import agromet
from app.advisory.agromet import AgrometError, current_bulletin, fetch_all, fetch_bulletin, parse_bulletin, purge_old_bulletins
from app.agent.service import answer_query
from app.agent.tools import tool_schemas
from app.config import get_settings
from app.db.models import AgrometBulletin
from app.translation.languages import is_weather_question

AS_OF = date(2026, 11, 8)  # tests/conftest.py: AS_OF_OVERRIDE


def bulletin_text(issued: str = "06.11.2026", days: str = "07 08 09 10 11", rain: str = "0.0 0.0 0.0 0.0 0.0") -> str:
    """Same layout as a real IMD district bulletin (text as pypdf extracts it)."""
    return f"""AGROMET ADVISORY BULLETIN
GRAMIN KRISHI MAUSAM SEWA, AMFU, PUNE
Weather based Agromet Advisory committee meeting dated {issued}
District : Pune
Weather Forecast
30 31 01 02 03 04 05 Date {days}
0.0 0.0 0.0 0.0 0.0 0.0 0.0 Rainfall (mm) {rain}
32.0 31.8 30.8 31.5 31.7 30.8 30.8 Max. Temp. (0C) 31 33 33 34 33
13.9 12.1 13.5 13.9 14.1 14.0 11.1 Min. Temp. (0C) 13 14 16 16 16
Agromet Advisory Based on Weather Forecast Prediction
Weather Summary/ Alert According to forecast given by Regional Meteorological Centre, Mumbai,
the weather may remain dry in the district.
Extended Range Forecast
(ERFS)
Rainfall may remain below normal.
General Advisory  Harvested produce should be stored in a safe place.
 In the district's rain-fed or irrigated areas, the sowing of Rabi crops such as
chickpea (gram), wheat, rajma bean & rabi sorghum should be planned
only if protective irrigation is available during the crops critical growth
stages.
Kharif
Paddy
Maturity to
harvest Stage
Drain the water from the field 10 days before harvesting.
Brinjal

Vegetative
Growth Stage
For control of sap-sucking pests, spray flonicamid 50% WG, 4 gm per 10 liters of water.
Onion Vegetative
Growth Stage
To control aphids, spray i midacloprid 17.8 SL 3 ml per 10 liters of water.
Pomegranat
e
Vegetative
stage
Irrigation water should be used judiciously.
Note: Farmers should take precautionary measures while spraying.
Date : {issued}
"""


@pytest.fixture
def agromet_env(tmp_path, monkeypatch, session):
    monkeypatch.setattr(get_settings(), "agromet_dir", str(tmp_path / "agromet"))
    monkeypatch.setattr(get_settings(), "agromet_districts", "pune")
    session.execute(delete(AgrometBulletin))
    session.commit()
    yield tmp_path
    session.execute(delete(AgrometBulletin))
    session.commit()


def serve(monkeypatch, responses):
    """Fake IMD: each download returns the next (status, body) and pdf_text the matching text."""
    calls = []

    def fake_get(url, **kw):
        status, body, text = responses[min(len(calls), len(responses) - 1)]
        calls.append(url)
        monkeypatch.setattr(agromet, "pdf_text", lambda _data: text)
        return httpx.Response(status, content=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(agromet.httpx, "get", fake_get)
    monkeypatch.setattr(agromet, "RETRY_BACKOFF_S", 0)
    return calls


# --- parsing -------------------------------------------------------------------------


def test_parse_dates_forecast_sections_and_crops():
    p = parse_bulletin(bulletin_text())
    assert p.issued_on == date(2026, 11, 6)
    assert p.valid_until == date(2026, 11, 11)  # last forecast day
    assert [f["date"] for f in p.forecast] == ["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
    assert p.forecast[0] == {"date": "2026-11-07", "rain_mm": 0.0, "tmax_c": 31.0, "tmin_c": 13.0}
    assert "remain dry" in p.sections["weather_summary"]
    assert p.sections["extended_range"] == "Rainfall may remain below normal."
    # A sentence starting with "chickpea" is not a heading: the general advice continues past it.
    assert "protective irrigation" in p.sections["general"] and "•" in p.sections["general"]
    assert set(p.crops) == {"brinjal", "onion"}  # paddy and pomegranate are not app crops
    assert p.crops["onion"].startswith("Vegetative Growth Stage To control aphids")
    assert "Irrigation water" not in p.crops["onion"]  # the wrapped "Pomegranat/e" heading ends it
    assert "flonicamid" in p.crops["brinjal"]
    assert "spray imidacloprid 17.8 SL" in p.crops["onion"]  # word split by the PDF is re-joined


def test_forecast_days_roll_into_next_month_and_validity_is_capped():
    p = parse_bulletin(bulletin_text(issued="29.11.2026", days="30 01 02 03 04"))
    assert [f["date"] for f in p.forecast] == ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04"]
    no_table = parse_bulletin("Agromet Advisory committee meeting dated 06.11.2026\n" + "word " * 60)
    assert no_table.forecast == [] and no_table.valid_until == date(2026, 11, 10)


def test_bulletin_without_issue_date_is_rejected():
    with pytest.raises(AgrometError):
        parse_bulletin("AGROMET ADVISORY BULLETIN with no date at all " * 5)


def test_weather_questions_are_recognised():
    assert is_weather_question("Will it rain this week?")
    assert is_weather_question("कांद्यावर फवारणी कधी करू?")
    assert is_weather_question("क्या इस हफ्ते बारिश होगी?")
    assert not is_weather_question("Should I sell wheat grain?")  # no "heat" / "rain" inside words
    assert not is_weather_question("मी कांदा आता विकू की थांबू?")


# --- download, check, store, expire, delete -----------------------------------------------


def test_fetch_stores_then_skips_unchanged(agromet_env, monkeypatch, session):
    pdf = b"%PDF-1.4 bulletin one"
    calls = serve(monkeypatch, [(200, pdf, bulletin_text())])
    first = fetch_bulletin(session, "pune")
    assert first["status"] == "stored" and first["crops"] == ["brinjal", "onion"]
    assert calls[0].endswith("/english-pdf/Pune.pdf")
    row = session.scalar(select(AgrometBulletin))
    assert row.status == "active" and row.valid_until == date(2026, 11, 11)
    assert (agromet_env / "agromet" / "pune").exists() and open(row.file_path, "rb").read() == pdf
    assert fetch_bulletin(session, "pune")["status"] == "unchanged"
    assert session.scalars(select(AgrometBulletin)).all() == [row]


def test_new_issue_supersedes_old_and_older_issue_is_ignored(agromet_env, monkeypatch, session):
    serve(monkeypatch, [(200, b"%PDF-1.4 old", bulletin_text(issued="03.11.2026", days="04 05 06 07 08"))])
    fetch_bulletin(session, "pune")
    serve(monkeypatch, [(200, b"%PDF-1.4 new", bulletin_text())])
    fetch_bulletin(session, "pune")
    statuses = {b.issued_on: b.status for b in session.scalars(select(AgrometBulletin))}
    assert statuses == {date(2026, 11, 3): "superseded", date(2026, 11, 6): "active"}
    serve(monkeypatch, [(200, b"%PDF-1.4 stale copy", bulletin_text(issued="01.11.2026", days="02 03 04 05 06"))])
    assert fetch_bulletin(session, "pune")["status"] == "older_than_stored"


def test_bad_downloads_are_rejected(agromet_env, monkeypatch, session):
    serve(monkeypatch, [(200, b"<html>maintenance</html>", "")])
    with pytest.raises(AgrometError, match="not a PDF"):
        fetch_bulletin(session, "pune")
    serve(monkeypatch, [(200, b"%PDF-1.4 scanned", "too short")])
    with pytest.raises(AgrometError, match="no readable text"):
        fetch_bulletin(session, "pune")
    serve(monkeypatch, [(404, b"not found", "")])
    with pytest.raises(httpx.HTTPStatusError):
        fetch_bulletin(session, "pune")
    assert session.scalars(select(AgrometBulletin)).all() == []


def test_fetch_all_reports_failure_and_alerts_ops(agromet_env, monkeypatch, session):
    alerts = []
    monkeypatch.setattr("app.ops.ops_alert", lambda text: alerts.append(text) or True)
    serve(monkeypatch, [(503, b"down", "")])
    [result] = fetch_all(session, AS_OF)
    assert result["status"] == "error" and result["stale"] is True
    assert alerts and "pune" in alerts[0]


def test_only_a_valid_active_bulletin_is_used(agromet_env, monkeypatch, session):
    serve(monkeypatch, [(200, b"%PDF-1.4 x", bulletin_text())])
    fetch_bulletin(session, "pune")
    assert current_bulletin(session, "pune", date(2026, 11, 11)) is not None
    assert current_bulletin(session, "pune", date(2026, 11, 12)) is None  # expired
    assert current_bulletin(session, "pune", date(2026, 11, 5)) is None  # not issued yet
    assert current_bulletin(session, "nashik", AS_OF) is None


def test_old_bulletins_and_pdfs_are_deleted(agromet_env, monkeypatch, session):
    serve(monkeypatch, [(200, b"%PDF-1.4 x", bulletin_text())])
    fetch_bulletin(session, "pune")
    row = session.scalar(select(AgrometBulletin))
    path = row.file_path
    assert purge_old_bulletins(session, date(2026, 12, 6)) == 0  # 30 days not yet over
    assert purge_old_bulletins(session, date(2026, 12, 7)) == 1
    assert session.scalars(select(AgrometBulletin)).all() == []
    assert not Path(path).exists()


def test_delete_never_touches_files_outside_the_agromet_folder(agromet_env, monkeypatch, session):
    outside = agromet_env / "important.txt"
    outside.write_text("keep me")
    session.add(
        AgrometBulletin(
            district="pune", issued_on=date(2026, 1, 1), valid_until=date(2026, 1, 5), status="superseded",
            sha256="f" * 64, source_url="https://example", file_path=str(outside), data={},
        )
    )
    session.commit()
    assert purge_old_bulletins(session, AS_OF) == 1
    assert outside.read_text() == "keep me"


# --- answers -------------------------------------------------------------------------------


def stored(monkeypatch, session, rain="0.0 0.0 0.0 0.0 0.0"):
    serve(monkeypatch, [(200, b"%PDF-1.4 " + rain.encode(), bulletin_text(rain=rain))])
    fetch_bulletin(session, "pune")


def test_weather_question_offline_in_marathi_and_english(agromet_env, monkeypatch, session):
    stored(monkeypatch, session)
    mr = answer_query(session, "या आठवड्यात पाऊस येणार आहे का?", language="mr", as_of=AS_OF, use_llm=False, district="pune")
    assert mr.text.startswith("पुणे साठी IMD कृषी हवामान सल्ला, दिनांक 6/11 (11/11 पर्यंत लागू).")
    assert "पुढील 5 दिवसांत पावसाची शक्यता नाही." in mr.text and "31–34°C" in mr.text
    assert "imidacloprid" not in mr.text  # English advice text is not shown to a Marathi farmer offline
    assert any(s["kind"] == "agromet" and s["issued_on"] == "2026-11-06" for s in mr.sources)

    en = answer_query(session, "When should I spray my onion?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert "Advice for Onion: Vegetative Growth Stage To control aphids" in en.text
    assert "https://mausam.imd.gov.in" in en.text


def test_no_valid_bulletin_or_other_district_says_so(agromet_env, session):
    pune = answer_query(session, "Will it rain this week?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert pune.text.startswith("There is no current IMD district advisory for Pune.")
    nashik = answer_query(session, "पाऊस येणार आहे का?", language="mr", as_of=AS_OF, use_llm=False, district="nashik")
    assert "नाशिक साठी सध्या लागू असलेला IMD जिल्हा सल्ला उपलब्ध नाही" in nashik.text


def test_sell_or_hold_answer_warns_about_forecast_rain(agromet_env, monkeypatch, session):
    stored(monkeypatch, session, rain="0.0 12.5 4.0 0.0 0.0")
    ans = answer_query(session, "Should I sell onion now?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert ans.decision in ("sell", "hold")
    assert "IMD forecast: rain on 8/11, 9/11." in ans.text
    assert any(s["kind"] == "agromet" for s in ans.sources)
    dry_district = answer_query(session, "Should I sell onion now?", language="en", as_of=AS_OF, use_llm=False, district="nashik")
    assert "IMD forecast" not in dry_district.text


def test_tool_is_offered_to_the_llm():
    names = {t["name"] for t in tool_schemas()}
    assert "get_district_advisory" in names
