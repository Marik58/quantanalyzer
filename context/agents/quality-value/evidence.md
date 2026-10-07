---
id: quality-value
kind: agent-evidence
editable_by: code
updated: 2026-10-07
source: context/research/backtests/2026-10-07-screens-v1/summary.json
---

# Evidence for the Quality & Value

## Your twin: the Value Screen (value-v1)

The rule version of your method (`backend/analysis/screens.py`), backtested on S&P 500
members month by month from 2011-01-31 to 2026-08-31 (188 months), using SEC
numbers only after they were filed, after a 10 bp trading cost. It **did not pass** Stage A (factor-adjusted alpha against the pool with t ≥ 3, holding up in most sub-periods).

- Against its Candidate Pool (every usable member that month): -1.6%
  a year, t = -0.78. After the known factor tilts: -0.02%
  a year, t = -0.01.
- Yearly growth after costs: picks 10.3%, pool 12.7%,
  SPY 14.0%. Years at or above 25%: 4 of 15.
- About 24 stocks passed in a typical month, out of about 381.

## Base rates for your probabilities (12 months ahead)

- A Value Screen pick beat SPY 44.0% of the time and made 25%+
  29.9% of the time (n = 4,179 stock-months).
- Any usable S&P 500 member: 44.7% and 29.6%
  (n = 66,487).

Start `p_beat_market` and `p_hurdle` from these, and move away only as far as your
evidence justifies. The 12-month windows overlap, so treat them as descriptions, not proof.

## Limits

76.4% of member-months were usable. Most gaps are companies that were
bought out or failed and no longer trade, so their prices aren't available free. Large
caps only, from 2011. Full report: `context/research/backtests/2026-10-07-screens-v1/report.md`.
