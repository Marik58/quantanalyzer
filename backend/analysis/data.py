"""yfinance wrapper. All price/info access for the rest of the app goes through here.

Resilience model
----------------
Yahoo Finance is the only data source and it is known to flake — transient
"possibly delisted; no price data found" errors hit healthy large-caps under
burst load. Three layers protect callers from a single bad call:

  1. Retry with exponential backoff (configurable via YF_MAX_RETRIES /
     YF_RETRY_BASE_DELAY).
  2. Stale-cache fallback: if every retry fails, return the last cached value
     even when it is outside CACHE_TTL, up to CACHE_STALE_SECONDS old.
  3. Structured logging: every failure path emits a WARNING/ERROR with the
     ticker and reason so silent failures stop.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.cache import get as cache_get, set_ as cache_set

log = logging.getLogger(__name__)

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
# Stale-fallback window: how old a cached entry may be and still be returned
# when the live API is failing. 30 days is generous; the alternative is None.
CACHE_STALE_SECONDS = int(os.getenv("CACHE_STALE_SECONDS", str(60 * 60 * 24 * 30)))
MAX_RETRIES = max(1, int(os.getenv("YF_MAX_RETRIES", "3")))
RETRY_BASE_DELAY = float(os.getenv("YF_RETRY_BASE_DELAY", "1.0"))

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


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, pd.DataFrame):
        return value.empty
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _yf_call_with_retry(ticker: str, kind: str, fn: Callable[[], Any]) -> tuple[Any, str | None]:
    """Call `fn()` up to MAX_RETRIES times with exponential backoff.

    Returns (value, None) on success, (None, error_string) on final failure.
    Empty values (None / empty DataFrame / empty dict) are treated as failures
    because yfinance returns those on rate-limit / transient errors instead of
    raising.
    """
    last_err: str | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            value = fn()
            if not _is_empty(value):
                return value, None
            last_err = "empty response from yfinance"
        except Exception as e:  # noqa: BLE001 — yfinance raises many types
            last_err = f"{type(e).__name__}: {e}"

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.warning(
                "yfinance %s for %s failed (attempt %d/%d): %s — retrying in %.1fs",
                kind, ticker, attempt, MAX_RETRIES, last_err, delay,
            )
            time.sleep(delay)

    log.error(
        "yfinance %s for %s gave up after %d attempts: %s",
        kind, ticker, MAX_RETRIES, last_err,
    )
    return None, last_err


def _fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    key = f"hist:{ticker}:{period}"
    fresh = cache_get(key, CACHE_TTL)
    if fresh is not None:
        return fresh

    def _call() -> pd.DataFrame:
        return yf.Ticker(ticker, session=_SESSION).history(period=period, auto_adjust=True)

    df, err = _yf_call_with_retry(ticker, "history", _call)
    if df is None:
        stale = cache_get(key, CACHE_STALE_SECONDS)
        if stale is not None:
            log.warning(
                "Using stale cache for history(%s, %s) — live API failed: %s",
                ticker, period, err,
            )
            return stale
        return None

    df.index = pd.to_datetime(df.index).tz_localize(None)
    cache_set(key, df)
    return df


def _fetch_info(ticker: str) -> dict[str, Any]:
    key = f"info:{ticker}"
    fresh = cache_get(key, CACHE_TTL * 4)
    if fresh is not None:
        return fresh

    def _call() -> dict[str, Any]:
        return yf.Ticker(ticker, session=_SESSION).info or {}

    info, err = _yf_call_with_retry(ticker, "info", _call)
    if info is None:
        stale = cache_get(key, CACHE_STALE_SECONDS)
        if stale is not None:
            log.warning(
                "Using stale cache for info(%s) — live API failed: %s",
                ticker, err,
            )
            return stale
        return {}

    keep = {
        "shortName", "longName", "sector", "industry", "marketCap",
        "trailingPE", "forwardPE", "priceToBook", "dividendYield",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta", "currency",
    }
    pared = {k: info.get(k) for k in keep if k in info}
    cache_set(key, pared)
    return pared


def load(ticker: str, period: str = "2y") -> TickerData | None:
    ticker = ticker.upper().strip()
    hist = _fetch_history(ticker, period)
    if hist is None:
        log.error("load(%s, %s) failed — no history available (live + stale cache exhausted)",
                  ticker, period)
        return None
    if len(hist) < 50:
        log.warning("load(%s, %s) returning None — only %d bars (need >=50)",
                    ticker, period, len(hist))
        return None
    info = _fetch_info(ticker)
    return TickerData(ticker=ticker, history=hist, info=info)
