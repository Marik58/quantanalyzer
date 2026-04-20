"""Technical indicators. Pure functions, all operate on a price DataFrame with Close/High/Low."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift()
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0):
    mid = sma(close, window)
    std = close.rolling(window).std()
    return mid - n_std * std, mid, mid + n_std * std


def annualized_volatility(close: pd.Series, window: int = 30) -> pd.Series:
    returns = close.pct_change()
    return returns.rolling(window).std() * np.sqrt(252)


def returns_over(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return float("nan")
    return float(close.iloc[-1] / close.iloc[-days - 1] - 1)


def max_drawdown(close: pd.Series, lookback: int = 252) -> float:
    window = close.iloc[-lookback:] if len(close) > lookback else close
    running_max = window.cummax()
    dd = window / running_max - 1
    return float(dd.min())


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a standard set of indicator columns to the price frame."""
    out = df.copy()
    close = out["Close"]
    out["SMA50"] = sma(close, 50)
    out["SMA200"] = sma(close, 200)
    out["EMA20"] = ema(close, 20)
    out["RSI14"] = rsi(close, 14)
    macd_line, signal_line, hist = macd(close)
    out["MACD"] = macd_line
    out["MACD_SIGNAL"] = signal_line
    out["MACD_HIST"] = hist
    out["ATR14"] = atr(out, 14)
    bb_lo, bb_mid, bb_hi = bollinger(close, 20, 2)
    out["BB_LOW"] = bb_lo
    out["BB_MID"] = bb_mid
    out["BB_HIGH"] = bb_hi
    out["VOL30"] = annualized_volatility(close, 30)
    return out
