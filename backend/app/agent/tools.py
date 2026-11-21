"""Agent tools. Each tool returns a JSON-serialisable dict and records its sources.

The same functions back both the Claude tool-use loop (llm_agent.py) and the
offline answer writer (fallback.py), so the two paths see identical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.agent import decision as decision_mod
from app.agent.data import last_ingestion, load_series
from app.config import get_settings
from app.reference import load_reference


@dataclass
class ToolContext:
    session: Session
    as_of: date
    language: str = "en"
    farmer_lat: float | None = None
    farmer_lon: float | None = None
    default_crop: str | None = None
    district: str | None = None
    default_quantity_qtl: float | None = None
    sources: dict[str, dict] = field(default_factory=dict)  # source_id -> details
    trace: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)  # raw tool results, for grounding checks
    recommendation: dict | None = None

    def add_source(self, source_id: str, **details: Any) -> str:
        self.sources.setdefault(source_id, {"id": source_id, **details})
        return source_id


class ToolError(Exception):
    pass


def _scope(ctx: ToolContext):
    return load_reference().scope(ctx.district, ctx.farmer_lat, ctx.farmer_lon)


def _crop(ctx: ToolContext, crop: str | None):
    ref = load_reference()
    crop_id = (crop or ctx.default_crop or "").lower().strip()
    if crop_id not in ref.crops:
        raise ToolError(f"Unsupported crop {crop!r}. Supported crops: {', '.join(ref.crops)}.")
    return ref.crops[crop_id]


def check_data_freshness(ctx: ToolContext, crop: str | None = None) -> dict:
    settings = get_settings()
    ref = load_reference()
    c = _crop(ctx, crop)
    scope = _scope(ctx)
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=30, markets=scope.market_ids)
    markets = []
    for m in (ref.markets[i] for i in scope.market_ids):
        pts = series.get(m.id, [])
        if not pts:
            markets.append({"market": m.id, "status": "missing", "latest_date": None, "age_days": None})
            continue
        age = (ctx.as_of - pts[-1].price_date).days
        markets.append(
            {
                "market": m.id,
                "status": "fresh" if age <= settings.stale_after_days else "stale",
                "latest_date": pts[-1].price_date.isoformat(),
                "age_days": age,
                "source": pts[-1].source,
            }
        )
    fresh = [m for m in markets if m["status"] == "fresh"]
    return {
        "crop": c.id,
        "as_of": ctx.as_of.isoformat(),
        "stale_after_days": settings.stale_after_days,
        "fresh_markets": len(fresh),
        "total_markets": len(markets),
        "usable": bool(fresh),
        "markets": markets,
        "last_ingestion": last_ingestion(ctx.session),
    }


def get_mandi_prices(ctx: ToolContext, crop: str | None = None, market: str | None = None, days: int | None = 7) -> dict:
    ref = load_reference()
    c = _crop(ctx, crop)
    if market and market not in ref.markets:
        raise ToolError(f"Unknown market {market!r}. Nearby markets: {', '.join(_scope(ctx).market_ids)}.")
    days = max(1, min(days or 7, 30))
    allowed = {market} if market else set(_scope(ctx).market_ids)
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=days, markets=allowed)
    out = []
    for m_id, pts in series.items():
        if m_id not in allowed:
            continue
        latest = pts[-1]
        sid = ctx.add_source(
            f"price:{c.id}:{m_id}:{latest.price_date.isoformat()}",
            kind="price",
            crop=c.id,
            market=m_id,
            market_name=ref.markets[m_id].name,
            date=latest.price_date.isoformat(),
            origin=latest.source,
        )
        out.append(
            {
                "source_id": sid,
                "market": m_id,
                "market_name": ref.markets[m_id].name,
                "latest": {
                    "date": latest.price_date.isoformat(),
                    "min": latest.min_price,
                    "modal": latest.modal_price,
                    "max": latest.max_price,
                    "arrivals_tonnes": latest.arrivals_tonnes,
                },
                "history_modal": [[p.price_date.isoformat(), p.modal_price] for p in pts],
                "data_origin": latest.source,
            }
        )
    return {"crop": c.id, "unit": "Rs per quintal", "as_of": ctx.as_of.isoformat(), "days": days, "markets": out}


def get_district_advisory(ctx: ToolContext, crop: str | None = None) -> dict:
    """This week's IMD agromet advisory for the farmer's district: forecast, weather summary
    and the advice for the crop. Only a bulletin that is still valid is ever returned."""
    from app.advisory.agromet import current_bulletin

    ref = load_reference()
    district = _scope(ctx).district
    name = ref.districts[district].names.get(ctx.language, ref.districts[district].name)
    if district not in get_settings().agromet_district_list:
        return {"available": False, "district": name, "reason": "District farm advice is not available for this district yet."}
    bulletin = current_bulletin(ctx.session, district, ctx.as_of)
    if bulletin is None:
        return {"available": False, "district": name, "reason": "There is no current IMD bulletin for this district (the last one has expired)."}
    crop_id = _crop(ctx, crop).id if (crop or ctx.default_crop) else None
    data = bulletin.data
    forecast = [
        {**f, "day": date.fromisoformat(f["date"]).day, "month": date.fromisoformat(f["date"]).month} for f in data.get("forecast", [])
    ]
    source_id = ctx.add_source(
        f"agromet:{district}:{bulletin.issued_on.isoformat()}",
        kind="agromet",
        title=f"IMD agromet advisory, {name}",
        district=district,
        issued_on=bulletin.issued_on.isoformat(),
        valid_until=bulletin.valid_until.isoformat(),
        url=bulletin.source_url,
        origin="IMD Gramin Krishi Mausam Sewa",
    )
    return {
        "available": True,
        "district": name,
        "issued_on": bulletin.issued_on.isoformat(),
        "valid_until": bulletin.valid_until.isoformat(),
        "source_id": source_id,
        "url": bulletin.source_url,
        "forecast": forecast,
        "rain_days": [f["date"] for f in forecast if (f.get("rain_mm") or 0) > 0],
        "weather_summary": data.get("sections", {}).get("weather_summary", ""),
        "extended_range": data.get("sections", {}).get("extended_range", ""),
        "crop": crop_id,
        "crop_advice": data.get("crops", {}).get(crop_id) if crop_id else None,
        "general_advisory": data.get("sections", {}).get("general", "")[:1500],
    }


def lookup_pesticide(
    ctx: ToolContext, crop: str | None = None, chemical: str | None = None, pest: str | None = None, days_since_spray: int | None = None
) -> dict:
    """Approved uses of a pesticide on a crop from the reviewed CIB&RC list: dose and the
    waiting period between the last spray and harvest. Only reviewer-approved rows are used."""
    from datetime import timedelta

    from app.advisory.pesticides import PPQS_PAGE, find_uses

    c = _crop(ctx, crop)
    list_date, rows = find_uses(ctx.session, c.id, chemical, pest)
    if list_date is None:
        return {"available": False, "crop": c.id, "reason": "No reviewed pesticide list yet: follow the waiting period on the product label."}
    source_id = ctx.add_source(
        f"pesticide:{list_date.isoformat()}:{c.id}",
        kind="pesticide",
        title="CIB&RC major uses of pesticides",
        list_date=list_date.isoformat(),
        url=PPQS_PAGE,
        origin="CIB&RC, Ministry of Agriculture",
    )
    out: dict = {"available": True, "crop": c.id, "chemical_asked": chemical, "list_date": list_date.isoformat(), "source_id": source_id}
    if not rows:
        return out | {"found": False, "reason": "Not listed for this crop in the reviewed list."}
    waits = [r.waiting_days for r in rows if r.waiting_days is not None]
    longest = max(waits) if waits else None
    out |= {
        "found": True,
        "uses": [
            {
                "chemical": r.chemical,
                "pest": r.pest,
                "dose_ai_per_ha": r.dose_ai_per_ha,
                "dose_formulation_per_ha": r.dose_formulation_per_ha,
                "dilution_l_per_ha": r.dilution_l_per_ha,
                "waiting_days": r.waiting_days,
            }
            for r in rows
        ],
        "longest_waiting_days": longest,  # the safe waiting period when several uses match
    }
    if days_since_spray is not None and longest is not None:
        days = max(0, int(days_since_spray))
        out |= {
            "days_since_spray": days,
            "days_left": max(0, longest - days),
            "harvest_from": (ctx.as_of - timedelta(days=days) + timedelta(days=longest)).isoformat(),
        }
    return out


def _farmer_state(ctx: ToolContext) -> str:
    return load_reference().districts[_scope(ctx).district].state


def _scheme(ctx: ToolContext, scheme: str):
    from app.advisory.schemes import detect_scheme, load_schemes

    found = load_schemes().get((scheme or "").strip().lower()) or detect_scheme(scheme or "")
    if found is None:
        raise ToolError(f"Unknown scheme {scheme!r}. Known schemes: {', '.join(load_schemes())}.")
    return found


def _scheme_source(ctx: ToolContext, s) -> str:
    return ctx.add_source(
        f"scheme:{s.id}",
        kind="scheme",
        title=s.name(ctx.language),
        info_as_of=s.info_as_of.isoformat(),
        review_status=s.review_status,
        url=s.url,
        helpline=s.helpline,
        origin="Official scheme guidelines",
    )


def list_schemes(ctx: ToolContext) -> dict:
    """Government schemes that apply to the farmer: central ones and the farmer's state's."""
    from app.advisory.schemes import schemes_for_state

    state = _farmer_state(ctx)
    return {
        "state": state,
        "schemes": [
            {"id": s.id, "name": s.name(ctx.language), "category": s.category, "benefit": s.texts(ctx.language)["benefit"]}
            for s in schemes_for_state(state)
        ],
    }


def get_scheme(ctx: ToolContext, scheme: str) -> dict:
    """One scheme's details in the farmer's language, with the official link and helpline."""
    s = _scheme(ctx, scheme)
    state = _farmer_state(ctx)
    return {
        "id": s.id,
        "name": s.name(ctx.language),
        "applies_to_farmer": s.applies_to(state),
        "scheme_state": s.state,
        "farmer_state": state,
        **s.texts(ctx.language),
        "url": s.url,
        "helpline": s.helpline,
        "info_as_of": s.info_as_of.isoformat(),
        "review_status": s.review_status,
        "stale": s.is_stale(ctx.as_of),
        "source_id": _scheme_source(ctx, s),
    }


ELIGIBILITY_FACTS = (
    "owns_land", "cultivates", "income_tax_payer", "govt_employee", "pension_10k", "professional", "public_office",
    "pm_kisan_beneficiary", "grows_notified_crop", "had_solar_pump_before", "micro_irrigation_subsidy_last_7_years",
)


def check_scheme_eligibility(ctx: ToolContext, scheme: str, **facts: bool | None) -> dict:
    """Rule-based eligibility: eligible / not_eligible (reasons) / depends (questions to ask)."""
    from app.advisory.schemes import check_eligibility

    s = _scheme(ctx, scheme)
    unknown = set(facts) - set(ELIGIBILITY_FACTS)
    if unknown:
        raise ToolError(f"Unknown facts: {', '.join(sorted(unknown))}")
    result = check_eligibility(s, facts, ctx.language)
    if not s.applies_to(_farmer_state(ctx)):
        result = result | {"verdict": "not_eligible", "reasons": [f"{s.name(ctx.language)} is only for {s.state}"], "questions": []}
    return result | {"name": s.name(ctx.language), "url": s.url, "helpline": s.helpline, "source_id": _scheme_source(ctx, s)}


def estimate_transport_cost(ctx: ToolContext, market: str, quantity_qtl: float | None = None) -> dict:
    ref = load_reference()
    scope = _scope(ctx)
    if market not in ref.markets:
        raise ToolError(f"Unknown market {market!r}. Nearby markets: {', '.join(scope.market_ids)}.")
    km, per_qtl = decision_mod.transport_cost_per_qtl(ref, market, scope.lat, scope.lon)
    qty = quantity_qtl or ctx.default_quantity_qtl
    return {
        "market": market,
        "road_distance_km_estimate": km,
        "transport_per_qtl": per_qtl,
        "market_fees_pct": ref.market_fees_pct,
        "quantity_qtl": qty,
        "transport_total": round(per_qtl * qty, 0) if qty else None,
        "farmer_location_is_default": not scope.location_known,
        "note": "Estimate from straight-line distance x road factor and assumed per-quintal rates.",
    }


def compute_recommendation(
    ctx: ToolContext, crop: str | None = None, quantity_qtl: float | None = None, horizon_days: int | None = None
) -> dict:
    settings = get_settings()
    ref = load_reference()
    c = _crop(ctx, crop)
    # A year and a bit of history: the last 30 days for the trend, last year's
    # same window for the seasonal signal.
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=400, markets=_scope(ctx).market_ids)
    rec = decision_mod.recommend(
        c,
        series,
        ctx.as_of,
        ref,
        farmer_lat=ctx.farmer_lat,
        farmer_lon=ctx.farmer_lon,
        quantity_qtl=quantity_qtl or ctx.default_quantity_qtl,
        horizon_days=horizon_days,
        stale_after_days=settings.stale_after_days,
        min_points=settings.min_price_points,
        district=ctx.district,
    ).to_dict()
    for m in rec["markets"]:
        if m["status"] == "fresh":
            ctx.add_source(
                f"price:{c.id}:{m['market']}:{m['latest_date']}",
                kind="price",
                crop=c.id,
                market=m["market"],
                market_name=ref.markets[m["market"]].name,
                date=m["latest_date"],
                origin=m["source"],
            )
    ctx.recommendation = rec
    return rec


TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "check_data_freshness": check_data_freshness,
    "get_mandi_prices": get_mandi_prices,
    "estimate_transport_cost": estimate_transport_cost,
    "get_district_advisory": get_district_advisory,
    "lookup_pesticide": lookup_pesticide,
    "list_schemes": list_schemes,
    "get_scheme": get_scheme,
    "check_scheme_eligibility": check_scheme_eligibility,
    "compute_recommendation": compute_recommendation,
}


def _nullable(t: str, **kw) -> dict:
    return {"type": [t, "null"], **kw}


def tool_schemas() -> list[dict]:
    """Tool definitions for the Messages API (strict mode: every field required, optional ones nullable)."""
    ref = load_reference()
    crops = list(ref.crops)
    crop_prop = _nullable("string", enum=[*crops, None], description="Crop id. Null uses the crop from the conversation.")
    return [
        {
            "name": "check_data_freshness",
            "description": "Report how recent the latest price report is for each nearby mandi, and whether any market has usable (fresh) data. Call this first for any price or sell/hold question.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"crop": crop_prop},
                "required": ["crop"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_mandi_prices",
            "description": "Get recent daily min/modal/max prices (Rs per quintal) for a crop at nearby mandis, with a source_id per market.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "crop": crop_prop,
                    "market": _nullable("string", description="One market id from the nearby markets listed in the question, or null for all of them."),
                    "days": _nullable("integer", description="Days of history, 1-30. Null means 7."),
                },
                "required": ["crop", "market", "days"],
                "additionalProperties": False,
            },
        },
        {
            "name": "estimate_transport_cost",
            "description": "Estimate transport cost per quintal (and total, if quantity is known) from the farmer to a market.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "market": {"type": "string", "description": "A market id from the nearby markets listed in the question."},
                    "quantity_qtl": _nullable("number", description="Quantity in quintals, or null."),
                },
                "required": ["market", "quantity_qtl"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_schemes",
            "description": "Government schemes the farmer can use: central schemes and their own state's, with a one-line benefit each. Use it when the farmer asks about schemes in general.",
            "strict": True,
            "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
        {
            "name": "get_scheme",
            "description": "One government scheme's details in the farmer's language: benefit, who can get it, who cannot, documents, how to apply, official url and helpline, info_as_of and review_status.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"scheme": {"type": "string", "description": "Scheme id from list_schemes, or its name."}},
                "required": ["scheme"],
                "additionalProperties": False,
            },
        },
        {
            "name": "check_scheme_eligibility",
            "description": "Rule-based eligibility for a scheme. Pass what the farmer told you as true/false and null for anything unknown. Returns verdict eligible / not_eligible (with reasons) / depends (with the exact questions to ask) / open.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "scheme": {"type": "string", "description": "Scheme id or name."},
                    **{f: _nullable("boolean") for f in ELIGIBILITY_FACTS},
                },
                "required": ["scheme", *ELIGIBILITY_FACTS],
                "additionalProperties": False,
            },
        },
        {
            "name": "lookup_pesticide",
            "description": "Approved uses of a pesticide on a crop from the official, reviewed CIB&RC list: pest, dose per hectare and the waiting period (days between the last spray and harvest). Use it for any question about which chemical, what dose, or when sprayed produce can be harvested or sold. With days_since_spray it returns days_left and harvest_from. Returns available=false when no reviewed list exists.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "crop": crop_prop,
                    "chemical": _nullable("string", description="Chemical name as the farmer said it, in English letters (e.g. mancozeb), or null."),
                    "pest": _nullable("string", description="Pest or disease in English (e.g. late blight), or null."),
                    "days_since_spray": _nullable("integer", description="Days since the last spray, if the farmer said, else null."),
                },
                "required": ["crop", "chemical", "pest", "days_since_spray"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_district_advisory",
            "description": "This week's official farm advice for the farmer's district from the IMD agromet advisory bulletin (Gramin Krishi Mausam Sewa): 5-day forecast (rain, temperature), weather summary, extended outlook, general advice and the advice for the crop. Use it for weather, rain, spraying, irrigation and crop-care questions, and to warn about rain in a sell/hold answer. Returns available=false when there is no valid bulletin.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"crop": crop_prop},
                "required": ["crop"],
                "additionalProperties": False,
            },
        },
        {
            "name": "compute_recommendation",
            "description": "Compute the sell / hold / insufficient_data recommendation with confidence, best market, net prices after transport, fees, storage cost and storage loss. This is the only source of the recommendation; always call it before answering a sell/hold question.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "crop": crop_prop,
                    "quantity_qtl": _nullable("number", description="Quantity in quintals, or null."),
                    "horizon_days": _nullable("integer", description="How many days the farmer could hold. Null uses the crop default."),
                },
                "required": ["crop", "quantity_qtl", "horizon_days"],
                "additionalProperties": False,
            },
        },
    ]


def simplify_schema(schema: dict) -> dict:
    """Plain JSON Schema for OpenAI-style APIs: no nullable type arrays, optional fields not required."""
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


def function_tools(names: set[str] | None = None) -> list[dict]:
    """The tools in OpenAI "function" format (Ollama, Gemini, Groq, OpenRouter), optionally a subset."""
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": simplify_schema(t["input_schema"])}}
        for t in tool_schemas()
        if names is None or t["name"] in names
    ]


def complete_args(name: str, args: dict) -> dict:
    """Keep only the tool's parameters; ones the model left out are null (all are nullable or required)."""
    schema = next((t["input_schema"] for t in tool_schemas() if t["name"] == name), None)
    return {p: args.get(p) for p in schema["properties"]} if schema else args


