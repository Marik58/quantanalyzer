"""Multi-factor Buy/Hold/Sell signal with transparent inputs and a confidence score."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.analysis.indicators import returns_over


@dataclass
class SignalFactor:
    name: str
    score: float            # -1..+1
    value: float            # raw value
    explanation: str


@dataclass
class Signal:
    action: str             # "BUY" | "HOLD" | "SELL"
    composite: float        # -100..+100
    confidence: float       # 0..100
    opportunity: float      # 0..100, used for ranking the watchlist
    factors: list[SignalFactor] = field(default_factory=list)


def _trend_factor(df: pd.DataFrame) -> SignalFactor:
    last = df.iloc[-1]
    close, sma50, sma200 = float(last["Close"]), float(last["SMA50"]), float(last["SMA200"])
    above_50 = (close - sma50) / sma50 if sma50 else 0
    above_200 = (close - sma200) / sma200 if sma200 else 0
    # Combine: weighted toward longer-term position
    score = float(np.clip(above_50 * 4 + above_200 * 2, -1, 1))
    side = "above" if above_200 > 0 else "below"
    return SignalFactor(
        name="Trend",
        score=score,
        value=above_200,
        explanation=f"Price is {abs(above_200):.1%} {side} the 200-day MA "
                    f"and {abs(above_50):.1%} {'above' if above_50 > 0 else 'below'} the 50-day MA.",
    )


def _momentum_factor(df: pd.DataFrame) -> SignalFactor:
    last = df.iloc[-1]
    rsi = float(last["RSI14"])
    macd_hist = float(last["MACD_HIST"])
    r1m = returns_over(df["Close"], 21)
    r3m = returns_over(df["Close"], 63)
    # RSI: 50 is neutral; >70 overbought (negative); <30 oversold (positive bounce)
    rsi_score = (rsi - 50) / 25
    if rsi > 75: rsi_score = -0.5
    if rsi < 25: rsi_score = 0.5
    macd_score = float(np.tanh(macd_hist * 5))
    rets_score = float(np.tanh((r1m + r3m) * 3))
    score = float(np.clip(0.4 * rsi_score + 0.3 * macd_score + 0.3 * rets_score, -1, 1))
    return SignalFactor(
        name="Momentum",
        score=score,
        value=rsi,
        explanation=f"RSI {rsi:.0f}, MACD histogram {'positive' if macd_hist > 0 else 'negative'}, "
                    f"1m return {r1m:+.1%}, 3m return {r3m:+.1%}.",
    )


def _volatility_factor(df: pd.DataFrame) -> SignalFactor:
    vol = float(df["VOL30"].dropna().iloc[-1])
    # Lower vol -> friendlier environment (mild positive); very high vol -> mild negative
    if vol < 0.20:
        score = 0.3
    elif vol < 0.35:
        score = 0.0
    elif vol < 0.55:
        score = -0.3
    else:
        score = -0.6
    return SignalFactor(
        name="Volatility regime",
        score=score,
        value=vol,
        explanation=f"30-day annualized volatility is {vol:.0%}.",
    )


def _benchmark_factor(df: pd.DataFrame, bench: pd.DataFrame | None) -> SignalFactor | None:
    if bench is None or len(bench) < 90:
        return None
    a = df["Close"].pct_change().dropna().iloc[-63:]
    b = bench["Close"].pct_change().dropna().iloc[-63:]
    n = min(len(a), len(b))
    if n < 30:
        return None
    rs = float((1 + a.iloc[-n:]).prod() - (1 + b.iloc[-n:]).prod())
    score = float(np.tanh(rs * 5))
    return SignalFactor(
        name="Relative strength vs SPY",
        score=score,
        value=rs,
        explanation=f"3-month return is {rs * 100:+.1f} percentage points {'above' if rs > 0 else 'below'} SPY.",
    )


def compute(df: pd.DataFrame, benchmark_df: pd.DataFrame | None = None) -> Signal:
    factors: list[SignalFactor] = [
        _trend_factor(df),
        _momentum_factor(df),
        _volatility_factor(df),
    ]
    bench_f = _benchmark_factor(df, benchmark_df)
    if bench_f is not None:
        factors.append(bench_f)

    weights = {
        "Trend": 0.35,
        "Momentum": 0.30,
        "Volatility regime": 0.15,
        "Relative strength vs SPY": 0.20,
    }
    used_weight = sum(weights[f.name] for f in factors)
    composite = sum(f.score * weights[f.name] for f in factors) / used_weight  # -1..+1
    composite_100 = float(composite * 100)

    if composite_100 > 25:
        action = "BUY"
    elif composite_100 < -25:
        action = "SELL"
    else:
        action = "HOLD"

    # Confidence = how much factors agree (low spread → high confidence)
    scores = np.array([f.score for f in factors])
    spread = float(scores.std())
    agreement = float(max(0.0, 1.0 - spread))
    confidence = float(round(min(100, abs(composite) * 70 + agreement * 30), 1))

    # Opportunity = composite shifted to 0..100 with a small confidence kicker
    opportunity = float(round((composite_100 + 100) / 2 * (0.7 + 0.3 * agreement), 1))

    return Signal(
        action=action,
        composite=round(composite_100, 1),
        confidence=confidence,
        opportunity=opportunity,
        factors=factors,
    )
