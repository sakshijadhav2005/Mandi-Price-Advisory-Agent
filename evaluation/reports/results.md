# Evaluation results

Generated 2026-11-08 23:30. Price data origin: **synthetic** (see backend/app/ingestion/synthetic.py). These numbers test the pipeline; they say nothing about real-market performance until the test set is rebuilt from Agmarknet data.

## Sell/hold decisions (600 decision points, 120 simulated feed outages)

Share of points where holding was actually better: 28.2%.

| Policy | Accuracy (95% CI) | Hold rate | Value ₹/qtl | Regret ₹/qtl | Says 'insufficient data' on outages |
|---|---|---|---|---|---|
| agent | 75.2% (71.5%–78.5%) | 11.3% | 1609 | 22.6 | 100.0% |
| always_sell | 71.8% (68.2%–75.2%) | 0.0% | 1607 | 24.7 | 0.0% |
| always_hold | 28.2% (24.8%–31.8%) | 100.0% | 1524 | 107.6 | 0.0% |
| above_7d_avg_rule | 43.2% (39.2%–47.2%) | 43.7% | 1562 | 69.2 | 0.0% |

Value is the realised net price per quintal of following the policy; regret is the gap to the best choice in hindsight.

### Accuracy per district and crop

| District / crop | agent | always_sell | always_hold | above_7d_avg_rule |
|---|---|---|---|---|
| nashik/onion | 65.0% | 63.0% | 37.0% | 35.0% |
| nashik/tomato | 99.0% | 99.0% | 1.0% | 62.0% |
| nashik/potato | 69.0% | 58.0% | 42.0% | 36.0% |
| pune/onion | 62.0% | 60.0% | 40.0% | 37.0% |
| pune/tomato | 97.0% | 97.0% | 3.0% | 52.0% |
| pune/potato | 59.0% | 54.0% | 46.0% | 37.0% |

### Calibration (agent)

| Confidence | n | Accuracy |
|---|---|---|
| high | 303 | 93.4% |
| medium | 112 | 70.5% |
| low | 185 | 48.1% |

### Largest misses

| Point | Label | Agent | Confidence | Net now | Net after hold |
|---|---|---|---|---|---|
| nashik-potato-2025-10-26 | hold | sell | low | 1712 | 2208 |
| pune-potato-2025-10-19 | hold | sell | high | 1750 | 2226 |
| pune-potato-2025-10-26 | hold | sell | low | 1817 | 2283 |
| pune-potato-2025-10-20 | hold | sell | medium | 1804 | 2241 |
| nashik-potato-2025-08-07 | hold | sell | low | 1388 | 1692 |
| nashik-potato-2025-10-13 | hold | sell | high | 1723 | 2003 |
| pune-potato-2025-07-26 | hold | sell | medium | 1396 | 1676 |
| pune-potato-2025-07-31 | hold | sell | low | 1433 | 1712 |

## Full pipeline per language (offline answer writer)

| Language | n | Crop understood | Decision matches engine | Answer language OK | Numbers grounded | Valid citations | LLM answer used | Mean latency ms | p95 latency ms | Mean tokens in/out |
|---|---|---|---|---|---|---|---|---|---|---|
| en | 15 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 56 | 147 | 0/0 |
| hi | 15 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 45 | 129 | 0/0 |
| mr | 15 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 73 | 157 | 0/0 |

Answer quality per language still needs rating by native-speaking reviewers (plan section 10).
