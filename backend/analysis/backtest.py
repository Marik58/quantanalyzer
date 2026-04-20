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


def run(df: pd.DataFrame, lookback_days: int = 504) -> BacktestResult:
    """Long when composite score > +25, flat when between, short-flat (0) when < -25.
    Recomputes the trend+momentum+vol composite on each day with data available at that bar.
    """
    full = compute_all(df).dropna(subset=["SMA200", "MACD_HIST", "VOL30"]).copy()
    if len(full) < 60:
        return BacktestResult(0.0, 0.0, 0.0, 0, 0.0)

    full = full.iloc[-lookback_days:]
    # Vectorized score components per day (mirrors signals.py weights/heuristics, simplified)
    above_50 = (full["Close"] - full["SMA50"]) / full["SMA50"]
    above_200 = (full["Close"] - full["SMA200"]) / full["SMA200"]
    trend = (above_50 * 4 + above_200 * 2).clip(-1, 1)

    rsi = full["RSI14"]
    rsi_score = ((rsi - 50) / 25).clip(-1, 1)
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

    composite = (0.45 * trend + 0.4 * momentum + 0.15 * vol_score) * 100
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
    return BacktestResult(
        signal_return=cum_strat,
        buyhold_return=cum_bh,
        hit_rate=hit,
        n_trades=n_trades,
        sharpe_signal=sharpe,
    )
