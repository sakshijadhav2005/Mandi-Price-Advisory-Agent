"""Local Ollama provider, tested against a fake Ollama HTTP server."""

import json
from datetime import date

import httpx
import pytest

from app.agent import ollama_agent
from app.agent.service import answer_query, resolve_provider
from app.config import get_settings

AS_OF = date(2026, 11, 8)


@pytest.fixture
def ollama(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "ollama")
    calls = []

    def install(replies):
        replies = list(replies)

        def fake_post(url, json=None, timeout=None):
            calls.append(json)
            reply = replies.pop(0)
            body = reply(json) if callable(reply) else reply
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

        monkeypatch.setattr(ollama_agent.httpx, "post", fake_post)
        return calls

    return install


def facts_answer(req):
    """Write an answer from the facts the server put in the user turn."""
    marker = "Base the recommendation and every number on them:\n"
    user = next(m["content"] for m in req["messages"] if m["role"] == "user" and marker in m["content"])
    facts = json.loads(user.split(marker, 1)[1])
    rec = facts[0]["result"]
    return {"message": {"role": "assistant", "content": f"Sell now at {rec['best_market_now']}, about ₹{round(rec['best_net_now_per_qtl'])} per quintal."}, "done_reason": "stop", "prompt_eval_count": 900, "eval_count": 30}


def test_ollama_grounded_answer(session, ollama):
    calls = ollama([facts_answer])
    ans = answer_query(session, "Should I sell onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "llm", ans.warnings
    assert ans.usage["model"] == "ollama:qwen2.5:3b"
    assert [t["tool"] for t in ans.trace] == ["check_data_freshness", "compute_recommendation"]
    assert {t["function"]["name"] for t in calls[0]["tools"]} == {"search_advisories", "get_mandi_prices", "estimate_transport_cost"}
    for tool in calls[0]["tools"]:
        for prop in tool["function"]["parameters"]["properties"].values():
            assert isinstance(prop["type"], str)
            assert None not in prop.get("enum", [])


def test_ollama_tool_call_then_answer(session, ollama):
    tool_turn = {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_advisories", "arguments": {"query": "onion storage"}}}]}}
    calls = ollama([tool_turn, facts_answer])
    ans = answer_query(session, "How do I store onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "llm"
    assert "search_advisories" in [t["tool"] for t in ans.trace]
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert any(src["kind"] == "advisory" for src in ans.sources)


def test_ollama_invented_number_falls_back(session, ollama):
    ollama([{"message": {"role": "assistant", "content": "Prices will hit ₹7,777 tomorrow."}}])
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline"
    assert any(w.startswith("llm_ungrounded_numbers") for w in ans.warnings)


def test_ollama_down_falls_back(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "ollama")

    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(ollama_agent.httpx, "post", boom)
    ans = answer_query(session, "onion?", language="hi", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline" and "भरोसा" in ans.text


def test_auto_provider_resolution(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_enabled", True)
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for key in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
        monkeypatch.setattr(s, key, "")
    assert resolve_provider() == "none"  # local models are opt-in
    monkeypatch.setattr(s, "llm_provider", "ollama")
    assert resolve_provider() == "ollama"
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert resolve_provider() == "anthropic"
    monkeypatch.setattr(s, "llm_enabled", False)
    assert resolve_provider() == "none"


def test_decision_consistency_guardrail():
    from app.agent.guardrails import decision_consistent

    assert decision_consistent("You should sell your onion now. Holding is not worth it.", "sell", "en")
    assert not decision_consistent("You can wait a few days. Then sell.", "sell", "en")
    assert not decision_consistent("मी कांदा विकू शकता, तरी थांबू शकता.", "sell", "mr")
    assert decision_consistent("अभी बेचें। भाव गिर रहे हैं।", "sell", "hi")
    assert decision_consistent("Hold for 7 days; prices are rising.", "hold", "en")
    assert decision_consistent("Recent prices are missing, so I cannot advise.", "insufficient_data", "en")
    assert decision_consistent("Cure the bulbs for 3 to 5 days first.", "sell", "en")  # storage advice, no decision
    assert not decision_consistent("Not enough data. Check the mandi.", "sell", "en")


def test_contradicting_answer_falls_back(session, ollama):
    ollama([{"message": {"role": "assistant", "content": "You can wait and store your onion for a week."}}])
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.decision == "sell"
    assert ans.mode == "offline" and "llm_decision_mismatch" in ans.warnings


def test_ollama_skipped_for_languages_not_enabled(session, ollama):
    calls = ollama([])
    ans = answer_query(session, "कांदा विकू का?", language="mr", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline" and calls == [] and ans.warnings == []


def test_offline_storage_question_answers_from_bulletin(session):
    en = answer_query(session, "How should I store onions so they do not rot?", language="en", as_of=AS_OF, use_llm=False)
    assert en.text.startswith("From the crop advisory (Onion curing and storage after harvest):")
    mr = answer_query(session, "कांदा साठवण कशी करावी?", language="mr", as_of=AS_OF, use_llm=False)
    assert mr.text.startswith("पीक सल्ल्यातून (कांदा काढणीनंतर सुकवणे आणि साठवण):")
    assert any(src["kind"] == "advisory" for src in mr.sources)
    plain = answer_query(session, "Should I sell onion now?", language="en", as_of=AS_OF, use_llm=False)
    assert plain.text.startswith(("Sell now", "Hold"))


def test_advisory_answers_may_say_store_but_not_hold():
    from app.agent.guardrails import decision_consistent

    assert decision_consistent("Store your onions in a ventilated shed.", "sell", "en", advisory=True)
    assert not decision_consistent("Hold your onions. Curing helps.", "sell", "en", advisory=True)
    assert decision_consistent("कांदा हवेशीर चाळीत साठवा.", "sell", "mr", advisory=True)
    assert not decision_consistent("कांदा थांबवा, दर वाढतील.", "sell", "mr", advisory=True)
