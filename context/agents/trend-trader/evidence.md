---
id: trend-trader
kind: agent-evidence
editable_by: code
updated: 2026-10-07
source: scripts/_universe_pilot_n200.log (run 2026-09-21)
---

# Evidence for the Trend Trader

## Your twin: the technical score (backend/analysis/signals.py)

Tested as the "technical" component of the composite score, on 200 randomly sampled
S&P 500 members (point-in-time, sampled as of 2023-09-01), monthly from 2023-08-31 to
2026-08-20: 37 months, 6,662 observations, 187 stocks with data.

- Rank correlation with the next month's return (information coefficient): +0.022,
  t = +0.72. After correcting for testing five components at once, q = 0.66.
  **Not distinguishable from zero.**
- The full composite score (technical plus four other components) did no better:
  information ratio +0.20, t = +0.35, and long-short +0.04% a month after a 10 bp
  trading cost.
- 13 stocks had no price history. All of them had left the index, which is the
  survivorship gap free data can't close.

## What this means for your calls

The rule your method is built on has shown **no measurable edge** so far. Start every
probability from the base rate, and move away from it only on evidence the score itself
doesn't capture. A "strong" stance needs a reason beyond the technical score.

## Limits

Only three years and 37 months were tested, so a real but small edge could be hidden by
noise (charters §14: at an information ratio of 0.2, proving it would take decades).
