"""Watchlist alpha check — does the timing signal earn its place?

Runs the reconciled `backtest.run` (which now mirrors signals.py) with the SPY
benchmark across every watchlist name, and tabulates:

    signal return  vs  buy-and-hold return  vs  SPY return  +  alpha vs SPY

Read-only: imports the same modules the app uses, hits no endpoints, changes no
state. Run from the repo root with the venv active:

    .venv\\Scripts\\python.exe scripts\\watchlist_alpha_check.py

The question it answers: is the signal net-negative-alpha across the board (in
which case reframe the product toward diagnostics/education), or does it earn a
timing role on some names?
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a bare script (`python scripts/watchlist_alpha_check.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend import db  # noqa: E402
from backend.analysis import backtest as backtest_mod  # noqa: E402
from backend.analysis import data as data_mod  # noqa: E402


def _pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{x * 100:+7.1f}%"


def main() -> int:
    try:
        tickers = db.list_tickers()
    except Exception:
        tickers = []
    if not tickers:
        tickers = db.DEFAULT_WATCHLIST
    tickers = [t for t in tickers if t.upper() != "SPY"]

    print(f"Loading SPY benchmark...")
    bench_td = data_mod.load("SPY")
    bench_df = bench_td.history if bench_td else None
    if bench_df is None:
        print("  WARNING: SPY failed to load — alpha column will be n/a.")

    header = (
        f"{'Ticker':<8}{'Signal':>9}{'Buy&Hold':>10}{'SPY':>9}"
        f"{'Alpha':>9}{'vs B&H':>9}{'Trades':>8}{'Hit%':>7}{'Sharpe':>8}"
    )
    print("\n" + header)
    print("-" * len(header))

    rows: list[dict] = []
    for t in tickers:
        td = data_mod.load(t)
        if td is None or td.history is None or td.history.empty:
            print(f"{t:<8}  (no data)")
            continue
        try:
            bt = backtest_mod.run(td.history, benchmark_df=bench_df)
        except Exception as exc:  # keep the sweep going; report the name
            print(f"{t:<8}  (backtest error: {exc})")
            continue

        alpha = bt.alpha_vs_spy
        vs_bh = bt.signal_return - bt.buyhold_return
        rows.append({
            "ticker": t,
            "signal": bt.signal_return,
            "buyhold": bt.buyhold_return,
            "spy": bt.spy_return,
            "alpha": alpha,
            "vs_bh": vs_bh,
        })
        print(
            f"{t:<8}{_pct(bt.signal_return):>9}{_pct(bt.buyhold_return):>10}"
            f"{_pct(bt.spy_return):>9}{_pct(alpha):>9}{_pct(vs_bh):>9}"
            f"{bt.n_trades:>8}{bt.hit_rate * 100:>6.0f}%{bt.sharpe_signal:>8.2f}"
        )

    if not rows:
        print("\nNo names produced a backtest. Check data.load / network.")
        return 1

    # --- Aggregates -----------------------------------------------------------
    n = len(rows)
    alphas = [r["alpha"] for r in rows if r["alpha"] is not None]
    vs_bhs = [r["vs_bh"] for r in rows]

    def _avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print("-" * len(header))
    print(f"{'MEAN':<8}{_pct(_avg([r['signal'] for r in rows])):>9}"
          f"{_pct(_avg([r['buyhold'] for r in rows])):>10}"
          f"{_pct(_avg([r['spy'] for r in rows if r['spy'] is not None])):>9}"
          f"{_pct(_avg(alphas)):>9}{_pct(_avg(vs_bhs)):>9}")

    beat_spy = sum(1 for a in alphas if a > 0)
    beat_bh = sum(1 for v in vs_bhs if v > 0)
    print("\n=== Verdict ===")
    print(f"Names analyzed:            {n}")
    if alphas:
        print(f"Beat SPY (alpha > 0):      {beat_spy}/{len(alphas)}  "
              f"(mean alpha {_avg(alphas) * 100:+.1f}%)")
    print(f"Beat buy & hold:           {beat_bh}/{n}  "
          f"(mean vs-B&H {_avg(vs_bhs) * 100:+.1f}%)")
    if alphas and beat_spy == 0:
        print("\n>> Signal is net-negative alpha on EVERY name. Strong case to reframe")
        print("   the product toward diagnostics + education, not timing calls.")
    elif alphas and beat_spy < len(alphas) / 2:
        print("\n>> Signal beats the market on a minority of names. Treat it as ONE")
        print("   input among many, not a standalone timing edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
