---
id: quality-value
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for quality-value

## Your twin: value-v1, the rule version of your method

Backtest `context/research/backtests/2026-10-07-screens-v1-data-v2`: S&P 500 members month by month, 2011-01-31 to 2026-08-31 (188
months), SEC numbers used only after they were filed, after a 10 bp trading cost.

- **Stage A: FAIL.** Against its Candidate Pool: -1.7% a year,
  t = -0.83. After known factor tilts: alpha -0.11% a year, t = -0.06.
- Yearly growth after costs: picks 10.2%, pool 12.8%, SPY 14.0%;
  full years at 25%+: 4 of 15.
- A pick beat SPY over the next 12 months 44.2% of the time and made 25%+
  30.0% (n = 4,200); any pool stock: 44.8% and 29.7%.

**What this means:** passing the rule is not, by itself, a reason for a positive stance. Your
value has to come from judgment the rule doesn't capture, and the scoreboard will check
whether it does (Stage B: not worse than this twin on the same stocks).
