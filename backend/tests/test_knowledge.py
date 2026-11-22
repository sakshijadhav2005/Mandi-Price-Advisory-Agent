"""Storage documents (reviewed) and Kisan Call Centre answers: search, import, answers."""

from datetime import date

import httpx
import pytest
from sqlalchemy import delete, select

from app.advisory import kcc
from app.advisory.documents import DocumentError, add_document, review_document, split_passages
from app.advisory.documents import search as search_documents
from app.advisory.kcc import decode_numbers, import_rows, names_a_chemical, purge_old
from app.advisory.search import BM25, guess_language, stem
from app.agent.service import answer_query
from app.agent.tools import tool_schemas
from app.config import get_settings
from app.db.models import AdvisoryChunk, AdvisoryDocument, KccAnswer

AS_OF = date(2026, 11, 8)

ONION_MR = """# कांदा साठवण

कांदा काढणीनंतर शेतातच तीन ते पाच दिवस सुकवावा आणि मान पूर्ण वाळल्यावरच साठवणुकीसाठी घ्यावा.

## कांदा चाळ

साठवणुकीसाठी हवेशीर कांदा चाळ वापरा. चाळीचा तळ जमिनीपासून उंच ठेवा म्हणजे खालून हवा खेळती राहते आणि कांदा सडत नाही.
"""
ONION_EN = """# Onion storage

Cure the bulbs in the field for three to five days and store only when the neck is fully dry.

## Storage structure

Use a well ventilated onion store with a raised, slatted floor so that air moves through the heap from below and the bulbs do not rot.
"""


@pytest.fixture
def clean(session):
    def wipe():
        session.execute(delete(AdvisoryChunk))
        session.execute(delete(AdvisoryDocument))
        session.execute(delete(KccAnswer))
        session.commit()

    wipe()
    yield
    wipe()


# --- search engine ---------------------------------------------------------------------------


def test_stemming_and_matching_across_languages():
    assert stem("कांद्याची") == stem("कांदा") == stem("कांद्यावर")
    assert stem("onions") == "onion"
    index = BM25([(1, ONION_EN), (2, ONION_MR), (3, "Tomato early blight: remove infected leaves.")])
    assert index.search("कांद्याची साठवण कशी करावी?")[0].key == 2
    assert index.search("how to store onions")[0].key == 1
    assert index.search("onion") == []  # a crop name alone is not a match
    assert guess_language(ONION_MR) == "mr" and guess_language("प्याज को हवादार जगह में रखें, यह जरूरी है") == "hi"


# --- storage documents ---------------------------------------------------------------------------


def test_document_workflow(clean, session, tmp_path):
    path = tmp_path / "onion-storage-mr.md"
    path.write_text(ONION_MR, encoding="utf-8")
    assert [h for h, _ in split_passages(ONION_MR)] == ["कांदा साठवण", "कांदा चाळ"]
    doc = add_document(session, path, title="कांदा साठवण", crop="onion", language="mr", publisher="ICAR-DOGR")
    assert doc.status == "pending"
    assert search_documents(session, "कांदा साठवण कशी करावी?", "onion") == []  # not reviewed yet
    with pytest.raises(DocumentError, match="already added"):
        add_document(session, path, title="again", crop="onion", language="mr", publisher="ICAR-DOGR")
    review_document(session, doc.id, "Dr. Reviewer")
    hits = search_documents(session, "कांदा साठवण कशी करावी?", "onion")
    assert hits and hits[0]["publisher"] == "ICAR-DOGR"
    assert search_documents(session, "कांदा साठवण कशी करावी?", "tomato") == []  # another crop's document
    review_document(session, doc.id, "Dr. Reviewer", approve=False)
    assert search_documents(session, "कांदा साठवण कशी करावी?", "onion") == []


def test_document_checks(clean, session, tmp_path):
    good = tmp_path / "a.md"
    good.write_text(ONION_EN, encoding="utf-8")
    with pytest.raises(DocumentError, match="unknown crop"):
        add_document(session, good, title="t", crop="mango", language="en", publisher="p")
    with pytest.raises(DocumentError, match="https"):
        add_document(session, good, title="t", crop="onion", language="en", publisher="p", url="http://x")
    tiny = tmp_path / "b.txt"
    tiny.write_text("too short", encoding="utf-8")
    with pytest.raises(DocumentError, match="no readable text"):
        add_document(session, tiny, title="t", crop="onion", language="en", publisher="p")
    with pytest.raises(DocumentError):
        review_document(session, 999999, "x")


