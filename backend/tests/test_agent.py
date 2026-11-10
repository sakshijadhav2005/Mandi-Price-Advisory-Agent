"""Agent service tests: offline writer, and the Claude loop against a fake client."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.agent import llm_agent
from app.agent.service import answer_query
from app.config import get_settings

AS_OF = date(2026, 11, 8)


def test_offline_answer_in_each_language(session):
    for lang, marker in [("en", "Confidence"), ("hi", "भरोसा"), ("mr", "खात्री")]:
        ans = answer_query(session, "onion sell or hold?", language=lang, as_of=AS_OF, use_llm=False)
        assert ans.decision in {"sell", "hold"}
        assert marker in ans.text
        assert ans.mode == "offline"
        assert any(s["kind"] == "price" for s in ans.sources)
        assert ans.disclaimer


def test_offline_insufficient_when_data_is_old(session):
    ans = answer_query(session, "onion?", language="en", as_of=date(2027, 3, 1), use_llm=False)
    assert ans.decision == "insufficient_data"
    assert "cannot give reliable" in ans.text


def test_unsupported_crop(session):
    ans = answer_query(session, "should I sell wheat?", language="en", as_of=AS_OF, use_llm=False)
    assert ans.decision is None
    assert "onion" in ans.text.lower()


# --- fake Anthropic client -------------------------------------------------------

def _usage():
    return SimpleNamespace(input_tokens=100, output_tokens=20)


def tool_use(name, args, id_):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=id_)


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0)
        content = step(kwargs) if callable(step) else step
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5-5", usage=_usage())


@pytest.fixture
def fake(monkeypatch):
    def install(script):
        client = FakeClient(script)
        monkeypatch.setattr(llm_agent, "_client", client)
        return client

    return install


def grounded_answer(kwargs):
    """Final turn: build an answer from the compute_recommendation result the loop sent back."""
    import json

    for msg in reversed(kwargs["messages"]):
        if msg["role"] == "user" and isinstance(msg["content"], list):
            for block in msg["content"]:
                data = json.loads(block["content"])
                if "decision" in data:
                    return [text(f"Sell now at {data['best_market_now']}: about ₹{round(data['best_net_now_per_qtl'])} per quintal.")]
    return [text("No data.")]


def test_llm_loop_uses_tools_and_returns_grounded_answer(session, fake):
    client = fake(
        [
            [tool_use("check_data_freshness", {"crop": "onion"}, "t1")],
            [tool_use("compute_recommendation", {"crop": "onion", "quantity_qtl": None, "horizon_days": None}, "t2")],
            grounded_answer,
        ]
    )
    ans = answer_query(session, "Should I sell onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "llm", ans.warnings
    assert [t["tool"] for t in ans.trace] == ["check_data_freshness", "compute_recommendation"]
    assert ans.usage["tool_calls"] == 2
    first = client.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert all(t["strict"] for t in first["tools"])


def test_llm_invented_number_falls_back_to_offline(session, fake):
    fake(
        [
            [tool_use("compute_recommendation", {"crop": "onion", "quantity_qtl": None, "horizon_days": None}, "t1")],
            [text("Hold: prices will reach ₹9,999 next week.")],
        ]
    )
    ans = answer_query(session, "Should I sell onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline"
    assert any(w.startswith("llm_ungrounded_numbers") for w in ans.warnings)
    assert "9,999" not in ans.text


def test_llm_wrong_language_falls_back(session, fake):
    fake([[tool_use("compute_recommendation", {"crop": "onion", "quantity_qtl": None, "horizon_days": None}, "t1")], [text("Sell now.")]])
    ans = answer_query(session, "कांदा विकू का?", language="mr", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline"
    assert "llm_wrong_language" in ans.warnings
    assert "खात्री" in ans.text


def test_tool_budget_is_enforced(session, fake):
    budget = get_settings().tool_budget
    many = [tool_use("check_data_freshness", {"crop": "onion"}, f"t{i}") for i in range(budget + 3)]
    client = fake([many, grounded_answer])
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.usage["tool_calls"] == budget
    assert ans.usage["budget_exhausted"] is True
    results = client.calls[1]["messages"][-1]["content"]
    assert sum(r["is_error"] for r in results) == 3


def test_refusal_falls_back(session, fake, monkeypatch):
    client = fake([[text("")]])
    original = client._create

    def refusing(**kw):
        r = original(**kw)
        r.stop_reason = "refusal"
        return r

    client.beta.messages.create = refusing
    ans = answer_query(session, "onion?", language="en", as_of=AS_OF, use_llm=True)
    assert ans.mode == "offline"
    assert any("declined" in w for w in ans.warnings)
