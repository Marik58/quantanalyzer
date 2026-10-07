---
id: trend-trader
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for trend-trader

## Your twin: the technical score (backend/analysis/signals.py)

Source: `scripts/_universe_pilot_n200.log (run 2026-09-21)`. 200 randomly sampled S&P 500 members (point-in-time),
2023-08-31 to 2026-08-20, 37 months, 6,662 observations.
- Rank correlation with next month's return: +0.022, t = +0.72
  (q = 0.66 after correcting for five components): **no measurable edge.**
- The full composite score: information ratio +0.20, t = +0.35.

**What this means:** a "strong" stance needs a reason beyond the technical score.

## What happened after big price moves

S&P 500 members, 2011-01-31 to 2025-09-30 (formation months with a full 12 months after). "t" compares each group with all stocks in the same months,
allowing for overlapping windows; |t| under 2 means no reliable difference.

After a 1-month move:

| Past move | Cases | Beat S&P 500 next 12m | All stocks, same months | t |
|---|---|---|---|---|
| fell 20%+ | 724 | 52.8% | 46.0% | +1.02 |
| fell 10-20% | 4,087 | 44.3% | 44.4% | -0.07 |
| moved less than 10% | 54,526 | 44.8% | 45.0% | -0.77 |
| rose 10-20% | 6,138 | 44.0% | 43.5% | +0.47 |
| rose 20%+ | 1,226 | 47.5% | 43.6% | +1.18 |

After a 12-month move:

| Past move | Cases | Beat S&P 500 next 12m | All stocks, same months | t |
|---|---|---|---|---|
| fell 30%+ | 3,146 | 50.6% | 42.9% | +1.42 |
| fell 0-30% | 16,306 | 43.2% | 43.4% | -0.09 |
| rose 0-30% | 28,363 | 44.4% | 45.4% | -0.92 |
| rose 30-60% | 11,598 | 45.9% | 45.6% | +0.29 |
| rose 60%+ | 4,222 | 46.3% | 45.7% | +0.15 |

**What this means:** no past-move group differs reliably from other stocks (every |t| < 2). A big move by itself hasn't predicted the next year for large caps. Don't treat a jump as momentum or a drop as a bargain without other evidence.
