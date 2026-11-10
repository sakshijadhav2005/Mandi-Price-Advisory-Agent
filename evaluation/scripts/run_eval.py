"""Evaluate the agent against baselines on the labelled decision points.

Two parts:

1. Decision evaluation (fast, no LLM): the recommendation engine vs always-sell,
   always-hold and the "sell if above the 7-day average" rule. Reports accuracy
   with bootstrap 95% CIs, realised value per quintal and regret against an
   oracle, insufficient-data rate on simulated feed outages, and calibration
   by confidence level.
2. Pipeline evaluation per language (--pipeline N): full answer_query on
   farmer-style questions in English, Hindi and Marathi. Checks crop
   understanding, decision consistency, answer language, number grounding,
   citation validity and latency. Add --llm to use Claude (costs money;
   needs credentials); without it the offline answer writer is evaluated.

Usage (from the repo root):
    python evaluation/scripts/run_eval.py --pipeline 10 [--llm]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_test_set import OUT as TEST_SET  # noqa: E402
from build_test_set import load_full_series  # noqa: E402

from app.agent.data import slice_series  # noqa: E402
from app.agent.decision import baseline_above_7d_avg, recommend  # noqa: E402
from app.agent.guardrails import language_ok, ungrounded_numbers  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.reference import load_reference  # noqa: E402

REPORT_DIR = ROOT / "evaluation" / "reports"

QUESTIONS = {
    "en": [
        "Should I sell my {crop_en} now or wait?",
        "I have 15 quintals of {crop_en}. Sell today or hold?",
        "What is the best mandi to sell {crop_en} this week?",
    ],
    "hi": [
        "क्या मुझे अपना {crop_hi} अभी बेचना चाहिए या रुकना चाहिए?",
        "मेरे पास 15 क्विंटल {crop_hi} है, आज बेचूं या रोकूं?",
        "इस हफ्ते {crop_hi} बेचने के लिए सबसे अच्छी मंडी कौन सी है?",
    ],
    "mr": [
        "मी माझा {crop_mr} आता विकू की थांबू?",
        "माझ्याकडे 15 क्विंटल {crop_mr} आहे, आज विकू की साठवू?",
        "या आठवड्यात {crop_mr} विकायला सर्वात चांगला बाजार कोणता?",
    ],
}


def bootstrap_ci(hits: list[int], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not hits:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(hits, k=len(hits))) / len(hits) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def decision_eval(points: list[dict]) -> dict:
    ref = load_reference()
    s = get_settings()
    full = {c: load_full_series(c) for c in ref.crops}
    policies = ["agent", "always_sell", "always_hold", "above_7d_avg_rule"]
    rows = []
    for pt in points:
        crop = ref.crops[pt["crop"]]
        as_of = date.fromisoformat(pt["as_of"])
        district = pt.get("district") or ref.default_district.id
        ids = set(ref.districts[district].market_ids)
        series = {m: p for m, p in slice_series(full[pt["crop"]], as_of, 400).items() if m in ids}
        if pt["case"] == "outage":
            cutoff = as_of - timedelta(days=pt["outage_days"])
            series = {m: [p for p in pts if p.price_date <= cutoff] for m, pts in series.items()}
            series = {m: pts for m, pts in series.items() if pts}
        rec = recommend(
            crop, series, as_of, ref, horizon_days=pt["horizon_days"], stale_after_days=s.stale_after_days,
            min_points=s.min_price_points, district=district,
        )
        rows.append(
            {
                **pt,
                "pred": {
                    "agent": rec.decision,
                    "always_sell": "sell",
                    "always_hold": "hold",
                    "above_7d_avg_rule": baseline_above_7d_avg(series, as_of),
                },
                "confidence": rec.confidence,
            }
        )

    normal = [r for r in rows if r["case"] == "normal"]
    outage = [r for r in rows if r["case"] == "outage"]
    out: dict = {"n_normal": len(normal), "n_outage": len(outage), "policies": {}, "per_crop": {}, "calibration": {}}

    def value(r: dict, decision: str) -> float:
        # insufficient_data -> the farmer checks the mandi and sells (value of selling now)
        return r["realised_net_hold"] if decision == "hold" else r["realised_net_now"]

    for pol in policies:
        hits = [int(r["pred"][pol] == r["label"]) for r in normal]
        answered = [r for r in normal if r["pred"][pol] != "insufficient_data"]
        lo, hi = bootstrap_ci(hits)
        oracle = [max(r["realised_net_now"], r["realised_net_hold"]) for r in normal]
        vals = [value(r, r["pred"][pol]) for r in normal]
        out["policies"][pol] = {
            "accuracy": sum(hits) / len(hits) if hits else 0.0,
            "ci95": [lo, hi],
            "coverage": len(answered) / len(normal) if normal else 0.0,
            "accuracy_when_answered": (sum(int(r["pred"][pol] == r["label"]) for r in answered) / len(answered)) if answered else 0.0,
            "hold_rate": sum(r["pred"][pol] == "hold" for r in normal) / len(normal) if normal else 0.0,
            "mean_value_per_qtl": statistics.fmean(vals) if vals else 0.0,
            "mean_regret_per_qtl": statistics.fmean(o - v for o, v in zip(oracle, vals)) if vals else 0.0,
            "outage_insufficient_rate": (sum(r["pred"][pol] == "insufficient_data" for r in outage) / len(outage)) if outage else None,
        }
        for crop in [f"{d}/{c}" for d in ref.districts for c in ref.crops]:
            cr = [r for r in normal if f"{r.get('district', ref.default_district.id)}/{r['crop']}" == crop]
            if cr:
                out["per_crop"].setdefault(crop, {})[pol] = sum(int(r["pred"][pol] == r["label"]) for r in cr) / len(cr)

    for level in ("high", "medium", "low"):
        bucket = [r for r in normal if r["confidence"] == level and r["pred"]["agent"] != "insufficient_data"]
        out["calibration"][level] = {
            "n": len(bucket),
            "accuracy": sum(int(r["pred"]["agent"] == r["label"]) for r in bucket) / len(bucket) if bucket else None,
        }
    out["label_hold_share"] = sum(r["label"] == "hold" for r in normal) / len(normal) if normal else 0.0
    failures = [r for r in normal if r["pred"]["agent"] != r["label"]]
    failures.sort(key=lambda r: -abs(r["realised_net_hold"] - r["realised_net_now"]))
    out["worst_failures"] = [
        {k: r[k] for k in ("id", "label", "confidence", "realised_net_now", "realised_net_hold")} | {"agent": r["pred"]["agent"]}
        for r in failures[:8]
    ]
    return out


def pipeline_eval(points: list[dict], per_crop: int, use_llm: bool) -> dict:
    from sqlalchemy import select

    from app.agent.service import answer_query
    from app.db.models import Price
    from app.db.session import session_scope
    from app.retrieval.index import get_index

    ref = load_reference()
    chunk_ids = {c.chunk_id for c in get_index().chunks}
    rng = random.Random(3)
    chosen = []
    for crop in ref.crops:
        normal = [p for p in points if p["crop"] == crop and p["case"] == "normal"]
        chosen += rng.sample(normal, min(per_crop, len(normal)))

    full = {c: load_full_series(c) for c in ref.crops}
    per_lang: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    with session_scope() as s:
        for pt in chosen:
            crop = ref.crops[pt["crop"]]
            names = {"crop_en": crop.name.lower(), "crop_hi": crop.names["hi"], "crop_mr": crop.names["mr"]}
            as_of = date.fromisoformat(pt["as_of"])
            district = pt.get("district") or ref.default_district.id
            engine = recommend(
                crop, slice_series(full[crop.id], as_of, 400), as_of, ref, stale_after_days=get_settings().stale_after_days, district=district
            )
            for lang, templates in QUESTIONS.items():
                q = rng.choice(templates).format(**names)
                ans = answer_query(s, q, language=lang, as_of=as_of, use_llm=use_llm, district=district)
                m = per_lang[lang]
                m["crop_understood"].append(int(bool(ans.recommendation) and ans.recommendation["crop"] == crop.id))
                m["decision_consistent"].append(int(ans.decision == engine.decision))
                m["language_ok"].append(int(language_ok(ans.text, lang)))
                m["grounded"].append(int(not ungrounded_numbers(ans.text, [ans.recommendation or {}, *ans.sources])))
                valid = 0
                for src in ans.sources:
                    if src["kind"] == "price":
                        valid += bool(
                            s.scalar(select(Price.id).where(Price.crop == src["crop"], Price.market == src["market"], Price.price_date == date.fromisoformat(src["date"])).limit(1))
                        )
                    else:
                        valid += src["id"].removeprefix("advisory:") in chunk_ids
                m["citation_valid"].append(valid / len(ans.sources) if ans.sources else 0.0)
                m["has_sources"].append(int(bool(ans.sources)))
                m["llm_used"].append(int(ans.mode == "llm"))
                m["latency_ms"].append(ans.latency_ms)
                m["input_tokens"].append(ans.usage.get("input_tokens", 0))
                m["output_tokens"].append(ans.usage.get("output_tokens", 0))
    summary = {}
    for lang, m in per_lang.items():
        summary[lang] = {k: statistics.fmean(v) for k, v in m.items() if v}
        summary[lang]["n"] = len(m["latency_ms"])
        summary[lang]["p95_latency_ms"] = sorted(m["latency_ms"])[int(0.95 * (len(m["latency_ms"]) - 1))]
    return summary


def write_report(dec: dict, pipe: dict | None, use_llm: bool) -> Path:
    origin = "synthetic"
    lines = [
        "# Evaluation results",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. Price data origin: **{origin}** "
        "(see backend/app/ingestion/synthetic.py). These numbers test the pipeline; they say nothing about "
        "real-market performance until the test set is rebuilt from Agmarknet data.",
        "",
        f"## Sell/hold decisions ({dec['n_normal']} decision points, {dec['n_outage']} simulated feed outages)",
        "",
        f"Share of points where holding was actually better: {pct(dec['label_hold_share'])}.",
        "",
        "| Policy | Accuracy (95% CI) | Hold rate | Value ₹/qtl | Regret ₹/qtl | Says 'insufficient data' on outages |",
        "|---|---|---|---|---|---|",
    ]
    for pol, p in dec["policies"].items():
        out_rate = "-" if p["outage_insufficient_rate"] is None else pct(p["outage_insufficient_rate"])
        lines.append(
            f"| {pol} | {pct(p['accuracy'])} ({pct(p['ci95'][0])}–{pct(p['ci95'][1])}) | {pct(p['hold_rate'])} | "
            f"{p['mean_value_per_qtl']:.0f} | {p['mean_regret_per_qtl']:.1f} | {out_rate} |"
        )
    lines += ["", "Value is the realised net price per quintal of following the policy; regret is the gap to the best choice in hindsight.", ""]
    lines += ["### Accuracy per district and crop", "", "| District / crop | " + " | ".join(dec["policies"]) + " |", "|---|" + "---|" * len(dec["policies"])]
    for crop, accs in dec["per_crop"].items():
        lines.append(f"| {crop} | " + " | ".join(pct(accs[p]) for p in dec["policies"]) + " |")
    lines += ["", "### Calibration (agent)", "", "| Confidence | n | Accuracy |", "|---|---|---|"]
    for level, c in dec["calibration"].items():
        lines.append(f"| {level} | {c['n']} | {'-' if c['accuracy'] is None else pct(c['accuracy'])} |")
    lines += ["", "### Largest misses", "", "| Point | Label | Agent | Confidence | Net now | Net after hold |", "|---|---|---|---|---|---|"]
    for f in dec["worst_failures"]:
        lines.append(f"| {f['id']} | {f['label']} | {f['agent']} | {f['confidence']} | {f['realised_net_now']:.0f} | {f['realised_net_hold']:.0f} |")
    if pipe:
        lines += [
            "",
            f"## Full pipeline per language ({'Claude' if use_llm else 'offline answer writer'})",
            "",
            "| Language | n | Crop understood | Decision matches engine | Answer language OK | Numbers grounded | Valid citations | LLM answer used | Mean latency ms | p95 latency ms | Mean tokens in/out |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for lang, m in pipe.items():
            lines.append(
                f"| {lang} | {m['n']} | {pct(m['crop_understood'])} | {pct(m['decision_consistent'])} | {pct(m['language_ok'])} | "
                f"{pct(m['grounded'])} | {pct(m['citation_valid'])} | {pct(m['llm_used'])} | {m['latency_ms']:.0f} | {m['p95_latency_ms']} | "
                f"{m['input_tokens']:.0f}/{m['output_tokens']:.0f} |"
            )
        lines += ["", "Answer quality per language still needs rating by native-speaking reviewers (plan section 10)."]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "results.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORT_DIR / "results.json").write_text(json.dumps({"decision": dec, "pipeline": pipe}, indent=2), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", type=int, default=0, help="decision points per crop for the per-language pipeline eval")
    ap.add_argument("--llm", action="store_true", help="use Claude in the pipeline eval (needs credentials, costs money)")
    args = ap.parse_args()
    if not TEST_SET.exists():
        raise SystemExit("Test set missing. Run evaluation/scripts/build_test_set.py first.")
    points = [json.loads(line) for line in TEST_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    dec = decision_eval(points)
    pipe = pipeline_eval(points, args.pipeline, args.llm) if args.pipeline else None
    path = write_report(dec, pipe, args.llm)
    sys.stdout.reconfigure(encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
