"""Free hosted LLMs (Gemini / Groq / OpenRouter), tested against a fake OpenAI-compatible server."""

import json
from datetime import date

import httpx
import pytest

from app.agent import openai_compat_agent, service
from app.agent.service import answer_query, resolve_provider
from app.config import get_settings

AS_OF = date(2026, 11, 8)


@pytest.fixture
def gemini(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    calls = []

    def install(replies, status=200):
        replies = list(replies)

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "body": json})
            reply = replies.pop(0) if replies else {}
            body = reply(json) if callable(reply) else reply
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

        monkeypatch.setattr(openai_compat_agent.httpx, "post", fake_post)
        return calls

    return install


def tool_call(name, args, call_id="call_1"):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
                },
            }
        ],
        "usage": {"prompt_tokens": 800, "completion_tokens": 20},
    }


def answer_from_recommendation(req):
    """Write the final answer from the compute_recommendation tool result."""
    rec = json.loads(next(m["content"] for m in reversed(req["messages"]) if m["role"] == "tool"))
    text = f"Sell now at {rec['best_market_now']}, about ₹{round(rec['best_net_now_per_qtl'])} per quintal."
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 1200, "completion_tokens": 30}}


def test_gemini_tool_loop_answer(session, gemini):
    # The model omits the optional arguments; the server fills them with null.
    calls = gemini([tool_call("compute_recommendation", {"crop": "onion"}), answer_from_recommendation])
    ans = answer_query(session, "Should I sell onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "llm", ans.warnings
    assert ans.usage["model"] == "gemini:gemini-2.5-flash"
    assert ans.usage["input_tokens"] == 2000
    assert [t["tool"] for t in ans.trace] == ["compute_recommendation"]
    assert calls[0]["url"].startswith("https://generativelanguage.googleapis.com/")
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["body"]["messages"][0]["role"] == "system"
    # The assistant turn is echoed back unchanged, followed by the tool result.
    assert calls[1]["body"]["messages"][-2]["tool_calls"][0]["id"] == "call_1"
    assert calls[1]["body"]["messages"][-1]["tool_call_id"] == "call_1"
    for tool in calls[0]["body"]["tools"]:
        for prop in tool["function"]["parameters"]["properties"].values():
            assert isinstance(prop["type"], str)


def test_rate_limit_falls_back_to_templates(session, gemini):
    gemini([{"error": {"message": "quota"}}], status=429)
    ans = answer_query(session, "कांदा विकू का?", language="mr", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline" and ans.text
    assert any("rate limited" in w for w in ans.warnings)


def test_invented_number_falls_back(session, gemini):
    gemini([{"choices": [{"finish_reason": "stop", "message": {"content": "Prices will hit ₹7,777 tomorrow."}}]}])
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline"
    assert any(w.startswith("llm_ungrounded_numbers") for w in ans.warnings)


def test_tool_budget_enforced(session, gemini, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_budget", 1)
    final = {"choices": [{"finish_reason": "stop", "message": {"content": "Check today's rate at the mandi."}}]}
    calls = gemini([tool_call("check_data_freshness", {"crop": "onion"}), tool_call("check_data_freshness", {"crop": "onion"}, "call_2"), final])
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.usage["budget_exhausted"] is True
    assert ans.usage["tool_calls"] == 1
    assert "budget exhausted" in calls[2]["body"]["messages"][-1]["content"]


def test_auto_picks_free_provider(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_enabled", True)
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for key in ("gemini_api_key", "groq_api_key", "openrouter_api_key"):
        monkeypatch.setattr(s, key, "")
    assert resolve_provider() == "none"
    monkeypatch.setattr(s, "groq_api_key", "g")
    assert resolve_provider() == "groq"
    monkeypatch.setattr(s, "gemini_api_key", "x")
    assert resolve_provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert resolve_provider() == "anthropic"
    assert service.PRESETS.keys() == {"gemini", "groq", "openrouter"}
