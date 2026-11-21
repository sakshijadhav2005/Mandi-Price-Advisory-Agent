"""Safe spraying: CIB&RC list import, review/approval, and waiting-period answers."""

import csv
import sys
import types
from datetime import date

import httpx
import pytest
from sqlalchemy import delete, select

from app.advisory import pesticides
from app.advisory.pesticides import (
    PesticideError,
    approve_from_csv,
    base_name,
    check_for_newer_list,
    crops_in,
    find_uses,
    import_lists,
)
from app.agent.service import answer_query
from app.agent.tools import tool_schemas
from app.db.models import PesticideUse
from app.translation.languages import days_since_spray, is_pesticide_question

AS_OF = date(2026, 11, 8)

HEADER = [
    ["1. Fungicides single product", "", "", "", "", "", ""],
    ["Crop", "Common name of the disease", "Dosage per ha", "", "", "", "Waiting period from last application to harvest (in days)"],
    ["", "", "a. i. (g)", "Formulation (g/ml)/%", "Dilution in water(L)", "", ""],
]
PAGE_1 = HEADER + [
    ["Mancozeb 75% WP", "", "", "", "", "", ""],
    ["Tomato", "Early blight", "1500", "2000", "750", "", "03"],
    ["", "Late blight", "1500", "2000", "", "750", "5"],  # spacer column moves the dilution
    ["Potato", "Late blight", "1500", "2000", "750", "", "Nil"],
    ["Wheat", "Rust", "1500", "2000", "750", "", "10"],  # not an app crop
    ["Azoxystrobin 23% SC", "", "", "", "", "", ""],
    ["Chilli", "Fruit rot", "125gm", "500 ml", "500-750", "", "500"],  # implausible
]
PAGE_2 = [  # continuation table, no header
    ["Onion", "Purple blotch", "- -", "0.005% 0.05%", "", "750 750", "15"],  # two values in a cell
    ["Cabbage & Cauliflower", "Downy mildew", "125", "500", "500", "", "3 days"],
]


class FakePage:
    def __init__(self, tables, text=""):
        self._tables, self._text = tables, text

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_pdfplumber(monkeypatch):
    pages = [FakePage([PAGE_1], "MAJOR USES OF PESTICIDES (as on 30.09.2026)"), FakePage([PAGE_2])]
    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=lambda path: FakePdf(pages)))


@pytest.fixture
def clean(session):
    session.execute(delete(PesticideUse))
    session.commit()
    yield
    session.execute(delete(PesticideUse))
    session.commit()


def imported(session, tmp_path):
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "cibrc-fungicides-2026-09-30.pdf").write_bytes(b"%PDF-1.4")
    out = import_lists(session, tmp_path / "lists", tmp_path / "review.csv")
    return out, list(csv.DictReader(open(tmp_path / "review.csv", encoding="utf-8-sig")))


def approve(session, tmp_path, rows, decide):
    for r in rows:
        r["approve"] = decide(r)
    path = tmp_path / "reviewed.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=pesticides.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return approve_from_csv(session, path, "Dr. Test Agronomist")


# --- reading the lists ----------------------------------------------------------------------


def test_helpers():
    names = pesticides._crop_names()
    assert crops_in("Tomato", names) == ["tomato"]
    assert crops_in("Cabbage & Cauliflower", names) == ["cabbage", "cauliflower"]
    assert crops_in("Paddy(Rice)", names) == []
    assert base_name("Mancozeb 75% WP") == "mancozeb"
    assert base_name("(Streptomycin Sulphate 9% + Tetracycline 1%) SP") == "streptomycin sulphate"
    assert pesticides._waiting("03") == (3, None)
    assert pesticides._waiting("10days") == (10, None)
    assert pesticides._waiting("Nil") == (0, None)
    assert pesticides._waiting("-") == (None, None)
    assert pesticides._waiting("500")[1] == "implausible waiting period"
    assert "not a single number" in pesticides._waiting("see label")[1]