def run_tool(ctx: ToolContext, name: str, args: dict) -> tuple[dict, bool]:
    """Execute a tool. Returns (result, is_error) and appends to the trace."""
    func = TOOL_FUNCS.get(name)
    if func is None:
        result, is_error = {"error": f"Unknown tool {name!r}"}, True
    else:
        try:
            result, is_error = func(ctx, **(args or {})), False
        except ToolError as exc:
            result, is_error = {"error": str(exc)}, True
        except TypeError as exc:  # bad / missing arguments
            result, is_error = {"error": f"Invalid arguments: {exc}"}, True
    ctx.trace.append({"tool": name, "args": args, "is_error": is_error, "summary": _summarise(name, result)})
    if not is_error:
        ctx.outputs.append(result)
    return result, is_error


def _summarise(name: str, result: dict) -> str:
    if "error" in result:
        return result["error"]
    if name == "check_data_freshness":
        return f"{result['fresh_markets']}/{result['total_markets']} markets fresh"
    if name == "get_mandi_prices":
        return f"{len(result['markets'])} markets"
    if name == "list_schemes":
        return f"{len(result['schemes'])} schemes for {result['state']}"
    if name == "get_scheme":
        return f"{result['id']} ({result['review_status']}, as of {result['info_as_of']})"
    if name == "check_scheme_eligibility":
        return f"{result['scheme']}: {result['verdict']}"
    if name == "lookup_pesticide":
        if not result.get("available"):
            return "no reviewed pesticide list"
        return f"{len(result.get('uses', []))} approved uses, list of {result['list_date']}"
    if name == "get_district_advisory":
        return f"IMD bulletin of {result['issued_on']}" if result.get("available") else "no valid district bulletin"
    if name == "estimate_transport_cost":
        return f"Rs {result['transport_per_qtl']}/qtl to {result['market']}"
    if name == "compute_recommendation":
        return f"{result['decision']} ({result['confidence']})"
    return ""
