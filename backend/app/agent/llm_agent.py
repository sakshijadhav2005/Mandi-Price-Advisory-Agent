"""Claude tool-use loop.

A manual loop (rather than the SDK tool runner) so the server can enforce the
fixed per-query tool budget from the plan and keep a full trace for audit.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic

from app.agent.tools import ToolContext, run_tool, tool_schemas
from app.config import get_settings
from app.reference import load_reference
from app.translation.glossary import SUPPORTED_LANGUAGES, glossary_for

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a mandi price and advisory assistant for small farmers in {district} district(s), {state}, India. Farmers ask whether to sell their produce now or hold it, and how to store or handle it.

How to work:
- For any price or sell/hold question, call check_data_freshness, then compute_recommendation. Use get_mandi_prices, estimate_transport_cost or search_advisories only when they add something the farmer asked about. You have a small tool budget, so do not repeat calls.
- The recommendation (sell, hold, or insufficient_data), its confidence and every number you mention must come from tool results. Never estimate, round up, or invent a price, cost or percentage yourself. Rounded rupee figures are fine.
- If compute_recommendation returns insufficient_data, say plainly that recent prices are missing or too old to advise, and suggest checking today's rate at the mandi. Do not guess.
- If data_origin is "synthetic", say once that the prices are demo data.
- State the confidence level and the main reason (price trend versus storage cost, storage loss and transport). Mention the market by name.
- For storage, quality or handling questions, use search_advisories and base your advice on the passages it returns.
- Crops currently supported: {crops}. If the farmer asks about another crop, say you cannot advise on it yet.

How to answer:
- Reply only in the farmer's language, given in each message. Use simple, everyday words that a farmer would use when speaking, not technical terms.
- Keep it short: 3 to 5 sentences, under about 90 words, so it can be read aloud in under 30 seconds. No headings, tables, markdown or bullet points.
- Write prices as ₹ per quintal.
- Do not add a disclaimer; the app adds one.

Supported farmer languages: {languages}."""


@dataclass
class LLMResult:
    text: str
    stop_reason: str | None
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    budget_exhausted: bool = False


class LLMUnavailable(Exception):
    pass


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    return _client


def build_system_prompt() -> str:
    ref = load_reference()
    return SYSTEM_PROMPT.format(
        district=", ".join(d.name for d in ref.districts.values()),
        state=", ".join(sorted({d.state for d in ref.districts.values()})),
        crops=", ".join(ref.crops),
        languages=", ".join(f"{code} ({name})" for code, name in SUPPORTED_LANGUAGES.items()),
    )


def build_user_turn(ctx: ToolContext, question: str) -> str:
    lang_name = SUPPORTED_LANGUAGES.get(ctx.language, "English")
    parts = [
        f"Farmer language: {lang_name} ({ctx.language}). Answer in {lang_name}.",
        f"Today's date: {ctx.as_of.isoformat()}.",
    ]
    if ctx.default_crop:
        parts.append(f"Crop selected in the app: {ctx.default_crop}.")
    if ctx.default_quantity_qtl:
        parts.append(f"Quantity: {ctx.default_quantity_qtl:g} quintals.")
    ref = load_reference()
    scope = ref.scope(ctx.district, ctx.farmer_lat, ctx.farmer_lon)
    parts.append(
        f"Farmer's district: {ref.districts[scope.district].name}. Nearby markets: "
        + ", ".join(f"{ref.markets[m].name} ({m})" for m in scope.market_ids)
        + "."
    )
    if not scope.location_known:
        parts.append("Farmer location unknown; tools use the district centre.")
    if gl := glossary_for(ctx.language):
        parts.append(f"Use these terms consistently:\n{gl}")
    return "\n".join(parts) + f"\n\nFarmer's question:\n{question}"


def run_llm_agent(ctx: ToolContext, question: str, history: list[dict] | None = None) -> LLMResult:
    settings = get_settings()
    client = get_client()
    tools = tool_schemas()
    messages: list[dict] = [*(history or []), {"role": "user", "content": build_user_turn(ctx, question)}]
    result = LLMResult(text="", stop_reason=None, model=None)

    for _ in range(settings.tool_budget + 2):
        try:
            response = client.beta.messages.create(
                model=settings.llm_model,
                max_tokens=settings.llm_max_tokens,
                system=build_system_prompt(),
                tools=tools,
                messages=messages,
                output_config={"effort": settings.llm_effort},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMUnavailable(f"credentials rejected: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable(f"rate limited: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise LLMUnavailable(f"bad request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable(f"connection error: {exc}") from exc
        except TypeError as exc:  # raised when no credentials can be resolved at all
            raise LLMUnavailable(f"no credentials: {exc}") from exc

        result.model = response.model
        result.stop_reason = response.stop_reason
        result.input_tokens += response.usage.input_tokens or 0
        result.output_tokens += response.usage.output_tokens or 0

        if response.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request")
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            result.text = "\n\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                raise LLMUnavailable("answer was cut off at max_tokens")
            return result

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_uses:
            if result.tool_calls >= settings.tool_budget:
                result.budget_exhausted = True
                content, is_error = {"error": "Tool budget exhausted. Answer now with the information you already have."}, True
            else:
                result.tool_calls += 1
                args = block.input if isinstance(block.input, dict) else {}
                content, is_error = run_tool(ctx, block.name, args)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(content, ensure_ascii=False, default=str),
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise LLMUnavailable("agent did not finish within the turn limit")
