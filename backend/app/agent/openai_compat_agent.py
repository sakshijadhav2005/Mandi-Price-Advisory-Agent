"""Tool-use loop for free hosted LLMs that speak the OpenAI chat-completions API.

Presets (pick one with LLM_PROVIDER, or let LLM_PROVIDER=auto pick the first key set):
- gemini:     Google AI Studio free tier  (GEMINI_API_KEY, https://aistudio.google.com/apikey)
- groq:       Groq free tier              (GROQ_API_KEY, https://console.groq.com/keys)
- openrouter: OpenRouter ":free" models   (OPENROUTER_API_KEY, https://openrouter.ai/keys)

Same contract as the Claude loop: fixed tool budget, full trace, and the usual
guardrails afterwards, with the template writer as fallback on any failure
(including free-tier rate limits).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.agent.llm_agent import Deadline, LLMResult, LLMUnavailable, build_system_prompt, build_user_turn, call_tool_within_budget
from app.agent.tools import ToolContext, function_tools
from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preset:
    base_url: str
    key_setting: str
    model_setting: str
    # Thinking models (gemini-3.5-flash, gpt-oss) can spend 20+ s "thinking" before a short
    # answer, past LLM_DEADLINE_S; a low reasoning effort keeps them to a few seconds.
    effort_setting: str | None = None


PRESETS: dict[str, Preset] = {
    "gemini": Preset("https://generativelanguage.googleapis.com/v1beta/openai", "gemini_api_key", "gemini_model", "gemini_reasoning_effort"),
    "groq": Preset("https://api.groq.com/openai/v1", "groq_api_key", "groq_model", "groq_reasoning_effort"),
    "openrouter": Preset("https://openrouter.ai/api/v1", "openrouter_api_key", "openrouter_model"),
}


def configured_free_provider() -> str | None:
    """First preset whose API key is set, in the order gemini, groq, openrouter."""
    s = get_settings()
    return next((name for name, p in PRESETS.items() if getattr(s, p.key_setting)), None)


def _chat(provider: str, messages: list[dict], tools: list[dict], timeout: float = 60.0) -> dict:
    s = get_settings()
    preset = PRESETS[provider]
    key = getattr(s, preset.key_setting)
    if not key:
        raise LLMUnavailable(f"{provider}: no API key set ({preset.key_setting.upper()})")
    body = {
        "model": getattr(s, preset.model_setting),
        "messages": messages,
        "tools": tools,
        "temperature": 0.2,
        "max_tokens": s.llm_max_tokens,
    }
    if provider == "groq":
        # Groq's free tier counts prompt + max_tokens against a per-minute token limit (8,000):
        # the default 4,000-token reply budget alone would exhaust it. Answers are short.
        body["max_tokens"] = min(s.llm_max_tokens, s.groq_max_tokens)
    if preset.effort_setting and (effort := getattr(s, preset.effort_setting, "")):
        body["reasoning_effort"] = effort
    try:
        resp = httpx.post(
            f"{preset.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"{provider}: connection error: {exc}") from exc
    if resp.status_code in (401, 403):
        raise LLMUnavailable(f"{provider}: credentials rejected ({resp.status_code})")
    if resp.status_code == 429:
        raise LLMUnavailable(f"{provider}: rate limited (free-tier quota)")
    if resp.status_code >= 400:
        raise LLMUnavailable(f"{provider}: API error {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise LLMUnavailable(f"{provider}: invalid JSON response") from exc


def run_openai_compat_agent(provider: str, ctx: ToolContext, question: str, history: list[dict] | None = None) -> LLMResult:
    s = get_settings()
    result = LLMResult(text="", stop_reason=None, model=f"{provider}:{getattr(s, PRESETS[provider].model_setting)}")
    tools = function_tools(keep_null=provider == "groq")
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt()},
        *(history or []),
        {"role": "user", "content": build_user_turn(ctx, question)},
    ]

    deadline = Deadline()
    for _ in range(s.tool_budget + 2):
        data = _chat(provider, messages, tools, timeout=deadline.next_call_timeout(provider))
        usage = data.get("usage") or {}
        result.input_tokens += usage.get("prompt_tokens", 0) or 0
        result.output_tokens += usage.get("completion_tokens", 0) or 0
        choices = data.get("choices") or []
        if not choices:
            raise LLMUnavailable(f"{provider}: empty response")
        choice = choices[0]
        msg = choice.get("message") or {}
        result.stop_reason = choice.get("finish_reason")
        calls = msg.get("tool_calls") or []
        if not calls:
            if result.stop_reason == "length":
                raise LLMUnavailable(f"{provider}: answer was cut off at max_tokens")
            result.text = (msg.get("content") or "").strip()
            return result

        # Echo the assistant turn back unchanged: Gemini keeps thought signatures in it.
        messages.append(msg)
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            content, _ = call_tool_within_budget(ctx, result, name, args)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(content, ensure_ascii=False, default=str)}
            )

    raise LLMUnavailable(f"{provider}: agent did not finish within the turn limit")
