"""Single test runner — asserts shape & range invariants for every analysis module.

Unlike the 18 `scripts/test_*.py` (which only *print*), this *asserts* and exits
non-zero on any failure, so it can gate signal-semantics changes. It loads one
ticker (AAPL) + SPY ONCE and reuses them across modules, so the whole suite is a
handful of yfinance fetches, not one per module.

Run from the repo root with the venv active:

    .venv\\Scripts\\python.exe scripts\\run_all_tests.py            # fast per-ticker modules
    .venv\\Scripts\\python.exe scripts\\run_all_tests.py --full     # + slow walk-forward

Exit code 0 = all green, 1 = at least one module failed its invariants.
"""
from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

from backend.analysis import (  # noqa: E402
    backtest as backtest_mod,
    catalyst as catalyst_mod,
    data as data_mod,
    distribution as dist_mod,
    indicators as ind_mod,
    manifold as manifold_mod,
    peers as peers_mod,
    regime as regime_mod,
    regime_hmm as regime_hmm_mod,
    risk as risk_mod,
    sentiment as sentiment_mod,
    signals as signals_mod,
    spectral as spectral_mod,
    statistics as stats_mod,
    topology as topology_mod,
    valuation as valuation_mod,
)
from backend.analysis import quant_score as quant_score_mod  # noqa: E402
from backend.analysis import score_backtest as score_bt_mod  # noqa: E402

TICKER = "AAPL"
_FAILURES: list[str] = []