def test_storage_question_answered_from_reviewed_document(clean, session, tmp_path):
    for name, text, lang in (("mr.md", ONION_MR, "mr"), ("en.md", ONION_EN, "en")):
        (tmp_path / name).write_text(text, encoding="utf-8")
        doc = add_document(session, tmp_path / name, title="Onion storage" if lang == "en" else "कांदा साठवण", crop="onion", language=lang, publisher="ICAR-DOGR", url="https://dogr.icar.gov.in")
        review_document(session, doc.id, "Dr. Reviewer")
    mr = answer_query(session, "कांद्याची साठवण कशी करावी?", language="mr", as_of=AS_OF, use_llm=False)
    assert mr.text.startswith('"कांदा साठवण" (ICAR-DOGR) नुसार:') and "चाळ" in mr.text
    assert any(s["kind"] == "document" for s in mr.sources)
    en = answer_query(session, "How should I store onions so they do not rot?", language="en", as_of=AS_OF, use_llm=False)
    assert en.text.startswith('From "Onion storage" (ICAR-DOGR):')
    # Hindi farmer: no Hindi document, so no English passage either (falls back as before).
    hi = answer_query(session, "प्याज का भंडारण कैसे करें?", language="hi", as_of=AS_OF, use_llm=False)
    assert "ICAR-DOGR" not in hi.text


# --- Kisan Call Centre ----------------------------------------------------------------------------


def row(**kw):
    base = {"StateName": "MAHARASHTRA", "DistrictName": "PUNE", "BlockName": "JUNNAR", "Sector": "HORTICULTURE", "Crop": "Onion",
            "QueryType": "Cultural Practices", "CreatedOn": "2025-06-10T10:00:00",
            "QueryText": "onion bulb size small what to do", "KccAns": "Give irrigation at proper intervals and apply recommended fertilizer doses as per soil test"}
    return base | kw


def test_kcc_cleaning(clean, session):
    rows = [
        row(),
        row(),  # duplicate
        row(DistrictName="NASHIK"),  # other district
        row(CreatedOn="2019-01-01T00:00:00"),  # older than 3 years
        row(QueryType="Weather"),
        row(QueryText="onion thrips", KccAns="Spray fipronil 5 SC 2 ml per litre of water"),  # names a chemical
        row(KccAns="ok"),  # too short
        row(QueryText="tomato leaf curl", Crop="Tomato", KccAns="23502367 remove infected plants early and keep the field clean of weeds"),
    ]
    counts = import_rows(session, rows, AS_OF)
    assert counts == {"read": 8, "stored": 2, "other_district": 1, "old_or_undated": 1, "skipped_type": 1, "names_chemical": 1, "empty": 1, "duplicate": 1}
    stored = session.scalars(select(KccAnswer).order_by(KccAnswer.id)).all()
    assert [r.crop_id for r in stored] == ["onion", "tomato"] and stored[0].district == "pune"
    assert stored[1].answer.startswith("मि remove")  # number-encoded Devanagari decoded
    assert decode_numbers("2350236723602366") == "मिसा"
    assert names_a_chemical("Use hexaconazole") and not names_a_chemical("Apply phosphorus and organic carbon as per soil test")
    assert purge_old(session, date(2029, 1, 1)) == 2


