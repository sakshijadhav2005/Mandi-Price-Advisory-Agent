"""Deterministic answer writer: runs the tools in a fixed order and fills templates.

It answers price and sell/hold questions; government-scheme questions from the structured
scheme entries (with rule-based eligibility questions); pesticide waiting-period questions
from the reviewed CIB&RC list; and weather / spraying / crop-care questions from the
district's IMD agromet bulletin (forecast in the farmer's language; the crop advice text
itself only in English, with a link). Storage and other questions get a short reply
pointing to the local agriculture office or KVK.

Used when no LLM is configured, when the LLM call fails, and when an LLM answer
fails a guardrail (wrong language or numbers not traceable to tool output).
"""

from __future__ import annotations

from datetime import date

from app.agent.tools import ToolContext, run_tool
from app.reference import load_reference
from app.translation.languages import (
    asks_eligibility,
    asks_sell_or_hold,
    days_since_spray,
    is_advisory_question,
    is_pesticide_question,
    is_scheme_question,
    is_weather_question,
)
from app.translation.templates import inr, t


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}/{d.month}"


def agromet_answer(ctx: ToolContext, crop_id: str | None) -> str:
    """This week's district advice: forecast summary in the farmer's language, plus the crop's
    advice (English farmers) or the bulletin link."""
    lang = ctx.language
    res, err = run_tool(ctx, "get_district_advisory", {"crop": crop_id})
    if err:
        return res["error"]
    if not res["available"]:
        return t(lang, "agromet_unavailable", district=res["district"])
    lines = [t(lang, "agromet_header", district=res["district"], issued=_day(res["issued_on"]), valid=_day(res["valid_until"]))]
    forecast = res["forecast"]
    if forecast:
        rainy = [f for f in forecast if (f.get("rain_mm") or 0) > 0]
        if rainy:
            lines.append(t(lang, "agromet_rain", dates=", ".join(_day(f["date"]) for f in rainy), mm=f"{sum(f['rain_mm'] for f in rainy):g}"))
        else:
            lines.append(t(lang, "agromet_dry", days=len(forecast)))
        tmax = [f["tmax_c"] for f in forecast if f.get("tmax_c") is not None]
        tmin = [f["tmin_c"] for f in forecast if f.get("tmin_c") is not None]
        if tmax and tmin:
            lines.append(t(lang, "agromet_temp", tmax_lo=f"{min(tmax):g}", tmax_hi=f"{max(tmax):g}", tmin_lo=f"{min(tmin):g}", tmin_hi=f"{max(tmin):g}"))
    if res["crop_advice"] and lang == "en":  # the bulletin is in English; no machine translation offline
        lines.append(t(lang, "agromet_crop", crop=load_reference().crops[res["crop"]].display(lang), advice=res["crop_advice"]))
    lines.append(t(lang, "agromet_more", url=res["url"]))
    return " ".join(lines)


def scheme_answer(ctx: ToolContext, question: str) -> str | None:
    """A named scheme: what you get, who can get it and how to apply (or, for "am I eligible?",
    the yes/no questions that decide it), with the official link and helpline. A general
    scheme question lists the schemes for the farmer's state. None when no scheme is meant."""
    from app.advisory.schemes import detect_scheme

    lang = ctx.language
    scheme = detect_scheme(question)
    if scheme is None:
        if not is_scheme_question(question):
            return None
        res, err = run_tool(ctx, "list_schemes", {})
        if err:
            return res["error"]
        return t(lang, "scheme_list", state=res["state"], names=", ".join(s["name"] for s in res["schemes"]))
    res, err = run_tool(ctx, "get_scheme", {"scheme": scheme.id})
    if err:
        return res["error"]
    if not res["applies_to_farmer"]:
        return t(lang, "scheme_other_state", name=res["name"], state=res["scheme_state"], farmer_state=res["farmer_state"])
    lines = [t(lang, "scheme_summary", name=res["name"], benefit=res["benefit"])]
    if asks_eligibility(question):
        check, err = run_tool(ctx, "check_scheme_eligibility", {"scheme": scheme.id})
        if not err and check["questions"]:
            lines.append(t(lang, "scheme_check", questions=" ".join(check["questions"])))
        else:
            lines.append(t(lang, "scheme_who", who=res["who"]))
    else:
        # Exclusions are long; they come with "am I eligible?" (as questions) and in the full entry.
        lines.append(t(lang, "scheme_who", who=res["who"]))
        lines.append(t(lang, "scheme_apply", apply=res["apply"]))
    lines.append(t(lang, "scheme_contact", url=res["url"], helpline=res["helpline"]))
    key = "scheme_reviewed" if res["review_status"] == "reviewed" and not res["stale"] else "scheme_draft"
    lines.append(t(lang, key, date=_day(res["info_as_of"])))
    return " ".join(lines)


