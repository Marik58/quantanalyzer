"""Market regime classification: trending / ranging / breakout."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Regime:
    label: str          # "uptrend" | "downtrend" | "ranging" | "breakout_up" | "breakout_down"
    strength: float     # 0..1
    description: str


def classify(df: pd.DataFrame) -> Regime:
    """Uses 50/200 SMA slope, BB width, and recent close vs BB to label the regime."""
    close = df["Close"]
    sma50 = df["SMA50"].dropna()
    sma200 = df["SMA200"].dropna()
    bb_low, bb_mid, bb_high = df["BB_LOW"], df["BB_MID"], df["BB_HIGH"]

    last_close = float(close.iloc[-1])
    last_bb_low = float(bb_low.iloc[-1])
    last_bb_high = float(bb_high.iloc[-1])
    last_bb_mid = float(bb_mid.iloc[-1])

    # Breakout: latest close pierces a band
    bb_width = (last_bb_high - last_bb_low) / last_bb_mid if last_bb_mid else 0
    if last_close > last_bb_high:
        return Regime("breakout_up", min(1.0, bb_width * 10),
                      "Closing above the upper Bollinger band — recent expansion above the typical range.")
    if last_close < last_bb_low:
        return Regime("breakout_down", min(1.0, bb_width * 10),
                      "Closing below the lower Bollinger band — recent breakdown below the typical range.")

    # Trend strength: slope of 50 MA over last 30 sessions, normalized by price
    if len(sma50) >= 30:
        slope = (sma50.iloc[-1] - sma50.iloc[-30]) / 30 / last_close
    else:
        slope = 0.0
    above_200 = len(sma200) and last_close > float(sma200.iloc[-1])

    # Score the trend: |slope| * 100 maps roughly to "% per day". 0.1%/day is meaningful.
    trend_strength = float(min(1.0, abs(slope) * 1000))

    if trend_strength > 0.3:
        if slope > 0 and above_200:
            return Regime("uptrend", trend_strength,
                          "50-day moving average sloping up and price holding above the 200-day average.")
        if slope < 0 and not above_200:
            return Regime("downtrend", trend_strength,
                          "50-day moving average sloping down and price below the 200-day average.")

    return Regime("ranging", 1.0 - trend_strength,
                  "Price oscillating without a dominant direction — moving averages are flat.")
