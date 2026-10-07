# Verified findings

Newest first. Each finding has a date, its evidence, and its source. A finding that turns
out wrong is marked **superseded** with a link to the correction. It's never deleted.

## 2026-10-07: Growth and Value Screens (v1), first backtest

See `backtests/2026-10-07-screens-v1/report.md`. Summary added below once the run completes.

## 2026-10-07: Point-in-time data coverage, S&P 500 since 2011

From `scripts/run_screen_backtest.py build`: 93,858 member-months (month-ends from 2011-01
to 2026-08).
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