# --- assertion helpers --------------------------------------------------------
def req(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def finite(x, name: str) -> None:
    req(isinstance(x, (int, float)), f"{name} must be numeric, got {type(x).__name__}")
    req(math.isfinite(float(x)), f"{name} must be finite, got {x}")


def in_range(x, lo, hi, name: str) -> None:
    finite(x, name)
    req(lo <= x <= hi, f"{name}={x} out of range [{lo}, {hi}]")


def nonempty_dict(d, name: str) -> None:
    req(isinstance(d, dict) and len(d) > 0, f"{name} must be a non-empty dict")


def has_explanations(payload: dict) -> None:
    if "explanations" in payload:
        nonempty_dict(payload["explanations"], "explanations")


# --- module tests -------------------------------------------------------------
# Each takes the shared context dict and asserts. Raising = fail.
def t_data(ctx) -> None:
    td = ctx["td"]
    req(td is not None, "data.load returned None")
    req(not td.history.empty, "history is empty")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        req(col in td.history.columns, f"history missing '{col}' column")
    finite(td.last_price, "last_price")
    req(td.last_price > 0, "last_price must be positive")


def t_indicators(ctx) -> None:
    df = ind_mod.compute_all(ctx["td"].history)
    for col in ("SMA50", "SMA200", "RSI14", "MACD_HIST", "VOL30"):
        req(col in df.columns, f"indicators missing '{col}'")
    rsi = df["RSI14"].dropna()
    req(not rsi.empty, "RSI14 all-NaN")
    in_range(float(rsi.min()), 0, 100, "RSI14.min")
    in_range(float(rsi.max()), 0, 100, "RSI14.max")


def t_signals(ctx) -> None:
    sig = signals_mod.compute(ctx["df_ready"], ctx["bench_df"])
    in_range(sig.composite, -100, 100, "signal.composite")
    in_range(sig.confidence, 0, 100, "signal.confidence")
    req(isinstance(sig.action, str) and sig.action, "signal.action empty")
    req(isinstance(sig.factors, list) and len(sig.factors) >= 1, "signal.factors empty")
    for f in sig.factors:
        in_range(f.score, -1.0, 1.0, f"factor '{f.name}'.score")


def t_regime(ctx) -> None:
    reg = regime_mod.classify(ctx["df_ready"])
    req(isinstance(reg.label, str) and reg.label, "regime.label empty")
    finite(reg.strength, "regime.strength")


def t_risk(ctx) -> None:
    rsk = risk_mod.rate(ctx["close"])
    req(isinstance(rsk.rating, str) and rsk.rating, "risk.rating empty")
    finite(rsk.annualized_vol, "risk.annualized_vol")
    req(rsk.annualized_vol >= 0, "risk.annualized_vol negative")
    in_range(rsk.max_drawdown_1y, -1.0, 0.0, "risk.max_drawdown_1y")


def t_distribution(ctx) -> None:
    d = dist_mod.compute(ctx["close"])
    finite(d.stdev_daily, "dist.stdev_daily")
    req(d.stdev_daily >= 0, "dist.stdev_daily negative")
    for nm in ("mean_daily", "skew", "kurtosis", "var_95", "var_99",
               "sharpe_annual", "last_return_z"):
        finite(getattr(d, nm), f"dist.{nm}")


def t_backtest(ctx) -> None:
    bt = backtest_mod.run(ctx["td"].history, benchmark_df=ctx["bench_df"])
    finite(bt.signal_return, "backtest.signal_return")
    finite(bt.buyhold_return, "backtest.buyhold_return")
    in_range(bt.hit_rate, 0.0, 1.0, "backtest.hit_rate")
    req(isinstance(bt.n_trades, int) and bt.n_trades >= 0, "backtest.n_trades invalid")
    finite(bt.sharpe_signal, "backtest.sharpe_signal")
    # SPY benchmark supplied → alpha must be populated and consistent
    req(bt.spy_return is not None, "backtest.spy_return None despite benchmark")
    req(abs(bt.alpha_vs_spy - (bt.signal_return - bt.spy_return)) < 1e-9,
        "backtest.alpha_vs_spy != signal_return - spy_return")


def t_quant_score(ctx) -> None:
    r = quant_score_mod.compute(TICKER)
    payload = quant_score_mod.to_dict(r)
    req(isinstance(r.verdict, str) and r.verdict, "quant_score.verdict empty")
    in_range(r.directional_score, -100, 100, "quant_score.directional_score")
    in_range(r.percentile_score, 0, 100, "quant_score.percentile_score")
    in_range(r.confidence, 0, 100, "quant_score.confidence")
    nonempty_dict(payload, "quant_score payload")
    has_explanations(payload)


def _compute_todict(mod, *args) -> None:
    """Generic: compute(...) returns non-None, to_dict yields non-empty dict."""
    r = mod.compute(*args)
    req(r is not None, f"{mod.__name__}.compute returned None")
    payload = mod.to_dict(r)
    nonempty_dict(payload, f"{mod.__name__} payload")
    has_explanations(payload)


def t_peers(ctx) -> None:
    _compute_todict(peers_mod, TICKER)


def t_sentiment(ctx) -> None:
    _compute_todict(sentiment_mod, TICKER, ctx["close"])


def t_statistics(ctx) -> None:
    _compute_todict(stats_mod, ctx["close"], ctx["bench_close"])


def t_spectral(ctx) -> None:
    _compute_todict(spectral_mod, ctx["close"])


def t_topology(ctx) -> None:
    _compute_todict(topology_mod, ctx["close"])


def t_manifold(ctx) -> None:
    h = ctx["td"].history
    _compute_todict(manifold_mod, h["Close"], h["High"], h["Low"])


def t_regime_hmm(ctx) -> None:
    _compute_todict(regime_hmm_mod, ctx["close"])


def t_valuation(ctx) -> None:
    _compute_todict(valuation_mod, TICKER)


def t_catalyst(ctx) -> None:
    _compute_todict(catalyst_mod, TICKER)


def t_score_backtest(ctx) -> None:  # slow: walk-forward, only with --full
    r = score_bt_mod.compute([TICKER, "MSFT", "GOOGL"], lookback_years=1, fwd_days=21)
    req(r is not None, "score_backtest returned None")


FAST_TESTS = [
    ("data", t_data),
    ("indicators", t_indicators),
    ("signals", t_signals),
    ("regime", t_regime),
    ("risk", t_risk),
    ("distribution", t_distribution),
    ("backtest", t_backtest),
    ("quant_score", t_quant_score),
    ("peers", t_peers),
    ("sentiment", t_sentiment),
    ("statistics", t_statistics),
    ("spectral", t_spectral),
    ("topology", t_topology),
    ("manifold", t_manifold),
    ("regime_hmm", t_regime_hmm),
    ("valuation", t_valuation),
    ("catalyst", t_catalyst),
]
SLOW_TESTS = [("score_backtest", t_score_backtest)]


def main(argv: list[str]) -> int:
    full = "--full" in argv
    print(f"Loading shared context ({TICKER} + SPY)...")
    td = data_mod.load(TICKER)
    if td is None:
        print(f"FATAL: could not load {TICKER}. Network / yfinance down?")
        return 1
    bench_td = data_mod.load("SPY")
    bench_df = bench_td.history if bench_td else None
    df = ind_mod.compute_all(td.history)
    df_ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
    ctx = {
        "td": td,
        "close": td.history["Close"],
        "bench_df": bench_df,
        "bench_close": bench_df["Close"] if bench_df is not None else None,
        "df_ready": df_ready,
    }

    tests = FAST_TESTS + (SLOW_TESTS if full else [])
    if not full:
        print(f"(skipping {len(SLOW_TESTS)} slow walk-forward test; pass --full to include)\n")

    passed = 0
    for name, fn in tests:
        try:
            fn(ctx)
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as exc:
            _FAILURES.append(name)
            print(f"  [FAIL] {name}: {exc}")
            if not isinstance(exc, AssertionError):
                traceback.print_exc()

    print(f"\n{passed}/{len(tests)} modules passed.")
    if _FAILURES:
        print(f"FAILED: {', '.join(_FAILURES)}")
        return 1
    print("All green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
