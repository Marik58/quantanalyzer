---
id: risk-manager
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for risk-manager

## What happened after big price moves

S&P 500 members, 2011-01-31 to 2025-09-30 (formation months with a full 12 months after). "t" compares each group with all stocks in the same months,
allowing for overlapping windows; |t| under 2 means no reliable difference.

After a 1-month move:

| Past move | Cases | Beat S&P 500 next 12m | All stocks, same months | t | Fell 30%+ within 3m |
|---|---|---|---|---|---|
| fell 20%+ | 724 | 52.8% | 46.0% | +1.02 | 11.7% |
| fell 10-20% | 4,087 | 44.3% | 44.4% | -0.07 | 7.6% |
| moved less than 10% | 54,526 | 44.8% | 45.0% | -0.77 | 2.7% |
| rose 10-20% | 6,138 | 44.0% | 43.5% | +0.47 | 2.8% |
| rose 20%+ | 1,226 | 47.5% | 43.6% | +1.18 | 5.0% |

After a 12-month move:

| Past move | Cases | Beat S&P 500 next 12m | All stocks, same months | t | Fell 30%+ within 3m |
|---|---|---|---|---|---|
| fell 30%+ | 3,146 | 50.6% | 42.9% | +1.42 | 8.4% |
| fell 0-30% | 16,306 | 43.2% | 43.4% | -0.09 | 3.5% |
| rose 0-30% | 28,363 | 44.4% | 45.4% | -0.92 | 2.1% |
| rose 30-60% | 11,598 | 45.9% | 45.6% | +0.29 | 2.9% |
| rose 60%+ | 4,222 | 46.3% | 45.7% | +0.15 | 3.7% |

**What this means:** no past-move group differs reliably from other stocks (every |t| < 2). A big move by itself hasn't predicted the next year for large caps. Don't treat a jump as momentum or a drop as a bargain without other evidence.

## Base rate for `p_drop_30` (a 30%+ fall within 3 months)

- Any S&P 500 stock: 3.1%
- After rising 20%+ in a month: 5.0% (1,226 cases)
- After falling 20%+ in a month: 11.7% (724 cases)

These are **large caps**. Pump-and-dump targets are usually tiny stocks, where the charter's
lesson applies instead: promoted stocks fell 53% on average within 120 trading days (Leuz et al.).
