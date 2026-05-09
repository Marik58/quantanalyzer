"""Smoke test for the Quant Score Backbone backtest.

By default runs on a 2-ticker subset so the test finishes in a couple of
minutes. Pass tickers as CLI args to override; pass --watchlist to run the
default Fox Fund watchlist (slower — 30+ minutes).

Usage:
    python scripts/test_score_backtest.py                    # AAPL, MSFT
    python scripts/test_score_backtest.py NVDA META         # custom subset
    python scripts/test_score_backtest.py --watchlist        # full watchlist
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Force UTF-8 on stdout so unicode arrows in the explanations don't crash on
# Windows cp1252 consoles. The API responses are JSON (UTF-8) anyway.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Make `backend.*` imports work when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Silence hmmlearn's cosmetic convergence chatter (deltas ~1e-3, harmless).
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

from backend.analysis import score_backtest as bt_mod


WATCHLIST = ["ADBE", "NOW", "CRM", "ORCL", "MSFT", "GOOGL", "NVDA",
             "AMD", "AAPL", "META", "AVGO", "AMAT", "SNPS", "CDNS"]


def main(argv: list[str]) -> int:
    if "--watchlist" in argv:
        tickers = WATCHLIST
    elif argv:
        tickers = [t.upper() for t in argv]
    else:
        tickers = ["AAPL", "MSFT"]

    print(f"Backtesting {len(tickers)} ticker(s): {', '.join(tickers)}")
    print("Forward window: 21 trading days · Lookback: 3 years · Monthly rebalance.")
    print("(HMM and topology are slow per call — expect ~30-60s per ticker.)\n")

    t0 = time.time()
    result = bt_mod.compute(tickers, lookback_years=3, fwd_days=21)
    elapsed = time.time() - t0

    print(f"Completed in {elapsed:.1f}s.\n")

    if result.error:
        print(f"ERROR: {result.error}")
        return 1

    # Per-ticker summary
    print("Per-ticker observations produced:")
    for s in result.series:
        if s.error:
            print(f"  {s.ticker:<6} FAILED: {s.error}")
        else:
            print(f"  {s.ticker:<6} {len(s.observations):>3} obs")

    if result.summary is None:
        print("\nNo summary — no observations were produced.")
        return 1

    s = result.summary
    print(f"\n=== Summary ({s.date_range[0]} -> {s.date_range[1]}) ===")
    print(f"  Observations:        {s.n_observations} across {s.n_tickers} tickers, {s.n_months} months")
    print(f"  Cross-sectional IC:  mean={s.ic_mean:+.3f}  std={s.ic_std:.3f}  t={s.ic_t_stat:+.2f}")
    print(f"  Annualized IR:       {s.ir_annualized:+.2f}")
    print(f"  Pooled IC:           {s.pooled_ic:+.3f}")
    print(f"  Hit rate (long):     {s.hit_rate_long*100:.0f}% over {s.n_long_signals} long signals")
    print(f"  Hit rate (short):    {s.hit_rate_short*100:.0f}% over {s.n_short_signals} short signals")
    print(f"  Quintile fwd rets:   " + " · ".join(
        f"Q{i+1}={r*100:+.2f}%" for i, r in enumerate(s.quintile_returns)))
    print(f"  L-S per rebalance:   {s.long_short_mean_monthly*100:+.2f}% mean,"
          f" {s.long_short_total*100:+.2f}% summed")

    print("\n=== Plain-English ===")
    for k, v in result.explanations.items():
        print(f"  [{k}] {v}\n")

    print("=== Excluded (would inject lookahead on yfinance) ===")
    for k, v in result.excluded_components.items():
        print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
