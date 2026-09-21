r"""Re-analyse a saved backtest without re-scoring it.

Scoring a 500-name universe takes hours because the HMM and topology refit at
every monthly cutoff. The scores themselves never change afterwards, so
`run_universe_backtest.py` saves them to data/backtests/*.csv and this script
answers follow-up questions against that file in seconds:

    .venv\Scripts\python.exe scripts\analyze_backtest_obs.py data\backtests\obs_pit_n80_seed1.csv
    .venv\Scripts\python.exe scripts\analyze_backtest_obs.py <file> --cost-bps 25
    .venv\Scripts\python.exe scripts\analyze_backtest_obs.py <file> --cost-sweep

Use it to ask "does the edge survive higher trading costs?", to check the
factor adjustment, or to look at component skill — all without touching the
network or re-running the model.
"""
from __future__ import annotations

import argparse
import csv
import sys
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
logging.disable(logging.WARNING)

from backend.analysis import score_backtest as sb  # noqa: E402

COMPONENTS = ("technical", "regime", "statistics", "spectral", "topology")


def load_observations(path: Path) -> list[sb.Observation]:
    obs: list[sb.Observation] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            comps = {}
            for c in COMPONENTS:
                raw = (row.get(c) or "").strip()
                comps[c] = float(raw) if raw not in ("", "None") else None
            obs.append(sb.Observation(
                date=row["date"], ticker=row["ticker"],
                backbone_score=float(row["score"]), fwd_return=float(row["fwd_return"]),
                fwd_days=21, components=comps,
                active_weight=float(row.get("active_weight") or 0.0),
            ))
    return obs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="observations CSV saved by run_universe_backtest.py")
    ap.add_argument("--fwd", type=int, default=21)
    ap.add_argument("--cost-bps", type=float, default=sb.DEFAULT_COST_BPS)
    ap.add_argument("--cost-sweep", action="store_true",
                    help="show the long-short result at 0, 5, 10, 25 and 50 bps")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    obs = load_observations(path)
    print(f"Loaded {len(obs)} observations from {path.name}\n")

    s = sb._summarize(obs, fwd_days=args.fwd, cost_bps=args.cost_bps)
    if s is None:
        print("No summary could be produced.")
        return 1

    print(f"  Window          {s.date_range[0]} -> {s.date_range[1]}")
    print(f"  Tickers/months  {s.n_tickers} / {s.n_months}")
    print(f"  Cross-sec IC    mean={s.ic_mean:+.4f}  t={s.ic_t_stat:+.2f}  (IR {s.ir_annualized:+.3f})")
    print(f"  Pooled IC       {s.pooled_ic:+.4f}")
    print("  Quintiles within " + " · ".join(f"Q{i+1}={q*100:+.2f}%"
                                             for i, q in enumerate(s.quintile_returns_within)))

    ff = s.factor_fit
    if ff:
        print(f"\n  Factor-adjusted alpha {ff['alpha_annualized']:+.2%}/yr  t={ff['alpha_t']:+.2f}  "
              f"p={ff['alpha_p']:.3f}  R2={ff['r_squared']:.2f}  ({ff['n_periods']} periods)")
        print("    betas " + "  ".join(f"{k}={v:+.2f}" for k, v in ff["betas"].items()))
        print(f"    {ff['verdict']}")

    print("\n  Component skill (Benjamini-Hochberg corrected):")
    for c in s.components:
        print(f"    {c.name:<11} IC={c.ic_mean:+.4f}  t={c.ic_t_stat:+.2f}  q={c.q_value:.3f}  "
              f"{'SURVIVES' if c.survives_correction else 'no'}")

    if args.cost_sweep:
        print("\n  Long-short net of costs (turnover "
              f"{s.turnover_mean:.0%} per rebalance):")
        for bps in (0.0, 5.0, 10.0, 25.0, 50.0):
            ss = sb._summarize(obs, fwd_days=args.fwd, cost_bps=bps)
            print(f"    {bps:>5.0f} bps  ->  {ss.long_short_mean_net*100:+.3f}% per rebalance "
                  f"({ss.long_short_mean_net * (252/args.fwd) * 100:+.1f}% a year, uncompounded)")
        print("    Costs are charged on both sides of both legs at the measured turnover.")
    else:
        print(f"\n  Long-short      gross {s.long_short_mean_monthly*100:+.2f}%/rebalance, "
              f"net {s.long_short_mean_net*100:+.2f}% at {s.cost_bps:.0f}bps")

    print(f"\n  {s.n_observations} observations · nothing was re-scored; "
          f"this ran off the saved file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
