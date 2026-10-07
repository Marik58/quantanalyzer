---
id: _shared
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for every agent

## Base rates: a typical S&P 500 stock

From 2011-01-31 to 2025-09-30 (formation months with a full 12 months after) (66,929 stock-months, S&P 500 members at the time):
- beat the S&P 500 over the next 12 months: **44.8%** of the time
- beat it over the next month: 49.0%
- returned 25% or more over the next 12 months: 29.7%
- fell 30% or more at some point within 3 months: 3.1%

Start every probability here and move only as far as your evidence justifies (house rule 5).
A forecaster that always says these numbers is the Base-Rate Forecaster; beating it is the
minimum. Limits: large caps only, from 2011; companies that no longer trade are missing.
