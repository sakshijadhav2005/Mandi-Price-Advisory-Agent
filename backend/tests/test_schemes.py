"""Government schemes: entry validation, detection, rule-based eligibility, answers."""

import json
import shutil
from datetime import date

import pytest

from app.advisory import schemes as schemes_mod
from app.advisory.schemes import SchemeError, check_eligibility, detect_scheme, load_schemes, problems_report, schemes_for_state
from app.agent.service import answer_query
from app.agent.tools import ToolContext, run_tool, tool_schemas

AS_OF = date(2026, 11, 22)


# --- the shipped entries ---------------------------------------------------------------------


def test_every_entry_is_valid_in_three_languages():
    entries = load_schemes()
    assert {"pm-kisan", "namo-shetkari", "pmfby", "kcc", "micro-irrigation", "soil-health-card", "magel-tyala-saur-pump", "e-nam"} <= set(entries)
    for s in entries.values():
        assert set(s.names) == {"en", "hi", "mr"} and s.url.startswith("https://") and s.helpline
        for lang in ("en", "hi", "mr"):
            assert s.texts(lang)["benefit"] and s.texts(lang)["apply"]
        assert s.review_status in ("draft", "reviewed")


def test_state_filter():
    maharashtra = {s.id for s in schemes_for_state("Maharashtra")}
    punjab = {s.id for s in schemes_for_state("Punjab")}
    assert {"namo-shetkari", "magel-tyala-saur-pump"} <= maharashtra
    assert "namo-shetkari" not in punjab and "pm-kisan" in punjab


@pytest.mark.parametrize(
    "question,scheme",
    [
        ("PM Kisan cha hafta kadhi yeil?", "pm-kisan"),
        ("पीएम किसानचा हप्ता कधी येईल?", "pm-kisan"),
        ("किसान सम्मान निधि की किस्त", "pm-kisan"),
        ("कांद्याचा पीक विमा कसा काढायचा?", "pmfby"),
        ("crop insurance for tomato", "pmfby"),
        ("किसान क्रेडिट कार्ड कैसे बनवाएं", "kcc"),
        ("मागेल त्याला सौर पंप", "magel-tyala-saur-pump"),
        ("drip subsidy", "micro-irrigation"),
        ("नमो शेतकरी योजना", "namo-shetkari"),
        ("dripping tap", None),
        ("Should I sell onion now?", None),
    ],
)
def test_detect_scheme(question, scheme):
    found = detect_scheme(question)
    assert (found.id if found else None) == scheme


def test_eligibility_rules():
    pm = load_schemes()["pm-kisan"]
    assert check_eligibility(pm, {}, "en")["verdict"] == "depends"
    out = check_eligibility(pm, {"owns_land": True, "income_tax_payer": True}, "en")
    assert out["verdict"] == "not_eligible" and out["reasons"] == ["families that paid income tax last year are excluded"]
    all_clear = {"owns_land": True, "income_tax_payer": False, "govt_employee": False, "pension_10k": False, "professional": False, "public_office": False}
    assert check_eligibility(pm, all_clear, "en")["verdict"] == "eligible"
    no_land = check_eligibility(pm, {"owns_land": False}, "mr")
    assert no_land["verdict"] == "not_eligible" and no_land["reasons"] == ["यासाठी कुटुंबाच्या नावावर नोंदलेली शेतजमीन हवी"]
    assert check_eligibility(load_schemes()["soil-health-card"], {}, "en")["verdict"] == "open"


def test_unreviewed_and_old_entries_are_reported():
    report = problems_report(AS_OF)
    assert any(line.startswith("pm-kisan: not reviewed yet") for line in report)
    assert any("older than" in line for line in problems_report(date(2027, 9, 1)))


# --- validation of broken files ---------------------------------------------------------------


