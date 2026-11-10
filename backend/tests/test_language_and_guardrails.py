import pytest

from app.agent.guardrails import language_ok, ungrounded_numbers
from app.reference import detect_crop, detect_market, detect_quantity_qtl
from app.retrieval.index import get_index
from app.translation.glossary import expand_query
from app.translation.languages import load_languages
from app.translation.templates import inr


@pytest.mark.parametrize(
    "text,crop",
    [
        ("Should I sell onion now?", "onion"),
        ("मी कांदा विकू की थांबू?", "onion"),
        ("माझ्या कांद्याला भाव काय?", "onion"),
        ("प्याज़ का भाव क्या है", "onion"),
        ("टमाटर अभी बेचूं?", "tomato"),
        ("टोमॅटो विकायचा आहे", "tomato"),
        ("What about wheat?", None),
    ],
)
def test_detect_crop(text, crop):
    assert detect_crop(text) == crop


def test_detect_quantity_and_market():
    assert detect_quantity_qtl("I have 20 quintal") == 20
    assert detect_quantity_qtl("२० क्विंटल कांदा") == 20
    assert detect_quantity_qtl("2 tonnes") == 20
    assert detect_quantity_qtl("500 kg") == 5
    assert detect_market("rate at Lasalgaon?") == "lasalgaon"
    assert detect_market("पिंपळगाव बसवंत बाजार") == "pimpalgaon"


def test_language_check():
    assert language_ok("Sell now. Confidence high.", "en")
    assert language_ok("आता विका. खात्री: जास्त.", "mr")
    assert not language_ok("Sell now. Confidence high.", "hi")


def test_grounding_allows_tool_numbers_and_rounding():
    outputs = [{"modal_latest": 2715.0, "net_now_per_qtl": 2638.4, "date": "2026-11-07"}]
    assert ungrounded_numbers("Nashik pays ₹2,715, about ₹2,640 net, reported 2026-11-07, hold 7 days.", outputs) == []
    assert ungrounded_numbers("Expect ₹3,100 next week.", outputs) == ["3,100"]
    assert ungrounded_numbers("भाव ₹२,७१५ है", outputs) == []


def test_inr_grouping():
    assert inr(123456) == "1,23,456"
    assert inr(2715) == "2,715"
    assert inr(999) == "999"
    assert inr(12345678) == "1,23,45,678"


def test_templates_have_same_keys_in_every_language():
    packs = load_languages()
    keys = set(packs["en"].templates)
    for code, pack in packs.items():
        assert set(pack.templates) == keys, code
        assert pack.glossary, code


def test_query_expansion_crosses_languages():
    q = expand_query("कांदा साठवण")
    assert "onion" in q and "storage" in q


def test_hybrid_retrieval_finds_storage_advice_across_languages():
    idx = get_index()
    en = idx.search("how to store onions to avoid rot", crop="onion", language="en")
    assert en and en[0]["crop"] == "onion"
    mr = idx.search("कांदा साठवण चाळ", crop="onion", language="mr")
    assert mr[0]["language"] == "mr"
    tomato = idx.search("crates transport bruising", crop="tomato")
    assert all(h["crop"] in ("tomato", "all") for h in tomato)
