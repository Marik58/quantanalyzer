"""Walk-forward backtest of the signal vs buy-and-hold over the available history."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.analysis.indicators import compute_all


@dataclass
class BacktestResult:
    signal_return: float       # cumulative return following the signal
    buyhold_return: float
    hit_rate: float            # fraction of long days that were positive
    n_trades: int              # number of regime flips
    sharpe_signal: float
    spy_return: float | None = None    # market (SPY) return over the same window
    alpha_vs_spy: float | None = None  # signal_return − spy_return


def run(df: pd.DataFrame, lookback_days: int = 504,
        benchmark_df: pd.DataFrame | None = None) -> BacktestResult:
    """Long when composite score > +25, flat otherwise (no shorting).
    Recomputes the trend+momentum+vol composite on each day with data available at
    that bar, using the SAME weights as signals.py (renormalized over the three
    factors available here — relative-strength-vs-SPY needs a per-bar benchmark and
    is omitted, exactly as signals.py does when that factor is unavailable).

    If `benchmark_df` (SPY history) is supplied, also reports the market return over
    the identical window and the strategy's excess return (alpha) vs the market.
    """
    full = compute_all(df).dropna(subset=["SMA200", "MACD_HIST", "VOL30"]).copy()
    if len(full) < 60:
        return BacktestResult(0.0, 0.0, 0.0, 0, 0.0)

    full = full.iloc[-lookback_days:]
    # Vectorized score components per day — mirrors signals.py exactly so the
    # backtest measures the SAME strategy the Overview tab displays.
    above_50 = (full["Close"] - full["SMA50"]) / full["SMA50"]
    above_200 = (full["Close"] - full["SMA200"]) / full["SMA200"]
    trend = (above_50 * 4 + above_200 * 2).clip(-1, 1)

    rsi = full["RSI14"]
    rsi_score = (rsi - 50) / 25
    rsi_score = rsi_score.where(rsi <= 75, -0.5)   # rsi>75 → -0.5 (overbought clamp)
    rsi_score = rsi_score.where(rsi >= 25,  0.5)   # rsi<25 → +0.5 (oversold bounce)
    macd_score = np.tanh(full["MACD_HIST"] * 5)
    r1m = full["Close"].pct_change(21)
    r3m = full["Close"].pct_change(63)
    rets_score = np.tanh((r1m + r3m) * 3)
    momentum = (0.4 * rsi_score + 0.3 * macd_score + 0.3 * rets_score).clip(-1, 1)

    vol = full["VOL30"]
    vol_score = pd.Series(0.0, index=full.index)
    vol_score[vol < 0.20] = 0.3
    vol_score[(vol >= 0.20) & (vol < 0.35)] = 0.0
    vol_score[(vol >= 0.35) & (vol < 0.55)] = -0.3
    vol_score[vol >= 0.55] = -0.6

    # signals.py weights (Trend 0.35 / Momentum 0.30 / Vol 0.15), renormalized over
    # the three factors present here (RS-vs-SPY omitted → denominator 0.80).
    _W_TREND, _W_MOM, _W_VOL = 0.35, 0.30, 0.15
    _used = _W_TREND + _W_MOM + _W_VOL
    composite = (_W_TREND * trend + _W_MOM * momentum + _W_VOL * vol_score) / _used * 100
    # Position: 1 long when score > 25, 0 otherwise (no shorting)
    pos = (composite > 25).astype(int).shift(1).fillna(0)

    daily_ret = full["Close"].pct_change().fillna(0)
    strat_ret = daily_ret * pos
    cum_strat = float((1 + strat_ret).prod() - 1)
    cum_bh = float((1 + daily_ret).prod() - 1)
    in_market = strat_ret[pos == 1]
    hit = float((in_market > 0).mean()) if len(in_market) else 0.0
    n_trades = int(pos.diff().abs().sum() // 2)
    sharpe = float((strat_ret.mean() / strat_ret.std()) * np.sqrt(252)) if strat_ret.std() > 0 else 0.0

    # Benchmark (SPY) return over the identical window, plus strategy alpha.
    spy_return: float | None = None
    alpha_vs_spy: float | None = None
    if benchmark_df is not None and not benchmark_df.empty and "Close" in benchmark_df:
        bc = benchmark_df["Close"]
        window = bc[(bc.index >= full.index[0]) & (bc.index <= full.index[-1])]
        if len(window) >= 2 and float(window.iloc[0]) > 0:
            spy_return = float(window.iloc[-1] / window.iloc[0] - 1.0)
            alpha_vs_spy = float(cum_strat - spy_return)

    return BacktestResult(
        signal_return=cum_strat,
        buyhold_return=cum_bh,
        hit_rate=hit,
        n_trades=n_trades,
        sharpe_signal=sharpe,
        spy_return=spy_return,
        alpha_vs_spy=alpha_vs_spy,
    )
