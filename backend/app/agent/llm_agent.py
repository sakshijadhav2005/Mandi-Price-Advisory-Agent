"""Claude tool-use loop.

A manual loop (rather than the SDK tool runner) so the server can enforce the
fixed per-query tool budget from the plan and keep a full trace for audit.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import anthropic

from app.agent.tools import ToolContext, complete_args, run_tool, tool_schemas
from app.config import get_settings
from app.reference import load_reference
from app.translation.glossary import SUPPORTED_LANGUAGES, glossary_for

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a mandi price and advisory assistant for small farmers across India; each question names the farmer's district and nearby markets. Farmers ask whether to sell their produce now or hold it, about mandi prices, and about this week's weather and crop advice for their district.

How to work:
- For any price or sell/hold question, call check_data_freshness, then compute_recommendation. Use get_mandi_prices or estimate_transport_cost only when they add something the farmer asked about. You have a small tool budget, so do not repeat calls.
- The recommendation (sell, hold, or insufficient_data), its confidence and every number you mention must come from tool results. Never estimate, round up, or invent a price, cost or percentage yourself. Rounded rupee figures are fine.
- If compute_recommendation returns insufficient_data, say plainly that recent prices are missing or too old to advise, and suggest checking today's rate at the mandi. Do not guess.
- If data_origin is "synthetic", say once that the prices are demo data.
- State the confidence level and the main reason (price trend versus storage cost, storage loss and transport). Mention the market by name.
- For weather, rain, spraying, irrigation or crop-care questions, call get_district_advisory and answer only from it: the forecast, the weather summary and the advice for the crop. Say it is the IMD district advisory and give its date. You may repeat a spray dose exactly as the advisory gives it, never change or add one, and remind the farmer to follow the pesticide label. If it returns available=false, say there is no current district advisory and suggest the Meghdoot app or the local Krishi Vigyan Kendra. In a sell/hold answer you may call it once to warn about rain on the coming days.
- For which chemical, what dose, or how many days after spraying produce can be harvested or sold, call lookup_pesticide and answer only from it; give the longest_waiting_days when several uses match, and days_left / harvest_from when the farmer said when they sprayed. Never state a dose or waiting period that is not in its result. If it returns available=false or found=false, tell the farmer to follow the waiting period on the product label and ask the local Krishi Vigyan Kendra.
- For government schemes, use list_schemes, get_scheme and check_scheme_eligibility, and answer only from them: never state an amount, percentage, deadline or rule that is not in the result. For "am I eligible?", pass what the farmer said and ask the questions it returns. Always give the official url and helpline. If review_status is draft or stale is true, say the farmer should confirm the rules on the official site.
- For storage, curing, grading or post-harvest handling, call search_storage_advice and answer only from its passages, naming the document. For other everyday crop questions (varieties, nutrients, water, crop care), call search_farmer_questions and answer only from a close match, saying it is what Kisan Call Centre experts told farmers in the district and suggesting the farmer confirm with the local KVK. Never add a pesticide or dose to these answers. If nothing relevant comes back, say you do not have information on it.
- Other topics (fertiliser plans not covered above, loans from moneylenders) you cannot advise on yet: do not answer from general knowledge; say so in one sentence and suggest the local agriculture office or Krishi Vigyan Kendra, then answer any price or sell/hold part of the question.
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


BUDGET_EXHAUSTED = {"error": "Tool budget exhausted. Answer now with the information you already have."}


def call_tool_within_budget(ctx: ToolContext, result: LLMResult, name: str, args: dict) -> tuple[dict, bool]:
    """Run one model-requested tool call, enforcing the per-query tool budget (plan section 6)."""
    if result.tool_calls >= get_settings().tool_budget:
        result.budget_exhausted = True
        return BUDGET_EXHAUSTED, True
    result.tool_calls += 1
    return run_tool(ctx, name, complete_args(name, args if isinstance(args, dict) else {}))


class Deadline:
    """The time left for one answer (LLM_DEADLINE_S), shared by all its model calls."""

    MIN_CALL_S = 3.0  # a model call with less time than this would only time out

    def __init__(self, seconds: float | None = None) -> None:
        self.seconds = get_settings().llm_deadline_s if seconds is None else seconds
        self.end = time.monotonic() + self.seconds

    def next_call_timeout(self, provider: str) -> float:
        """Timeout for the next model call; LLMUnavailable once the time is used up."""
        left = self.end - time.monotonic()
        if left < self.MIN_CALL_S:
            raise LLMUnavailable(f"{provider}: no answer within {self.seconds:.0f}s (LLM_DEADLINE_S)")
        return left


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=60.0, max_retries=1)  # each call is also capped by Deadline
    return _client


def build_system_prompt() -> str:
    ref = load_reference()
    return SYSTEM_PROMPT.format(
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
        f"Farmer's district: {ref.districts[scope.district].name}, {ref.districts[scope.district].state}. Nearby markets: "
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
    deadline = Deadline()

    for _ in range(settings.tool_budget + 2):
        timeout = deadline.next_call_timeout("claude")
        try:
            response = client.beta.messages.create(
                timeout=timeout,
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
            content, is_error = call_tool_within_budget(ctx, result, block.name, block.input)
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