def test_import_reads_waiting_period_from_last_column(fake_pdfplumber, clean, session, tmp_path):
    out, rows = imported(session, tmp_path)
    assert out["list_dates"] == ["2026-09-30"] and out["rows"] == 7  # wheat skipped; cabbage & cauliflower -> 2
    by = {(r["crop"], r["pest"]): r for r in rows}
    early = by[("Tomato", "Early blight")]
    assert (early["dose_ai_per_ha"], early["dose_formulation_per_ha"], early["dilution_l_per_ha"], early["waiting_days"]) == ("1500", "2000", "750", "3")
    assert by[("Tomato", "Late blight")]["dilution_l_per_ha"] == "750"  # found past the spacer column
    assert by[("Tomato", "Late blight")]["chemical"] == "Mancozeb 75% WP"  # crop carried to the next row
    assert by[("Potato", "Late blight")]["waiting_days"] == "0"  # Nil
    assert by[("Green Chilli", "Fruit rot")]["flag"] == "implausible waiting period"
    assert by[("Onion", "Purple blotch")]["flag"].startswith("several values")  # continuation table
    assert by[("Cauliflower", "Downy mildew")]["waiting_days"] == "3"
    assert all(r["approve"] == "" for r in rows)
    assert {r.status for r in session.scalars(select(PesticideUse))} == {"pending"}


def test_reimport_replaces_pending_rows(fake_pdfplumber, clean, session, tmp_path):
    imported(session, tmp_path)
    (tmp_path / "review.csv").unlink()
    import_lists(session, tmp_path / "lists", tmp_path / "review.csv")
    assert len(session.scalars(select(PesticideUse)).all()) == 7


# --- review and approval ----------------------------------------------------------------------


def test_only_approved_rows_are_used(fake_pdfplumber, clean, session, tmp_path):
    _, rows = imported(session, tmp_path)
    assert find_uses(session, "tomato") == (None, [])  # nothing approved yet
    counts = approve(session, tmp_path, rows, lambda r: "yes" if r["crop"] == "Tomato" else ("no" if r["crop"] == "Onion" else ""))
    assert counts == {"approved": 2, "rejected": 1, "unchanged": 4}
    list_date, uses = find_uses(session, "tomato", chemical="mancozeb")
    assert list_date == date(2026, 9, 30) and [u.waiting_days for u in uses] == [3, 5]
    assert all(u.reviewed_by == "Dr. Test Agronomist" for u in uses)
    assert find_uses(session, "onion")[1] == []  # rejected
    assert find_uses(session, "potato")[1] == []  # still pending


def test_reviewer_can_correct_a_value_and_bad_input_is_refused(fake_pdfplumber, clean, session, tmp_path):
    _, rows = imported(session, tmp_path)
    chilli = [r for r in rows if r["crop"] == "Green Chilli"]
    chilli[0]["waiting_days"] = "5"  # the reviewer fixes the implausible 500
    approve(session, tmp_path, chilli, lambda r: "yes")
    assert find_uses(session, "green_chilli")[1][0].waiting_days == 5
    chilli[0]["waiting_days"] = "five"
    with pytest.raises(PesticideError):
        approve(session, tmp_path, chilli, lambda r: "yes")
    with pytest.raises(PesticideError):
        approve_from_csv(session, tmp_path / "reviewed.csv", "  ")


def test_newer_list_check(monkeypatch, clean, session):
    page = "<a>Fungicide MUP as on 30.09.2026.pdf</a> <a>Herbicides as on 31.03.2027</a>"
    monkeypatch.setattr(pesticides.httpx, "get", lambda url, **kw: httpx.Response(200, text=page, request=httpx.Request("GET", url)))
    assert check_for_newer_list(session) == {"published": "2027-03-31", "stored": None, "newer": True}


# --- answers ------------------------------------------------------------------------------------


def test_question_detection():
    assert is_pesticide_question("टोमॅटोवर फवारणीनंतर किती दिवसांनी काढणी करू?")
    assert is_pesticide_question("What is the waiting period after spraying?")
    assert not is_pesticide_question("Should I sell tomato now?")
    assert days_since_spray("I sprayed 3 days ago") == 3
    assert days_since_spray("मी ४ दिवसांपूर्वी फवारले") == 4


