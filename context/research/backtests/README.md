# Backtest runs

One folder per run, named `<date>-<name>`. A run is never edited after the fact. A re-run
makes a new folder, so the record of what was believed when stays intact.

Each folder holds:
- `report.md`: what was tested, the results with their t-statistics, coverage, and limits
- `summary.json`: the same numbers, machine-readable (agents' evidence files are built from it)
- `monthly_<version>.csv`: the month-by-month series, so anyone can recheck the statistics

Every screen version that's run is also recorded in the trials ledger (`backtest_trials`
table), including versions that failed.

Earlier runs, from before this folder existed, are logged in `scripts/` (for example
`_universe_pilot_n200.log`) and summarized in `../findings.md`.
