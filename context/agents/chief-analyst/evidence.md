---
id: chief-analyst
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for chief-analyst

## The panel's track records so far (weigh agents by these)

| Agent | Its twin's record | Verdict |
|---|---|---|
| Trend Trader | technical score: IC +0.022, t = +0.72 (37 months) | no measurable edge |
| Growth Hunter | growth-v1: +0.8%/yr vs pool, t = +0.26 (188 months) | Stage A fail |
| Quality & Value | value-v1: -1.7%/yr vs pool, t = -0.83 (188 months) | Stage A fail |

No agent has a proven edge yet, and no AI agent has graded calls yet. When agents agree, that isn't extra evidence if their methods have no record; say so. Weight a view by its record, not by how confident it sounds.

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