def named_chemical(ctx: ToolContext, question: str) -> str | None:
    """An approved chemical named in the question ("mancozeb"), if any."""
    from app.advisory.pesticides import approved_chemicals

    lowered = question.lower()
    return next((c for c in sorted(approved_chemicals(ctx.session), key=len, reverse=True) if c in lowered), None)


def pesticide_answer(ctx: ToolContext, crop_id: str, question: str) -> str:
    """Waiting period (and dose, when one use matches) from the reviewed CIB&RC list."""
    from app.advisory.pesticides import base_name

    lang = ctx.language
    crop_name = load_reference().crops[crop_id].display(lang)
    chemical = named_chemical(ctx, question)
    days = days_since_spray(question)
    res, err = run_tool(ctx, "lookup_pesticide", {"crop": crop_id, "chemical": chemical, "pest": None, "days_since_spray": days})
    if err:
        return res["error"]
    if not res["available"]:
        return t(lang, "pesticide_none")
    if chemical is None:
        if not res.get("found"):
            return t(lang, "pesticide_none")
        examples = list(dict.fromkeys(base_name(u["chemical"]) for u in res["uses"]))[:3]
        return t(lang, "pesticide_ask_name", crop=crop_name, examples=", ".join(examples))
    if not res["found"]:
        return t(lang, "pesticide_not_listed", chemical=chemical, crop=crop_name, date=_day(res["list_date"]))
    uses = res["uses"]
    longest = res["longest_waiting_days"]
    listed = _day(res["list_date"])
    # Several products can contain the named chemical (e.g. mancozeb alone or mixed with
    # azoxystrobin), each with its own waiting period: never mix one product's name with
    # another's waiting period.
    products: dict[str, int | None] = {}
    for u in uses:
        days_for = u["waiting_days"]
        if u["chemical"] not in products or (days_for is not None and (products[u["chemical"]] or 0) < days_for):
            products[u["chemical"]] = days_for
    if len(products) > 1:
        items = "; ".join(
            t(lang, "pesticide_item_days", product=p, days=d) if d is not None else t(lang, "pesticide_item_none", product=p)
            for p, d in products.items()
        )
        lines = [t(lang, "pesticide_products", crop=crop_name, chemical=chemical, items=items, date=listed)]
        if longest is not None:
            lines.append(t(lang, "pesticide_longest", days=longest))
    elif longest is None:
        lines = [t(lang, "pesticide_no_wait", chemical=uses[0]["chemical"], crop=crop_name, date=listed)]
    else:
        lines = [t(lang, "pesticide_wait", chemical=uses[0]["chemical"], crop=crop_name, days=longest, date=listed)]
    if len(uses) == 1 and uses[0]["dose_formulation_per_ha"] and uses[0]["dilution_l_per_ha"]:
        u = uses[0]
        lines.append(t(lang, "pesticide_dose", pest=u["pest"], formulation=u["dose_formulation_per_ha"], dilution=u["dilution_l_per_ha"]))
    if "days_left" in res:
        if res["days_left"] == 0:
            lines.append(t(lang, "pesticide_over", n=res["days_since_spray"]))
        else:
            lines.append(t(lang, "pesticide_left", n=res["days_since_spray"], left=res["days_left"], date=_day(res["harvest_from"])))
    lines.append(t(lang, "pesticide_safety"))
    return " ".join(lines)


