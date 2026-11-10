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
from app.retrieval.index import get_index


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
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=30)
    markets = []
    for m in (ref.markets[i] for i in _scope(ctx).market_ids):
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
        raise ToolError(f"Unknown market {market!r}. Known markets: {', '.join(ref.markets)}.")
    days = max(1, min(days or 7, 30))
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=days, market=market)
    allowed = {market} if market else set(_scope(ctx).market_ids)
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


def search_advisories(ctx: ToolContext, query: str, crop: str | None = None) -> dict:
    crop_id = None
    if crop or ctx.default_crop:
        crop_id = _crop(ctx, crop).id
    hits = get_index().search(query, crop=crop_id, language=ctx.language, k=3)
    for h in hits:
        h["source_id"] = ctx.add_source(
            f"advisory:{h['chunk_id']}",
            kind="advisory",
            title=h["title"],
            language=h["language"],
            published=h["published"],
            origin=h["source"],
            excerpt=h["text"][:280],
        )
    return {"query": query, "results": hits}


def estimate_transport_cost(ctx: ToolContext, market: str, quantity_qtl: float | None = None) -> dict:
    ref = load_reference()
    if market not in ref.markets:
        raise ToolError(f"Unknown market {market!r}. Known markets: {', '.join(ref.markets)}.")
    scope = _scope(ctx)
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
    series = load_series(ctx.session, c.id, ctx.as_of, lookback_days=400)
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
    "search_advisories": search_advisories,
    "estimate_transport_cost": estimate_transport_cost,
    "compute_recommendation": compute_recommendation,
}


def _nullable(t: str, **kw) -> dict:
    return {"type": [t, "null"], **kw}


def tool_schemas() -> list[dict]:
    """Tool definitions for the Messages API (strict mode: every field required, optional ones nullable)."""
    ref = load_reference()
    crops = list(ref.crops)
    markets = list(ref.markets)
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
                    "market": _nullable("string", enum=[*markets, None], description="One market id, or null for all nearby markets."),
                    "days": _nullable("integer", description="Days of history, 1-30. Null means 7."),
                },
                "required": ["crop", "market", "days"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search_advisories",
            "description": "Search crop advisory bulletins (storage, quality, handling, market practice). Bulletins exist in English, Hindi and Marathi; write the query in English for best coverage.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "crop": crop_prop},
                "required": ["query", "crop"],
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
                    "market": {"type": "string", "enum": markets},
                    "quantity_qtl": _nullable("number", description="Quantity in quintals, or null."),
                },
                "required": ["market", "quantity_qtl"],
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
    if name == "search_advisories":
        return f"{len(result['results'])} advisory passages"
    if name == "estimate_transport_cost":
        return f"Rs {result['transport_per_qtl']}/qtl to {result['market']}"
    if name == "compute_recommendation":
        return f"{result['decision']} ({result['confidence']})"
    return ""