def test_kcc_answer_in_farmers_language(clean, session):
    import_rows(
        session,
        [
            row(QueryText="कांद्याचा आकार लहान राहतो काय करावे", KccAns="कांद्याला वेळेवर पाणी द्यावे आणि माती परीक्षणानुसार खताची मात्रा द्यावी, तण काढावे"),
            row(),
        ],
        AS_OF,
    )
    mr = answer_query(session, "कांद्याचा आकार लहान का राहतो?", language="mr", as_of=AS_OF, use_llm=False, district="pune")
    assert mr.text.startswith("किसान कॉल सेंटरच्या तज्ज्ञांनी पुणे मधील अशाच प्रश्नाचे उत्तर दिले होते (10/6):")
    assert mr.text.endswith("त्यानुसार करण्यापूर्वी आपल्या KVK कडून खात्री करा.")
    assert any(s["kind"] == "kcc" for s in mr.sources)
    en = answer_query(session, "Why is my onion bulb size small?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert "Give irrigation at proper intervals" in en.text
    other = answer_query(session, "Why is my onion bulb size small?", language="en", as_of=AS_OF, use_llm=False, district="nashik")
    assert "Kisan Call Centre" not in other.text  # KCC rows are per district
    sell = answer_query(session, "Should I sell onion now?", language="en", as_of=AS_OF, use_llm=False, district="pune")
    assert sell.text.startswith(("Sell now", "Hold"))


def test_kcc_api_fetch(clean, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "kcc_resource_id", "res-123")
    seen = []

    def fake_get(url, params=None, **kw):
        seen.append((url, params))
        records = [row()] if params["offset"] == 0 else []
        return httpx.Response(200, json={"records": records}, request=httpx.Request("GET", url))

    monkeypatch.setattr(kcc.httpx, "get", fake_get)
    out = kcc.fetch_api(session, AS_OF, page_size=1)
    assert out["stored"] == 1
    assert seen[0][0] == "https://api.data.gov.in/resource/res-123"
    assert seen[0][1]["filters[StateName]"] == "MAHARASHTRA" and seen[0][1]["filters[DistrictName]"] == "PUNE"
    monkeypatch.setattr(get_settings(), "kcc_resource_id", "")
    with pytest.raises(kcc.KccError):
        kcc.fetch_api(session, AS_OF)


def test_tools_offered_to_the_llm():
    names = {t["name"] for t in tool_schemas()}
    assert {"search_storage_advice", "search_farmer_questions"} <= names


def test_search_fixes_found_by_the_storage_preview(clean, session, tmp_path):
    # English stems: cure / curing / cured, store / storing all meet.
    assert stem("cure") == stem("curing") == stem("cured")
    assert stem("store") == stem("storing") == stem("stored")
    # Devanagari words must start a word: "भाजीपाला" (vegetables) is not "पाला" (frost).
    from app.translation.languages import is_advisory_question, is_weather_question

    assert not is_weather_question("भाजीपाला जास्त दिवस ताजा कसा ठेवायचा?")
    assert is_weather_question("पाला पडेल का?") and is_advisory_question("भाजीपाला जास्त दिवस ताजा कसा ठेवायचा?")
    # A crop-specific document beats a general one, and the farmer's language comes first.
    general = tmp_path / "general.md"
    general.write_text("# शीतकक्ष\n\nकांदा व भाजीपाल्याची साठवण शीतकक्षात करावी, दिवसातून दोन वेळा पाणी शिंपडावे आणि भाजीपाला ताजा राहतो.\n" * 3, encoding="utf-8")
    onion = tmp_path / "onion.md"
    onion.write_text(
        "# कांदा साठवण\n\nसुकलेला कांदा 0 °से. साठवण तापमान आणि 65-70% सापेक्ष आर्द्रतेत साठवावा; तो सुमारे 30-240 दिवस टिकतो. "
        "साठवणीपूर्वी कांदा शेतातच तीन ते पाच दिवस सुकवावा आणि मान पूर्ण वाळल्यावरच चाळीत भरावा. खराब, जोड आणि कोंब आलेले कांदे बाजूला काढावेत.\n",
        encoding="utf-8",
    )
    english = tmp_path / "onion-en.md"
    english.write_text(ONION_EN, encoding="utf-8")
    for path, crop, lang in ((general, "all", "mr"), (onion, "onion", "mr"), (english, "onion", "en")):
        doc = add_document(session, path, title=path.stem, crop=crop, language=lang, publisher="p")
        review_document(session, doc.id, "r")
    hits = search_documents(session, "कांद्याची साठवण किती दिवस टिकते?", "onion", language="mr")
    assert hits[0]["title"] == "onion"
    en = search_documents(session, "How do I cure onions before storage?", "onion", language="en")
    assert en[0]["language"] == "en"