def rain_note(ctx: ToolContext) -> str | None:
    """One line for a sell/hold answer when the district bulletin forecasts rain."""
    from app.advisory.agromet import current_bulletin
    from app.config import get_settings

    district = load_reference().scope(ctx.district, ctx.farmer_lat, ctx.farmer_lon).district
    if district not in get_settings().agromet_district_list:
        return None
    bulletin = current_bulletin(ctx.session, district, ctx.as_of)
    if bulletin is None:
        return None
    rainy = [f["date"] for f in bulletin.data.get("forecast", []) if (f.get("rain_mm") or 0) > 0 and f["date"] >= ctx.as_of.isoformat()]
    if not rainy:
        return None
    ctx.add_source(
        f"agromet:{district}:{bulletin.issued_on.isoformat()}",
        kind="agromet",
        title=f"IMD agromet advisory, {load_reference().districts[district].name}",
        district=district,
        issued_on=bulletin.issued_on.isoformat(),
        valid_until=bulletin.valid_until.isoformat(),
        url=bulletin.source_url,
        origin="IMD Gramin Krishi Mausam Sewa",
    )
    return t(ctx.language, "agromet_rain_note", dates=", ".join(_day(d) for d in rainy))


def write_answer(
    ctx: ToolContext,
    crop_id: str | None,
    quantity_qtl: float | None = None,
    horizon_days: int | None = None,
    question: str = "",
) -> str:
    ref = load_reference()
    lang = ctx.language
    # Government schemes first: "onion crop insurance" is about insurance, not onion prices.
    if question and (scheme := scheme_answer(ctx, question)):
        return scheme
    weather = bool(question) and is_weather_question(question)
    if not crop_id or crop_id not in ref.crops:
        if question and (is_pesticide_question(question) or named_chemical(ctx, question)):
            return t(lang, "pesticide_which_crop", crops=", ".join(c.display(lang) for c in ref.crops.values()))
        if weather:
            return agromet_answer(ctx, None)
        # No crop: a general question (a scheme, storage of an unknown crop) is out of scope.
        crops = ", ".join(c.display(lang) for c in ref.crops.values())
        if question and not asks_sell_or_hold(question):
            return t(lang, "out_of_scope") + " " + t(lang, "unsupported_crop", crops=crops)
        return t(lang, "unsupported_crop", crops=crops)
    crop = ref.crops[crop_id]
    crop_name = crop.display(lang)
    # Pesticide dose / waiting-period questions come first: harvesting too early is a safety issue.
    if question and (is_pesticide_question(question) or named_chemical(ctx, question)):
        return pesticide_answer(ctx, crop_id, question)
    if weather and not asks_sell_or_hold(question):
        return agromet_answer(ctx, crop_id)

    run_tool(ctx, "check_data_freshness", {"crop": crop_id})
    rec, err = run_tool(
        ctx, "compute_recommendation", {"crop": crop_id, "quantity_qtl": quantity_qtl, "horizon_days": horizon_days}
    )
    if err:
        return rec["error"]

    # Storage / handling questions get the sell-or-hold answer, plus a pointer to local experts;
    # weather + sell/hold questions get this week's district advice first.
    if weather:
        lines: list[str] = [agromet_answer(ctx, crop_id)]
    else:
        lines = [t(lang, "out_of_scope")] if question and is_advisory_question(question) else []
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

    if not weather and (note := rain_note(ctx)):  # the weather answer above already covers rain
        lines.append(note)
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