def test_offline_answers(fake_pdfplumber, clean, session, tmp_path):
    none = answer_query(session, "How many days after spraying can I harvest tomato?", language="en", as_of=AS_OF, use_llm=False)
    assert none.text.startswith("I don't have a reviewed pesticide list yet.")

    _, rows = imported(session, tmp_path)
    approve(session, tmp_path, rows, lambda r: "yes" if r["crop"] in ("Tomato", "Potato") else "")

    ans = answer_query(session, "I sprayed mancozeb on tomato 2 days ago. When can I harvest?", language="en", as_of=AS_OF, use_llm=False)
    assert ans.text.startswith("Mancozeb 75% WP on Tomato: wait at least 5 days after the last spray")  # longest of 3 and 5
    assert "wait 3 more days, then harvest and sell from 11/11." in ans.text
    assert ans.text.endswith("wear protective clothing while spraying.")
    assert any(s["kind"] == "pesticide" and s["list_date"] == "2026-09-30" for s in ans.sources)

    over = answer_query(session, "mancozeb on tomato 9 days ago, can I harvest?", language="en", as_of=AS_OF, use_llm=False)
    assert "the waiting period is over" in over.text

    potato = answer_query(session, "बटाट्यावर mancozeb फवारणीनंतर किती दिवसांनी काढणी करू?", language="mr", as_of=AS_OF, use_llm=False)
    assert potato.text.startswith("बटाटा वर Mancozeb 75% WP: शेवटच्या फवारणीनंतर काढणीपूर्वी किमान 0 दिवस थांबा")
    assert "Late blight साठी प्रमाण: प्रति हेक्टर 750 लिटर पाण्यात 2000 औषध." in potato.text

    ask = answer_query(session, "What is the waiting period for tomato after spraying?", language="en", as_of=AS_OF, use_llm=False)
    assert ask.text.startswith("Tell me the name of the chemical you sprayed on Tomato (for example mancozeb)")

    which = answer_query(session, "How many days after spraying can I harvest?", language="en", as_of=AS_OF, use_llm=False)
    assert which.text.startswith("Which crop did you spray?")

    unlisted = answer_query(session, "I sprayed mancozeb on onion, when can I harvest?", language="en", as_of=AS_OF, use_llm=False)
    assert unlisted.text.startswith("mancozeb is not listed for Onion in the official CIB&RC list (30/9).")


def test_several_products_are_never_mixed(clean, session):
    for chemical, days in (("Mancozeb 75% WP", None), ("Mancozeb 40% + Azoxystrobin 7% OS", 5), ("Mancozeb 69.7% + Cyazofamid 5.3% WG", 7)):
        session.add(
            PesticideUse(
                list_kind="fungicides", list_date=date(2026, 9, 30), chemical=chemical, crop_id="tomato", pest="Late blight",
                dose_formulation_per_ha="1500", dilution_l_per_ha="500", waiting_days=days, source_file="x.pdf", page=1, status="approved",
            )
        )
    session.commit()
    ans = answer_query(session, "I sprayed mancozeb on tomato 3 days ago", language="en", as_of=AS_OF, use_llm=False)
    assert ans.text.startswith(
        "Several approved products for Tomato contain mancozeb: Mancozeb 40% + Azoxystrobin 7% OS: 5 days; "
        "Mancozeb 69.7% + Cyazofamid 5.3% WG: 7 days; Mancozeb 75% WP: not stated (official CIB&RC list, 30/9)."
    )
    assert "If you are not sure which one you used, wait 7 days after the last spray." in ans.text
    assert "wait 4 more days, then harvest and sell from 12/11." in ans.text
    assert "Dose for" not in ans.text  # no single dose when the product is unclear


def test_tool_is_offered_to_the_llm():
    assert "lookup_pesticide" in {t["name"] for t in tool_schemas()}