@pytest.fixture
def scheme_dir(tmp_path):
    shutil.copy(schemes_mod.SCHEME_DIR / "_facts.json", tmp_path / "_facts.json")
    good = json.loads((schemes_mod.SCHEME_DIR / "kcc.json").read_text(encoding="utf-8"))
    yield tmp_path, good
    schemes_mod.load_schemes.cache_clear()
    schemes_mod.load_facts.cache_clear()


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda d: d["text"].pop("mr"), "text.mr missing"),
        (lambda d: d.update(url="http://insecure.example"), "url must start with https://"),
        (lambda d: d.update(state="Atlantis"), "unknown state"),
        (lambda d: d["eligibility"].append({"fact": "owns_cow", "must_be": True}), "unknown fact"),
        (lambda d: d.update(review_status="reviewed"), "needs reviewed_by"),
        (lambda d: d.update(info_as_of="last week"), "info_as_of must be YYYY-MM-DD"),
    ],
)
def test_broken_entries_are_rejected(scheme_dir, change, message):
    folder, entry = scheme_dir
    change(entry)
    (folder / "kcc.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SchemeError, match=message):
        load_schemes(folder)


def test_file_name_must_match_id(scheme_dir):
    folder, entry = scheme_dir
    (folder / "credit-card.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SchemeError, match="must match the file name"):
        load_schemes(folder)


# --- answers ---------------------------------------------------------------------------------


def ask(session, question, lang="mr", district="pune"):
    return answer_query(session, question, language=lang, as_of=AS_OF, use_llm=False, district=district)


def test_scheme_answer_in_marathi(session):
    ans = ask(session, "पीएम किसानचा हप्ता कसा मिळतो?")
    assert ans.text.startswith("पीएम-किसान: जमीन असलेल्या शेतकरी कुटुंबांना वर्षाला ₹6,000")
    assert "अधिकृत संकेतस्थळ https://pmkisan.gov.in, हेल्पलाइन 155261" in ans.text
    assert "अजून कोणत्याही अधिकाऱ्याने पडताळलेली नाही" in ans.text  # draft entry
    assert [s["kind"] for s in ans.sources] == ["scheme"] and ans.sources[0]["review_status"] == "draft"


def test_eligibility_question_lists_the_deciding_questions(session):
    ans = ask(session, "मला पीएम किसान मिळेल का?")
    assert "तुम्ही पात्र आहात का हे पाहण्यासाठी याची उत्तरे द्या:" in ans.text
    assert "मागील वर्षी तुमच्या कुटुंबातील कोणी आयकर भरला का?" in ans.text


def test_scheme_question_naming_a_crop_gets_no_price_card(session):
    ans = ask(session, "कांद्याचा पीक विमा कसा काढायचा?")
    assert ans.text.startswith("प्रधानमंत्री पीक विमा योजना:") and "14447" in ans.text
    assert ans.recommendation is None and ans.decision is None


def test_state_scheme_elsewhere_and_scheme_list(session):
    other = ask(session, "Namo Shetkari yojana", lang="en", district="amritsar")
    assert other.text == "Namo Shetkari Mahasanman Nidhi is a Maharashtra scheme, so it does not apply in Punjab."
    listing = ask(session, "What schemes are there for me?", lang="en")
    assert listing.text.startswith("Schemes I can explain for Maharashtra:") and "Namo Shetkari" in listing.text
    punjab = ask(session, "Which government schemes can I get?", lang="en", district="amritsar")
    assert "Namo Shetkari" not in punjab.text


def test_eligibility_tool_for_the_llm(session):
    ctx = ToolContext(session=session, as_of=AS_OF, language="en", district="pune")
    out, err = run_tool(ctx, "check_scheme_eligibility", {"scheme": "pm-kisan", "owns_land": True, "govt_employee": True})
    assert not err and out["verdict"] == "not_eligible" and out["url"] == "https://pmkisan.gov.in"
    out, err = run_tool(ctx, "check_scheme_eligibility", {"scheme": "pm-kisan", "owns_cow": True})
    assert err and "Unknown facts" in out["error"]
    punjab = ToolContext(session=session, as_of=AS_OF, language="en", district="amritsar")
    out, _ = run_tool(punjab, "check_scheme_eligibility", {"scheme": "namo-shetkari", "pm_kisan_beneficiary": True})
    assert out["verdict"] == "not_eligible" and "only for Maharashtra" in out["reasons"][0]
    assert {"list_schemes", "get_scheme", "check_scheme_eligibility"} <= {t["name"] for t in tool_schemas()}
