"""Free local LLM through Ollama (https://ollama.com), no API key needed.

Small local models (3-8B) are less reliable at multi-step tool use than Claude,
so this path is "grounded generation": the server runs the freshness check and
the recommendation itself and hands the model those facts. The model may still
call search_advisories / get_mandi_prices / estimate_transport_cost for extra
detail, within the same tool budget. The usual guardrails (answer language,
number grounding) apply afterwards, with the template writer as fallback.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.agent.llm_agent import LLMResult, LLMUnavailable, build_system_prompt, build_user_turn
from app.agent.tools import ToolContext, run_tool, tool_schemas
from app.config import get_settings
from app.translation.languages import is_advisory_question
from app.translation.templates import t

log = logging.getLogger(__name__)

OPTIONAL_TOOLS = {"search_advisories", "get_mandi_prices", "estimate_transport_cost"}

_available: tuple[float, bool] | None = None


def ollama_available() -> bool:
    """True when the Ollama server is up and the configured model is pulled (cached for 60 s)."""
    global _available
    now = time.monotonic()
    if _available and now - _available[0] < 60:
        return _available[1]
    s = get_settings()
    ok = False
    try:
        resp = httpx.get(f"{s.ollama_url}/api/tags", timeout=1.5)
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        ok = s.ollama_model in names or f"{s.ollama_model}:latest" in names
    except (httpx.HTTPError, ValueError):
        ok = False
    _available = (now, ok)
    return ok


def _simplify(schema: dict) -> dict:
    """Plain JSON Schema for small models: no nullable type arrays, optional fields not required."""
    props = {}
    for name, p in schema["properties"].items():
        p = dict(p)
        if isinstance(p.get("type"), list):
            p["type"] = next(t for t in p["type"] if t != "null")
        if "enum" in p:
            p["enum"] = [v for v in p["enum"] if v is not None]
        props[name] = p
    required = [n for n in schema.get("required", []) if not isinstance(schema["properties"][n].get("type"), list)]
    return {"type": "object", "properties": props, "required": required}


def ollama_tools() -> list[dict]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": _simplify(t["input_schema"])}}
        for t in tool_schemas()
        if t["name"] in OPTIONAL_TOOLS
    ]


def _round(v):
    return round(v) if isinstance(v, float) else v


def _compact_recommendation(rec: dict) -> dict:
    """Essentials only, rupee figures rounded, so a small model does not echo false precision."""
    keep = (
        "crop decision confidence horizon_days quantity_qtl best_market_now best_net_now_per_qtl best_market_hold "
        "best_net_hold_per_qtl expected_gain_per_qtl uncertainty_per_qtl total_value_now reason_codes"
    ).split()
    out = {k: _round(rec[k]) for k in keep if rec.get(k) is not None}
    out["markets"] = [
        {k: _round(m[k]) for k in ("market", "status", "latest_date", "modal_latest", "transport_per_qtl", "net_now_per_qtl", "trend_pct_per_day", "source") if m.get(k) is not None}
        for m in rec["markets"]
    ]
    return out


def _chat(messages: list[dict], tools: list[dict]) -> dict:
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.ollama_url}/api/chat",
            json={"model": s.ollama_model, "messages": messages, "tools": tools, "stream": False, "options": {"temperature": 0.2, "num_ctx": 8192}},
            timeout=s.ollama_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"ollama: {exc}") from exc


def run_ollama_agent(ctx: ToolContext, question: str, history: list[dict] | None = None) -> LLMResult:
    s = get_settings()
    result = LLMResult(text="", stop_reason=None, model=f"ollama:{s.ollama_model}")
    facts = []
    decision_phrase = ""
    if ctx.default_crop:
        fresh, _ = run_tool(ctx, "check_data_freshness", {"crop": ctx.default_crop})
        rec, err = run_tool(ctx, "compute_recommendation", {"crop": ctx.default_crop, "quantity_qtl": ctx.default_quantity_qtl, "horizon_days": None})
        result.tool_calls += 2
        if not err:
            facts.append({"tool": "compute_recommendation", "result": _compact_recommendation(rec)})
            decision_phrase = t(ctx.language, f"decision.{rec['decision']}", h=rec["horizon_days"])
        facts.append({"tool": "check_data_freshness", "result": {k: fresh.get(k) for k in ("fresh_markets", "total_markets", "usable")}})

    if is_advisory_question(question):
        adv, err = run_tool(ctx, "search_advisories", {"query": question, "crop": ctx.default_crop})
        result.tool_calls += 1
        if not err and adv["results"]:
            facts.append({"tool": "search_advisories", "result": [{"title": h["title"], "language": h["language"], "text": h["text"]} for h in adv["results"][:2]]})

    user = build_user_turn(ctx, question)
    if facts:
        user += (
            f"\n\nRecommendation from the server: \"{decision_phrase}\". If the farmer asked whether to sell or hold, "
            "begin your answer with exactly that recommendation, then give the main reason in one or two sentences. "
            "Do not calculate new numbers. The server already ran these tools for you. "
            "Base the recommendation and every number on them:\n" + json.dumps(facts, ensure_ascii=False)
        )
    messages = [
        {"role": "system", "content": build_system_prompt()},
        *(history or []),
        {"role": "user", "content": user},
    ]
    tools = ollama_tools()

    for _ in range(s.tool_budget + 2):
        data = _chat(messages, tools)
        msg = data.get("message", {})
        result.input_tokens += data.get("prompt_eval_count", 0) or 0
        result.output_tokens += data.get("eval_count", 0) or 0
        result.stop_reason = data.get("done_reason")
        calls = msg.get("tool_calls") or []
        if not calls:
            result.text = (msg.get("content") or "").strip()
            return result
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if result.tool_calls >= s.tool_budget:
                result.budget_exhausted = True
                content = {"error": "Tool budget exhausted. Answer now."}
            elif name not in OPTIONAL_TOOLS:
                content = {"error": f"Tool {name!r} is not available. Answer with the facts you have."}
            else:
                result.tool_calls += 1
                if name in ("search_advisories",) and "crop" not in args:
                    args["crop"] = None
                if name == "get_mandi_prices":
                    args = {"crop": args.get("crop"), "market": args.get("market"), "days": args.get("days")}
                if name == "estimate_transport_cost":
                    args = {"market": args.get("market", ""), "quantity_qtl": args.get("quantity_qtl")}
                content, _ = run_tool(ctx, name, args)
            messages.append({"role": "tool", "content": json.dumps(content, ensure_ascii=False, default=str), "tool_name": name})
    raise LLMUnavailable("ollama agent did not finish within the turn limit")
