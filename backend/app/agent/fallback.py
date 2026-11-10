"""Deterministic answer writer: runs the tools in a fixed order and fills templates.

Used when no LLM is configured, when the LLM call fails, and when an LLM answer
fails a guardrail (wrong language or numbers not traceable to tool output).
"""

from __future__ import annotations

import re

from app.agent.tools import ToolContext, run_tool
from app.reference import load_reference
from app.translation.languages import is_advisory_question
from app.translation.templates import inr, t

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def _tip(ctx: ToolContext, decision: str, crop_id: str) -> str | None:
    query = {
        "hold": "storage loss rot ventilated store",
        "sell": "grading selling market transport costs",
    }.get(decision, "market price report")
    result, err = run_tool(ctx, "search_advisories", {"query": query, "crop": crop_id})
    if err:
        return None
    for hit in result["results"]:
        if hit["language"] == ctx.language:
            return _SENTENCE_END.split(hit["text"].strip())[0]
    return None


def advisory_answer(ctx: ToolContext, question: str, crop_id: str | None) -> str | None:
    """Answer a storage / handling question from the best bulletin passage, preferring the farmer's language."""
    result, err = run_tool(ctx, "search_advisories", {"query": question, "crop": crop_id})
    if err or not result["results"]:
        return None
    hits = result["results"]
    hit = next((h for h in hits if h["language"] == ctx.language), None)
    if hit is None:
        if ctx.language != "en":
            return None  # avoid answering a Hindi/Marathi farmer in English
        hit = hits[0]
    sentences = _SENTENCE_END.split(hit["text"].strip())
    return t(ctx.language, "advice_from", title=hit["title"]) + " " + " ".join(sentences[:3])


def write_answer(
    ctx: ToolContext,
    crop_id: str | None,
    quantity_qtl: float | None = None,
    horizon_days: int | None = None,
    question: str = "",
) -> str:
    ref = load_reference()
    lang = ctx.language
    if not crop_id or crop_id not in ref.crops:
        return t(lang, "unsupported_crop", crops=", ".join(c.display(lang) for c in ref.crops.values()))
    crop = ref.crops[crop_id]
    crop_name = crop.display(lang)

    advice = advisory_answer(ctx, question, crop_id) if question and is_advisory_question(question) else None

    run_tool(ctx, "check_data_freshness", {"crop": crop_id})
    rec, err = run_tool(
        ctx, "compute_recommendation", {"crop": crop_id, "quantity_qtl": quantity_qtl, "horizon_days": horizon_days}
    )
    if err:
        return rec["error"]

    lines: list[str] = [advice] if advice else []
    h = rec["horizon_days"]
    if rec["decision"] == "insufficient_data":
        lines.append(t(lang, "decision.insufficient_data") + t(lang, "eos"))
        lines.append(t(lang, "insufficient", crop=crop_name, days=rec["assumptions"]["stale_after_days"]))
        return "\n\n".join(lines)

    markets = {m["market"]: m for m in rec["markets"]}
    best = markets[rec["best_market_now"]]
    lines.append(f"{t(lang, 'decision.' + rec['decision'], h=h)}{t(lang, 'eos')} {t(lang, 'confidence_line', c=t(lang, 'confidence.' + rec['confidence']))}")
    best_line = t(
        lang,
        "best_now",
        crop=crop_name,
        market=ref.markets[best["market"]].display(lang),
        modal=inr(best["modal_latest"]),
        date=best["latest_date"],
        transport=inr(best["transport_per_qtl"]),
        net=inr(best["net_now_per_qtl"]),
    )
    if rec.get("total_value_now"):
        best_line += " " + t(lang, "total_now", qty=f"{rec['quantity_qtl']:g}", total=inr(rec["total_value_now"]))
    lines.append(best_line)

    hold = markets[rec["best_market_hold"]]
    fmt = dict(
        h=h,
        crop=crop_name,
        gain=inr(rec["expected_gain_per_qtl"]),
        sigma=inr(rec["uncertainty_per_qtl"]),
        trend=f"{hold['trend_pct_per_day']:.1f}",
        hold_net=inr(rec["best_net_hold_per_qtl"]),
        hold_market=ref.markets[hold["market"]].display(lang),
        season=f"{hold.get('seasonal_pct') or 0:.0f}",
        stale=", ".join(ref.markets[m["market"]].display(lang) for m in rec["markets"] if m["status"] == "stale"),
    )
    reasons = []
    if rec["decision"] == "hold":
        reasons.append(t(lang, "hold_case", **fmt))
    for code in rec["reason_codes"]:
        key = f"reason.{code}"
        if key in _REASON_KEYS:
            reasons.append(t(lang, key, **fmt))
    lines.append(" ".join(reasons))

    if not advice and (tip := _tip(ctx, rec["decision"], crop_id)):
        lines.append(t(lang, "advice_tip", tip=tip))
    if any(m.get("source") == "synthetic" for m in rec["markets"] if m["status"] == "fresh"):
        lines.append(t(lang, "synthetic_note"))
    return "\n\n".join(line for line in lines if line)


_REASON_KEYS = {
    "reason.holding_costs_exceed_expected_rise",
    "reason.prices_flat_or_falling",
    "reason.expected_gain_too_small_for_risk",
    "reason.perishable_crop",
    "reason.some_markets_stale",
    "reason.seasonal_rise",
}
