"""yfinance wrapper. All price/info access for the rest of the app goes through here."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))

# Yahoo blocks plain Python requests; curl_cffi impersonates Chrome's TLS fingerprint.
_SESSION = curl_requests.Session(impersonate="chrome")


@dataclass
class TickerData:
    ticker: str
    history: pd.DataFrame
    info: dict[str, Any]

    @property
    def last_price(self) -> float:
        return float(self.history["Close"].iloc[-1])


@cached(ttl_seconds=CACHE_TTL, key_fn=lambda ticker, period="2y": f"hist:{ticker}:{period}")
def _fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    df = yf.Ticker(ticker, session=_SESSION).history(period=period, auto_adjust=True)
    if df is None or df.empty:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda ticker: f"info:{ticker}")
def _fetch_info(ticker: str) -> dict[str, Any]:
    try:
        info = yf.Ticker(ticker, session=_SESSION).info or {}
    except Exception:
        info = {}
    keep = {
        "shortName", "longName", "sector", "industry", "marketCap",
        "trailingPE", "forwardPE", "priceToBook", "dividendYield",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta", "currency",
    }
    return {k: info.get(k) for k in keep if k in info}


def load(ticker: str, period: str = "2y") -> TickerData | None:
    ticker = ticker.upper().strip()
    hist = _fetch_history(ticker, period)
    if hist is None or len(hist) < 50:
        return None
    info = _fetch_info(ticker)
    return TickerData(ticker=ticker, history=hist, info=info)
