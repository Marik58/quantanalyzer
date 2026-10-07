---
id: growth-hunter
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for growth-hunter

## Your twin: growth-v1, the rule version of your method

Backtest `context/research/backtests/2026-10-07-screens-v1-data-v2`: S&P 500 members month by month, 2011-01-31 to 2026-08-31 (188
months), SEC numbers used only after they were filed, after a 10 bp trading cost.

- **Stage A: FAIL.** Against its Candidate Pool: +0.8% a year,
  t = +0.26. After known factor tilts: alpha -0.45% a year, t = -0.14.
- Yearly growth after costs: picks 12.5%, pool 12.8%, SPY 14.0%;
  full years at 25%+: 5 of 15.
- A pick beat SPY over the next 12 months 45.7% of the time and made 25%+
  35.4% (n = 2,294); any pool stock: 44.8% and 29.7%.

**What this means:** passing the rule is not, by itself, a reason for a positive stance. Your
value has to come from judgment the rule doesn't capture, and the scoreboard will check
whether it does (Stage B: not worse than this twin on the same stocks).
