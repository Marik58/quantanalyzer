# Verified findings

Newest first. Each finding has a date, its evidence, and its source. A finding that turns
out wrong is marked **superseded** with a link to the correction. It's never deleted.

## 2026-10-07: After a big move, large caps behave like any other stock

From `base_rates.json` (S&P 500 members, 2011-01 to 2025-09 formation months, 66,929
stock-months). Each group is compared with all stocks in the same months, with
overlap-adjusted t-statistics.
- **After a 1-month jump of 20%+:** 47.5% beat the S&P 500 over the next year, against
  43.6% for all stocks in the same months (t = +1.18).
- **After a 20%+ fall:** 52.8% against 46.0% (t = +1.02).
- **After 12-month moves:** every |t| < 2.
- **Conclusion:** neither momentum nor reversal is reliable on its own for large caps in
  this period.
- **A 30%+ drop within 3 months:** 3.1% for any stock, 5.0% after a 20%+ jump, 11.7% after a
  20%+ fall.
- **Where it's used:** the paper-trading warning, the morning email, and the evidence of
  the Trend Trader, Hype Watch, Risk Manager and Chief Analyst.

## 2026-10-07: Screens re-run on corrected data (data v2): same answer

The data fixes:
- predecessor company IDs linked by accounting proof (Disney, Alphabet, Cigna, Medtronic,
  Walgreens and 6 more)
- 33 IR rows excluded, because the ID belonged to Gardner Denver then

Usable rows went from 71,678 to 72,131. Results (trials #19, #20,
`backtests/2026-10-07-screens-v1-data-v2/`):
- **Growth:** +0.8% a year against the pool, t = +0.26; alpha −0.4%, t = −0.14.
- **Value:** −1.7% a year, t = −0.83.
- **Both still fail Stage A.** The first run's folder is kept unchanged for comparison.

## 2026-10-07: Growth and Value Screens (v1), first backtest. Neither has an edge

Rules were committed before the run (commit 457a73b), and each screen was run once
(trials #17 and #18). Setup: S&P 500 members month by month, 2011-01 to 2026-08 (188
months), about 381 usable stocks a month, after a 10 bp trading cost. Full report:
`backtests/2026-10-07-screens-v1/report.md`.

| | Growth Screen | Value Screen | Candidate Pool | SPY |
|---|---|---|---|---|
| Yearly growth, after costs | 13.0% | 10.3% | 12.7% | 14.0% |
| Against the pool | +1.3%/yr, t = +0.39 | −1.6%/yr, t = −0.78 | | |
| Factor-adjusted alpha | −0.04%/yr, t = −0.01 | −0.02%/yr, t = −0.01 | | |
| Full years at 25%+ | 5 of 15 | 4 of 15 | | |
| Stage A (t ≥ 3) | **fail** | **fail** | | |

- **The Growth Screen's small raw lead is fully explained by known factor tilts.** It leans
  toward aggressive investors (CMA −0.43) and away from value (HML −0.21). It also had one
  strong stretch (2016–2020: +12.1% a year, t = 2.50) between two weak ones (2011–2015 −2.5%,
  2021–2026 −4.9%). That's the "one lucky stretch" pattern the sub-period check exists to catch.
- **The Value Screen trailed the pool** in all three sub-periods.
- **Base rates (12 months ahead, overlapping windows):** a usable S&P 500 member beat SPY
  44.7% of the time and returned 25%+ 29.6% of the time (n = 66,487). Growth picks: 45.7%
  and 35.4%. Value picks: 44.0% and 29.9%.
- **The math was checked twice.** An independent regression reproduced both alphas. A
  placebo (30 runs of 20 random stocks a month) gave alpha t-stats spread like noise
  (sd 0.93, range −2.2 to +1.6), so the near-zero alphas aren't forced by the code.
- **Limits:** 76% of member-months usable. The biggest gap is companies that no longer
  trade (no free prices), which is 12% overall and about 25% in 2011. Large caps only.

## 2026-10-07: Point-in-time data coverage, S&P 500 since 2011

From `scripts/run_screen_backtest.py build`: 93,858 member-months (month-ends from 2011-01
to 2026-08), of which 71,678 (76%) are usable.
- About 12% belong to companies that **no longer trade** and have no free price history.
  That's roughly a quarter of the index in 2011 and under 2% by 2025.
- Banks rarely report a standard revenue line, so financial screens can't score them.
- SEC filings contain scale typos (share counts in units instead of millions), caught by
  a market-value sanity check.

## 2026-10-06: Ticker-to-company map

798 of 866 S&P 500 memberships since 2010 are verified against SEC filing records
(`data/universe/ticker_cik.csv`). The first version's "likely" rows were mostly wrong; the
flawed rule was found by hand-checking and removed (see `../project/decisions.md`).

## 2026-10-06: SEC history starts around 2010, and the SEC ticker list misses leavers

- Machine-readable financials begin in 2009–2011, so fundamentals backtests get about 15
  years, not 20.
- 127 of the 199 stocks that left the S&P 500 since 2015 (64%) aren't in the SEC's current
  ticker list. That's why the ticker-to-company map was needed.

## 2026-09-21/22: The technical/composite score has no measurable edge

200 randomly sampled S&P 500 members, point-in-time, 37 months (2023-08 to 2026-08), 6,662
observations (`scripts/_universe_pilot_n200.log`).
- Information ratio +0.20, t = +0.35.
- No component survives a multiple-testing correction (best q = 0.66).
- Tripling the sample from 80 names to 200 cut the apparent edge from +0.66 to +0.20,
  which is what noise does.
- Earlier watchlist-only numbers (14 names, information ratio −0.26) used a biased universe
  and are superseded by this run.

## 2026-09-16 (fixed 2026-09-21): Five methodology bugs found by audit

All five were fixed in the commit "Fix five verified methodology bugs"; results from
before the fix are superseded.
1. **The statistics component never ran in any backtest.** A wrong parameter name raised
   an error that was silently swallowed.
2. **Spectral phase labels were a quarter-cycle off**, so peaks scored bullish.
3. **Kelly sizing used the win/lose formula on continuous returns**, which overstates the
   bet badly.
4. **"GARCH" was claimed in docs but never implemented.** The stress test is really beta
   times the SPY drawdown.
5. **The DCF counted debt twice**, so large-cap tech always screened "overvalued".

Also true, but not bugs:
- Regime labels are relative clusters (AAPL's "Bear" state had a positive trend).
- The topology score can't tell real prices from shuffled ones.
- The MACD score sits at ±1 on most days.
