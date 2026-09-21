"""Point-in-time S&P 500 membership — the fix for survivorship bias.

Backtesting on today's index members is testing a list of winners: the
companies that were dropped along the way have vanished from the sample. This
module answers "who was actually in the index on date X?" using the public
membership history maintained at github.com/fja05680/sp500 (MIT licensed),
which tracks index changes back to 1996.

Usage in a backtest: score every ticker that was a member on the scoring date,
not the ones that are members today.

    from backend.analysis import universe
    members = universe.members_on("2023-08-31")     # ~503 tickers
    sample  = universe.sample_members(80, as_of="2023-08-31", seed=1)

Honest limitation: knowing who was in the index is only half the problem. The
free price sources still lack history for many delisted companies, so some
survivorship bias remains until a proper research database (CRSP) is used.
`coverage_report()` measures exactly how much is missing rather than hiding it.
"""
from __future__ import annotations

import csv
import io
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

log = logging.getLogger(__name__)

SOURCE_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
              "sp500_ticker_start_end.csv")
LOCAL_COPY = Path(__file__).resolve().parent.parent.parent / "data" / "universe" / "sp500_membership.csv"
REFRESH_DAYS = 30


@dataclass
class Membership:
    ticker: str
    start: pd.Timestamp
    end: pd.Timestamp | None      # None = still a member


_CACHE: list[Membership] | None = None


def _download() -> str | None:
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(SOURCE_URL, impersonate="chrome", timeout=30)
        if r.status_code == 200 and "ticker" in r.text[:200]:
            return r.text
        log.warning("membership download returned HTTP %s", r.status_code)
    except Exception as exc:
        log.warning("membership download failed: %s", exc)
    return None


def _load_raw(force_refresh: bool = False) -> str:
    """CSV text, from the local copy when it is fresh, otherwise re-downloaded."""
    fresh = False
    if LOCAL_COPY.exists():
        age_days = (datetime.now().timestamp() - LOCAL_COPY.stat().st_mtime) / 86400
        fresh = age_days < REFRESH_DAYS
    if fresh and not force_refresh:
        return LOCAL_COPY.read_text(encoding="utf-8")

    text = _download()
    if text is None:
        if LOCAL_COPY.exists():
            log.warning("using stale membership file — download unavailable")
            return LOCAL_COPY.read_text(encoding="utf-8")
        raise RuntimeError(
            "Could not download S&P 500 membership history and no local copy exists. "
            f"Save {SOURCE_URL} to {LOCAL_COPY} and retry.")
    LOCAL_COPY.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_COPY.write_text(text, encoding="utf-8")
    return text


def load(force_refresh: bool = False) -> list[Membership]:
    global _CACHE
    if _CACHE is not None and not force_refresh:
        return _CACHE
    rows: list[Membership] = []
    for row in csv.DictReader(io.StringIO(_load_raw(force_refresh))):
        tkr = (row.get("ticker") or "").strip().upper()
        if not tkr:
            continue
        start = pd.to_datetime(row.get("start_date") or None, errors="coerce")
        end_raw = (row.get("end_date") or "").strip()
        end = pd.to_datetime(end_raw, errors="coerce") if end_raw else None
        if pd.isna(start):
            continue
        rows.append(Membership(ticker=tkr, start=start,
                               end=None if end is None or pd.isna(end) else end))
    _CACHE = rows
    return rows


def to_yahoo(ticker: str) -> str:
    """Index tickers use dots for share classes; Yahoo uses hyphens (BRK.B -> BRK-B)."""
    return ticker.strip().upper().replace(".", "-")


def members_on(as_of: str | date | pd.Timestamp) -> set[str]:
    """Tickers that were in the index on `as_of` (Yahoo-style symbols)."""
    ts = pd.Timestamp(as_of)
    return {to_yahoo(m.ticker) for m in load()
            if m.start <= ts and (m.end is None or m.end >= ts)}


def members_between(start: str | date, end: str | date) -> set[str]:
    """Anyone who was a member at any point in the window — including names
    that were later removed. This is the pool a survivorship-free test draws
    from."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return {to_yahoo(m.ticker) for m in load()
            if m.start <= e and (m.end is None or m.end >= s)}


def leavers_between(start: str | date, end: str | date) -> set[str]:
    """Members at the start of the window who had left by the end — the names a
    today's-constituents backtest silently drops."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return {to_yahoo(m.ticker) for m in load()
            if m.start <= s and m.end is not None and s <= m.end <= e}


def sample_members(n: int, as_of: str | date = "2023-08-31",
                   seed: int = 1, include_leavers: bool = True,
                   until: str | date | None = None) -> list[str]:
    """A random sample of index members as of a date.

    include_leavers keeps names that were later removed — without them the
    sample is survivorship-biased again, which is the whole point.
    """
    pool = sorted(members_on(as_of))
    if not include_leavers and until is not None:
        gone = leavers_between(as_of, until)
        pool = [t for t in pool if t not in gone]
    rng = random.Random(seed)
    rng.shuffle(pool)
    return sorted(pool[:max(1, min(n, len(pool)))])


def membership_filter(tickers: Iterable[str] | None = None):
    """Returns fn(date) -> set of tickers that were members that day."""
    allowed = {t.upper() for t in tickers} if tickers else None

    def _fn(as_of: str) -> set[str]:
        members = members_on(as_of)
        return members & allowed if allowed is not None else members

    return _fn


def coverage_report(tickers: Iterable[str], period: str = "5y") -> dict[str, Any]:
    """How many of these tickers can the free data source actually deliver?

    The gap is the residual survivorship bias: delisted names are exactly the
    ones missing, and they are the ones that would drag returns down.
    """
    from backend.analysis import data as data_mod

    have, missing = [], []
    for t in tickers:
        td = data_mod.load(t, period=period)
        (have if td is not None and not td.history.empty else missing).append(t)
    total = len(have) + len(missing)
    return {
        "requested": total,
        "with_data": len(have),
        "missing": len(missing),
        "missing_pct": round(100.0 * len(missing) / total, 1) if total else 0.0,
        "missing_tickers": sorted(missing),
    }


def stats() -> dict[str, Any]:
    rows = load()
    current = [m for m in rows if m.end is None]
    return {
        "source": SOURCE_URL,
        "tickers_ever": len(rows),
        "current_members": len(current),
        "earliest_start": min(m.start for m in rows).strftime("%Y-%m-%d"),
        "local_copy": str(LOCAL_COPY),
    }
