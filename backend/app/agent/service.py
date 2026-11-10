"""Answer a farmer query: run the agent, apply guardrails, assemble the response."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.agent import fallback
from app.agent.data import today
from app.agent.guardrails import decision_consistent, language_ok, ungrounded_numbers
from app.agent.llm_agent import LLMUnavailable, run_llm_agent
from app.agent.ollama_agent import ollama_available, run_ollama_agent  # noqa: F401
from app.agent.tools import ToolContext, compute_recommendation, run_tool
from app.config import get_settings
from app.reference import detect_crop, detect_district, detect_quantity_qtl, load_reference
from app.translation.glossary import SUPPORTED_LANGUAGES
from app.translation.languages import is_advisory_question
from app.translation.templates import t

log = logging.getLogger(__name__)


@dataclass
class AgentAnswer:
    text: str
    language: str
    decision: str | None
    confidence: str | None
    recommendation: dict | None
    sources: list[dict]
    disclaimer: str
    mode: str  # llm | offline
    trace: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)


def resolve_provider() -> str:
    """Which answer writer to use: anthropic | ollama | none."""
    s = get_settings()
    if not s.llm_enabled:
        return "none"
    if s.llm_provider != "auto":
        return s.llm_provider
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    # Local models are opt-in (LLM_PROVIDER=ollama): in testing, a 3B model's explanations
    # were often muddled even when the numbers and the decision passed the guardrails.
    return "none"


def _tool_outputs(ctx: ToolContext) -> list[dict]:
    """Everything the model was shown: tool results plus the facts in the user turn."""
    return [*ctx.outputs, {"quantity_qtl": ctx.default_quantity_qtl, "as_of": ctx.as_of.isoformat()}]


def answer_query(
    session: Session,
    question: str,
    language: str = "en",
    crop: str | None = None,
    quantity_qtl: float | None = None,
    farmer_lat: float | None = None,
    farmer_lon: float | None = None,
    as_of: date | None = None,
    history: list[dict] | None = None,
    use_llm: bool | None = None,
    district: str | None = None,
) -> AgentAnswer:
    settings = get_settings()
    started = time.perf_counter()
    language = language if language in SUPPORTED_LANGUAGES else "en"
    crop = crop if crop in load_reference().crops else None
    crop = detect_crop(question) or crop
    quantity_qtl = detect_quantity_qtl(question) or quantity_qtl
    district = detect_district(question) or (district if district in load_reference().districts else None)

    ctx = ToolContext(
        session=session,
        as_of=as_of or today(),
        language=language,
        farmer_lat=farmer_lat,
        farmer_lon=farmer_lon,
        default_crop=crop,
        default_quantity_qtl=quantity_qtl,
        district=district,
    )
    warnings: list[str] = []
    usage: dict = {}
    mode = "offline"
    text = ""
    llm_text = None

    provider = resolve_provider() if use_llm is not False else "none"
    if use_llm and provider == "none":
        provider = settings.llm_provider if settings.llm_provider in ("anthropic", "ollama") else "anthropic"
    if provider == "ollama" and language not in settings.ollama_language_list:
        provider = "none"  # small local models write poor Hindi/Marathi; use the templates instead
    if provider != "none":
        try:
            res = (run_ollama_agent if provider == "ollama" else run_llm_agent)(ctx, question, history)
            llm_text = res.text
            usage = {
                "model": res.model,
                "input_tokens": res.input_tokens,
                "output_tokens": res.output_tokens,
                "tool_calls": res.tool_calls,
                "budget_exhausted": res.budget_exhausted,
            }
            if not res.text:
                warnings.append("llm_empty_answer")
            elif not language_ok(res.text, language):
                warnings.append("llm_wrong_language")
            elif bad := ungrounded_numbers(res.text, _tool_outputs(ctx)):
                warnings.append(f"llm_ungrounded_numbers:{','.join(bad[:5])}")
            elif not decision_consistent(
                res.text, (ctx.recommendation or {}).get("decision"), language, advisory=is_advisory_question(question)
            ):
                warnings.append("llm_decision_mismatch")
            else:
                text, mode = res.text, "llm"
        except LLMUnavailable as exc:
            log.warning("LLM unavailable, using offline answer writer: %s", exc)
            warnings.append(f"llm_unavailable:{exc}"[:300])

    if mode == "offline":
        # Fresh context so the offline writer's trace and sources are not mixed with a rejected LLM attempt.
        llm_trace = ctx.trace
        ctx = ToolContext(
            session=session,
            as_of=ctx.as_of,
            language=language,
            farmer_lat=farmer_lat,
            farmer_lon=farmer_lon,
            default_crop=crop,
            default_quantity_qtl=quantity_qtl,
            district=district,
        )
        text = fallback.write_answer(ctx, crop, quantity_qtl, question=question)
        if llm_text is not None:
            ctx.trace = [{"tool": "(rejected llm attempt)", "args": {}, "is_error": True, "summary": f"{len(llm_trace)} tool calls"}] + ctx.trace

    # Always attach a structured recommendation when a crop is known, so the UI card is grounded.
    if ctx.recommendation is None and crop:
        compute_recommendation(ctx, crop=crop, quantity_qtl=quantity_qtl)
    rec = ctx.recommendation

    return AgentAnswer(
        text=text,
        language=language,
        decision=rec["decision"] if rec else None,
        confidence=rec["confidence"] if rec else None,
        recommendation=rec,
        sources=list(ctx.sources.values()),
        disclaimer=t(language, "disclaimer"),
        mode=mode,
        trace=ctx.trace,
        warnings=warnings,
        latency_ms=int((time.perf_counter() - started) * 1000),
        usage=usage,
        audit={
            "question": question,
            "language": language,
            "crop": crop,
            "quantity_qtl": quantity_qtl,
            "as_of": ctx.as_of.isoformat(),
            "district": district,
            "decision": rec["decision"] if rec else None,
            "reason_codes": rec["reason_codes"] if rec else [],
            "rejected_llm_answer": llm_text if mode == "offline" and llm_text else None,
        },
    )


__all__ = ["AgentAnswer", "answer_query", "run_tool"]
