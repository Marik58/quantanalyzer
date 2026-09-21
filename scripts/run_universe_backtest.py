r"""Backtest the Quant Score on a point-in-time S&P 500 universe.

The 14-name watchlist backtest cannot answer whether the score works: with so
few, highly correlated names the month-to-month information coefficient is
almost pure sampling noise (its standard error is roughly 1/sqrt(N-1), which
is about 0.28 at N=14 versus 0.045 at N=500). This script runs the same
walk-forward test on a broad universe, scoring each name only on the dates it
was actually in the index.

    .venv\Scripts\python.exe scripts\run_universe_backtest.py --n 80
    .venv\Scripts\python.exe scripts\run_universe_backtest.py --n 80 --compare
    .venv\Scripts\python.exe scripts\run_universe_backtest.py --n 500 --years 3

--compare additionally runs the survivors-only version of the same sample, so
the survivorship bias is measured rather than argued about.

Expect roughly 15-20 seconds per ticker (the HMM and topology refit at every
monthly cutoff), so --n 80 takes about 25 minutes and --n 500 a few hours.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging  # noqa: E402
import warnings  # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

from backend import db  # noqa: E402
from backend.analysis import score_backtest as sb  # noqa: E402
from backend.analysis import universe as uni  # noqa: E402


def _summary_block(title: str, res) -> None:
    s = res.summary
    print(f"\n=== {title} ===")
    if s is None:
        print(f"  no observations ({res.error})")
        return
    print(f"  Observations      {s.n_observations} across {s.n_tickers} tickers, {s.n_months} months")
    print(f"  Window            {s.date_range[0]} -> {s.date_range[1]}")
    print(f"  Cross-sec IC      mean={s.ic_mean:+.4f}  std={s.ic_std:.3f}  t={s.ic_t_stat:+.2f}")
    print(f"  Annualized IR     {s.ir_annualized:+.3f}")
    print(f"  Pooled IC         {s.pooled_ic:+.4f}")
    print(f"  Hit rate          long {s.hit_rate_long:.0%} ({s.n_long_signals}), "
          f"short {s.hit_rate_short:.0%} ({s.n_short_signals})")
    print("  Quintiles within  " + " · ".join(f"Q{i+1}={q*100:+.2f}%"
                                              for i, q in enumerate(s.quintile_returns_within)))
    print(f"  Long-short        gross {s.long_short_mean_monthly*100:+.2f}%/rebalance, "
          f"net {s.long_short_mean_net*100:+.2f}% after {s.cost_bps:.0f}bps "
          f"(turnover {s.turnover_mean:.0%})")
    if s.components:
        print("  Component skill (Benjamini-Hochberg corrected):")
        for c in s.components:
            flag = "SURVIVES" if c.survives_correction else "no"
            print(f"    {c.name:<11} IC={c.ic_mean:+.4f}  t={c.ic_t_stat:+.2f}  "
                  f"p={c.p_value:.3f}  q={c.q_value:.3f}  {flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=80, help="sample size (default 80)")
    ap.add_argument("--as-of", default=None,
                    help="membership date for the sample (default: start of the window)")
    ap.add_argument("--years", type=int, default=3, help="lookback years (default 3)")
    ap.add_argument("--fwd", type=int, default=21, help="forward window in trading days")
    ap.add_argument("--cost-bps", type=float, default=sb.DEFAULT_COST_BPS)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--compare", action="store_true",
                    help="also run survivors-only, to measure survivorship bias")
    ap.add_argument("--label", default=None, help="label stored in the trials ledger")
    args = ap.parse_args()

    db.init()
    end = datetime.now().date()
    as_of = args.as_of or f"{end.year - args.years}-{end.month:02d}-01"

    info = uni.stats()
    pool = uni.members_between(as_of, str(end))
    gone = uni.leavers_between(as_of, str(end))
    print(f"S&P 500 membership history: {info['tickers_ever']} tickers ever, "
          f"{info['current_members']} current")
    print(f"Window {as_of} -> {end}: {len(pool)} names were members at some point, "
          f"{len(gone)} of them left the index (the survivorship-critical ones).")

    sample = uni.sample_members(args.n, as_of=as_of, seed=args.seed)
    in_sample_gone = sorted(set(sample) & gone)
    print(f"\nSampled {len(sample)} members as of {as_of}; "
          f"{len(in_sample_gone)} later left the index"
          + (f" ({', '.join(in_sample_gone[:10])}{'…' if len(in_sample_gone) > 10 else ''})"
             if in_sample_gone else ""))

    t0 = time.time()
    print(f"\nRunning point-in-time backtest… ~{len(sample) * 18 / 60:.0f} min expected")
    res = sb.compute(sample, lookback_years=args.years, fwd_days=args.fwd,
                     cost_bps=args.cost_bps,
                     label=args.label or f"sp500-pit n={len(sample)} seed={args.seed}",
                     universe_fn=uni.membership_filter(sample),
                     universe_label=f"sp500-pit:{len(sample)}:seed{args.seed}")
    print(f"  done in {time.time() - t0:.0f}s")

    failed = [s.ticker for s in res.series if s.error or not s.observations]
    print(f"\nData coverage: {len(sample) - len(failed)}/{len(sample)} tickers produced "
          f"observations; {len(failed)} had no usable history.")
    if failed:
        still_missing_gone = sorted(set(failed) & gone)
        print(f"  missing: {', '.join(failed[:15])}{'…' if len(failed) > 15 else ''}")
        print(f"  of those, {len(still_missing_gone)} are names that left the index — "
              f"exactly the ones a survivorship-free test needs. This is the residual "
              f"bias that only a research database (CRSP) removes.")

    _summary_block(f"Point-in-time universe (n={len(sample)})", res)
    for key in ("skill", "quintiles", "portfolio", "universe"):
        if res.explanations.get(key):
            print(f"\n  [{key}] {res.explanations[key]}")

    if args.compare:
        survivors = [t for t in sample if t not in gone]
        print(f"\n\nRunning survivors-only comparison ({len(survivors)} names)…")
        res2 = sb.compute(survivors, lookback_years=args.years, fwd_days=args.fwd,
                          cost_bps=args.cost_bps,
                          label=f"survivors-only n={len(survivors)} seed={args.seed}",
                          universe_label=f"survivors-only:{len(survivors)}:seed{args.seed}")
        _summary_block(f"Survivors only (n={len(survivors)})", res2)
        if res.summary and res2.summary:
            d_ir = res2.summary.ir_annualized - res.summary.ir_annualized
            d_ic = res2.summary.ic_mean - res.summary.ic_mean
            print(f"\n=== Survivorship bias ===")
            print(f"  Dropping the removed names moves IR by {d_ir:+.3f} "
                  f"and mean IC by {d_ic:+.4f}.")
            print("  A positive shift means the survivors-only test flatters the score.")

    print("\nTrials ledger (most recent):")
    for row in db.backtest_trials(3):
        print(f"  #{row['id']}  {row['universe']}  IR={row['ir_annualized']:+.3f}  "
              f"obs={row['n_observations']}  {row['ts'][:19]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
