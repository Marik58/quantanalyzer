"""Point-in-time inputs for the Growth and Value Screen backtests (Roadmap Phase 3).

For every month-end since 2011 this answers three questions, each only with what
was knowable on that date:

1. Who was in the S&P 500? (membership rows in data/universe/ticker_cik.csv)
2. Which SEC company was that? (the verified company ID from the ticker map)
3. What did its stock price and its latest annual report say?

Prices come from Yahoo, looked up by the company's ticker TODAY according to the
SEC (FB's history lives under META), never by the old ticker, which may now
belong to a different company (BBT). Financials are first-filed SEC values,
used only after the day they were filed. Every gap is counted, never filled.

The output is a "panel": one row per member per month, with the features the
screens use and the next month's return. It is saved so the analysis can be
re-run in seconds, and it is the same point-in-time snapshot a future AI
analyst's evidence packet will be built from.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from backend import edgar

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSE_CSV = ROOT / "data" / "universe" / "ticker_cik.csv"
PRICE_DIR = ROOT / "data" / "cache" / "pit_prices"
PRICE_START = "2009-06-01"
PRICE_MAX_AGE_DAYS = 7
STALE_FY_DAYS = 550          # a latest annual report older than this is too stale to use
MCAP_BOUNDS = (3e8, 6e12)    # outside this, the share count or price is wrong for an S&P member
FIELDS = ("revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow",
          "capex", "total_assets", "total_liabilities", "equity", "diluted_shares",
          "shares_outstanding")


# --- 1 + 2: who was in the index, and which company was it ---------------------

@dataclass
class Member:
    ticker: str
    start: str
    end: str | None
    cik: int | None
    status: str
    valid_from: str = ""            # before this, the ID belonged to a different company
    predecessor: int | None = None  # before `switch`, this ID's filings are the company's
    switch: str = ""


def membership(path: Path = UNIVERSE_CSV, links_path: Path | None = None) -> list[Member]:
    """Membership rows with their verified company IDs, plus the links from
    backend/cik_links.py (predecessor IDs, and IDs that took over a ticker later)."""
    from backend import cik_links
    links = cik_links.load(links_path) if links_path else cik_links.load()
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = Member(r["ticker"], r["start"], r["end"] or None,
                       int(r["cik"]) if r["cik"] else None, r["status"])
            link = links.get((m.ticker, m.start))
            if link:
                m.valid_from, m.predecessor, m.switch = link["valid_from"], link["predecessor"], link["switch"]
                if m.status == "split" and link["predecessor"]:
                    m.cik, m.status = link["cik"], "verified"     # resolved by an accounting link
            out.append(m)
    return out


def active_on(members: Iterable[Member], t: str) -> list[Member]:
    return [m for m in members if m.start <= t and (m.end is None or t < m.end)]


def yahoo_symbol(m: Member) -> tuple[str | None, str]:
    """(symbol, why missing). Former members are found by the company's ticker today."""
    if m.status != "verified" or m.cik is None:
        return None, f"company ID not verified ({m.status})"
    if m.end is None:
        return m.ticker.replace(".", "-"), ""
    tickers = edgar.submissions(m.cik).get("tickers") or []
    if not tickers:
        return None, "no longer trades (the SEC lists no current ticker)"
    plain = [t for t in tickers if "-" not in t] or tickers
    return plain[0].replace(".", "-"), ""


# --- 3a: prices -------------------------------------------------------------------

def _price_path(symbol: str) -> Path:
    return PRICE_DIR / f"{symbol}.pkl"


def load_prices(symbols: Iterable[str], progress: Callable[[str], None] | None = None,
                batch: int = 80) -> dict[str, pd.DataFrame]:
    """symbol -> DataFrame[Close (split-adjusted), AdjClose (total return), Splits].
    Symbols Yahoo has nothing for are left out (and remembered for a week)."""
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    missing_path = PRICE_DIR / "_missing.json"
    known_missing = json.loads(missing_path.read_text()) if missing_path.exists() else {}
    now = time.time()
    out: dict[str, pd.DataFrame] = {}
    todo = []
    for s in sorted(set(symbols)):
        p = _price_path(s)
        if p.exists() and now - p.stat().st_mtime < PRICE_MAX_AGE_DAYS * 86400:
            out[s] = pd.read_pickle(p)
        elif now - known_missing.get(s, 0) < PRICE_MAX_AGE_DAYS * 86400:
            continue
        else:
            todo.append(s)
    fetched = download_prices(todo, PRICE_START, progress=progress, batch=batch)
    for s in todo:
        if s in fetched:
            fetched[s].to_pickle(_price_path(s))
            out[s] = fetched[s]
        else:
            known_missing[s] = now
    missing_path.write_text(json.dumps(known_missing))
    return out


def download_prices(symbols: list[str], start: str, progress: Callable[[str], None] | None = None,
                    batch: int = 80) -> dict[str, pd.DataFrame]:
    """Fresh daily prices from Yahoo (nothing cached): symbol -> Close, AdjClose, Splits."""
    import yfinance as yf
    from curl_cffi import requests as curl_requests

    session = curl_requests.Session(impersonate="chrome")
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        raw = yf.download(chunk, start=start, auto_adjust=False, actions=True,
                          group_by="ticker", threads=True, progress=False, session=session)
        for s in chunk:
            try:
                if not isinstance(raw.columns, pd.MultiIndex):
                    sub = raw
                elif s in raw.columns.get_level_values(0):
                    sub = raw[s]
                else:                                   # a one-symbol batch: (field, symbol) order
                    sub = raw.xs(s, axis=1, level=1)
                df = pd.DataFrame({"Close": sub["Close"], "AdjClose": sub["Adj Close"],
                                   "Splits": sub.get("Stock Splits", 0.0)}).dropna(subset=["Close"])
            except KeyError:
                continue
            if len(df) < 20:
                continue
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df["Splits"] = df["Splits"].fillna(0.0)
            out[s] = df
        if progress:
            progress(f"prices {min(i + batch, len(symbols))}/{len(symbols)} downloaded")
        time.sleep(1.0)
    return out


def split_factor_after(prices: pd.DataFrame, day: str | pd.Timestamp) -> float:
    """Product of all split ratios after `day` (a 4-for-1 split counts as 4)."""
    s = prices["Splits"]
    later = s[(s.index > pd.Timestamp(day)) & (s > 0)]
    return float(np.prod(later.to_numpy())) if len(later) else 1.0


def market_cap(shares: float, shares_filed: str, prices: pd.DataFrame, t: pd.Timestamp) -> float | None:
    """Shares (as reported on their filing date) x price on t, in the same share units.

    Yahoo's Close is adjusted for every split up to today; the reported share count
    only for splits up to its filing date. Converting the shares to today's units
    makes the two match: cap = shares x (splits after filing) x Close(t)."""
    close = price_on(prices, t, "Close")
    if close is None or not shares or shares <= 0:
        return None
    return float(shares * split_factor_after(prices, shares_filed) * close)


def price_on(prices: pd.DataFrame, t: pd.Timestamp, col: str = "AdjClose",
             max_gap_days: int = 7) -> float | None:
    """Last price on or before t, if it is recent enough to count as trading on t."""
    idx = prices.index.searchsorted(t, side="right") - 1
    if idx < 0 or (t - prices.index[idx]).days > max_gap_days:
        return None
    v = float(prices[col].iloc[idx])
    return v if np.isfinite(v) and v > 0 else None


def period_return(prices: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> tuple[float | None, bool]:
    """(total return from t0 to t1, ended early). A series that stops before t1
    (delisted, bought out) returns to its last price; the flag says so."""
    p0 = price_on(prices, t0)
    if p0 is None:
        return None, False
    idx = prices.index.searchsorted(t1, side="right") - 1
    p1 = float(prices["AdjClose"].iloc[idx])
    ended = (t1 - prices.index[idx]).days > 7
    return (p1 / p0 - 1.0 if np.isfinite(p1) and p1 > 0 else None), ended


# --- 3b: the latest annual report, as known on a date ---------------------------

def _closest(rows: list[dict[str, Any]], target: date, tol_days: int) -> dict[str, Any] | None:
    best, gap = None, tol_days + 1
    for r in rows:
        g = abs((date.fromisoformat(r["end"]) - target).days)
        if g < gap:
            best, gap = r, g
    return best


def snapshot_features(values: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Features from one point-in-time set of annual values (each metric's
    first-filed rows known on the snapshot date). None without revenue."""
    rev = values.get("revenue") or []
    if not rev:
        return None
    e0 = date.fromisoformat(rev[-1]["end"])

    def val(metric: str, years_back: int = 0, tol: int = 25) -> dict[str, Any] | None:
        target = e0 - timedelta(days=round(365.25 * years_back))
        return _closest(values.get(metric) or [], target, tol + 15 * years_back)

    f: dict[str, Any] = {"fy_end": e0.isoformat(), "filed": rev[-1]["filed"]}
    for m in FIELDS:
        if m in ("diluted_shares", "shares_outstanding"):
            continue
        r = val(m)
        f[m] = r["value"] if r else None
    for k, yb in (("revenue_1", 1), ("revenue_3", 3)):
        r = val("revenue", yb)
        f[k] = r["value"] if r else None
    r = val("operating_income", 1)
    f["operating_income_1"] = r["value"] if r else None
    d0, d1 = val("diluted_shares"), val("diluted_shares", 1)
    f["shares"], f["shares_filed"] = (d0["value"], d0["filed"]) if d0 else (None, None)
    f["shares_1"] = d1["value"] if d1 else None
    # The cover-page count (dated just after the year end) is the second official source,
    # used when the diluted count is missing or filed with the wrong scale (McDonald's
    # tagged 732.3 shares for 2023, meaning 732.3 million).
    cover = [r for r in values.get("shares_outstanding") or [] if r["end"] >= e0.isoformat()]
    f["cover_shares"], f["cover_filed"] = (cover[0]["value"], cover[0]["filed"]) if cover else (None, None)
    return f


class Fundamentals:
    """A company's annual-report features at any past date, without look-ahead."""

    def __init__(self, facts: dict[str, Any]):
        filed = set()
        for taxonomy in facts.get("facts", {}).values():
            for node in taxonomy.values():
                for rows in node.get("units", {}).values():
                    filed.update(r["filed"] for r in rows
                                 if r.get("form") in edgar._ANNUAL_FORMS and r.get("filed", "") >= "2009")
        self.dates: list[str] = sorted(filed)
        self.snaps: list[dict[str, Any] | None] = [
            snapshot_features({m: edgar.annual_values(facts, m, d) for m in FIELDS}) for d in self.dates]

    def as_of(self, t: str) -> dict[str, Any] | None:
        """Features from reports filed strictly before t, if the latest is fresh enough."""
        i = int(np.searchsorted(self.dates, t, side="left")) - 1
        if i < 0 or self.snaps[i] is None:
            return None
        f = self.snaps[i]
        if (date.fromisoformat(t) - date.fromisoformat(f["fy_end"])).days > STALE_FY_DAYS:
            return None
        return f


# --- The panel -------------------------------------------------------------------

def month_ends(calendar: pd.DatetimeIndex, start: str) -> list[pd.Timestamp]:
    """Last trading day of each complete month from `start` on."""
    s = pd.Series(calendar, index=calendar)
    ends = list(s.groupby([calendar.year, calendar.month]).max())
    last = calendar[-1]
    if ends and ends[-1] == last and (last + pd.offsets.BDay(1)).month == last.month:
        ends = ends[:-1]                           # the current month isn't finished
    return [d for d in ends if d >= pd.Timestamp(start)]


def _fundamentals_cache() -> Callable[[int], Fundamentals | None]:
    cache: dict[int, Fundamentals | None] = {}

    def get(cik: int) -> Fundamentals | None:
        if cik not in cache:
            try:
                cache[cik] = Fundamentals(edgar.compact_facts(cik))
            except edgar.EdgarError:
                cache[cik] = None
        return cache[cik]

    get.cache = cache   # type: ignore[attr-defined]
    return get


def month_rows(members: list[Member], t: pd.Timestamp,
               symbols: dict[tuple[str, str], tuple[str | None, str]],
               prices: dict[str, pd.DataFrame],
               fundamentals: Callable[[int], Fundamentals | None]) -> list[dict[str, Any]]:
    """Every S&P 500 member on date t, with what was knowable on t: the latest annual
    report filed before t and the market value on t. No returns (those come after t).
    A row the screens can use has missing == ""; otherwise `missing` says why not."""
    ts = t.strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for m in active_on(members, ts):
        sym, why = symbols.get((m.ticker, m.start), (None, "joined after start"))
        row: dict[str, Any] = {"date": ts, "ticker": m.ticker, "cik": m.cik, "symbol": sym}
        if m.cik is not None and m.cik in seen:
            continue                            # second share class of the same company
        if m.cik is not None:
            seen.add(m.cik)
        if sym is None:
            row["missing"] = why
        elif sym not in prices or price_on(prices[sym], t) is None:
            row["missing"] = "no price on this date"
        elif m.valid_from and ts < m.valid_from and not (m.predecessor and ts < m.switch):
            row["missing"] = "company ID belonged to another company then"
        else:
            source = m.predecessor if m.predecessor and ts < m.switch else m.cik
            fu = fundamentals(source)
            f = fu.as_of(ts) if fu else None
            if f is None:
                row["missing"] = "no fresh annual report" if fu else "no SEC financial data"
            else:
                cap, tried, cap_source = None, 0, ""
                for sh, sh_filed, src in ((f.get("shares"), f.get("shares_filed"), "diluted"),
                                          (f.get("cover_shares"), f.get("cover_filed"), "cover")):
                    c = market_cap(sh, sh_filed, prices[sym], t) if sh else None
                    tried += c is not None
                    if c is not None and MCAP_BOUNDS[0] <= c <= MCAP_BOUNDS[1]:
                        cap, cap_source = c, src
                        break
                if cap is None:
                    row["missing"] = "implausible market value" if tried else "no share count"
                else:
                    row.update({k: v for k, v in f.items()})
                    row["mcap"], row["mcap_shares"], row["missing"] = cap, cap_source, ""
        rows.append(row)
    return rows


def current_members() -> list[Member]:
    return [m for m in membership() if m.end is None]


def live_snapshot(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Today's members as the screens would see them on `as_of` (default: the last
    trading day in SPY's prices). `prices` must include SPY and members' symbols."""
    members = current_members()
    symbols = {(m.ticker, m.start): yahoo_symbol(m) for m in members}
    t = as_of if as_of is not None else prices["SPY"].index[-1]
    return pd.DataFrame(month_rows(members, t, symbols, prices, _fundamentals_cache()))


def build_panel(start: str = "2011-01-31", progress: Callable[[str], None] | None = None,
                members: list[Member] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per S&P 500 member per month-end. Returns (panel, coverage report)."""
    say = progress or (lambda _m: None)
    members = members if members is not None else membership()
    symbols: dict[tuple[str, str], tuple[str | None, str]] = {}
    for m in members:
        if m.end is None or m.end >= start:
            symbols[(m.ticker, m.start)] = yahoo_symbol(m)
    wanted = {s for s, _ in symbols.values() if s} | {"SPY"}
    prices = load_prices(wanted, progress=say)
    if "SPY" not in prices:
        raise RuntimeError("no SPY prices; can't build the calendar")
    dates = month_ends(prices["SPY"].index, start)

    fundamentals = _fundamentals_cache()
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(dates[:-1]):
        ts = t.strftime("%Y-%m-%d")
        for row in month_rows(members, t, symbols, prices, fundamentals):
            if row["missing"] == "":
                sym = row["symbol"]
                ret, ended = period_return(prices[sym], t, dates[i + 1])
                row["ret_next"], row["ended_early"] = ret, ended
                row["missing"] = "" if ret is not None else "no next price"
                if i + 12 < len(dates):
                    row["ret_12m"] = period_return(prices[sym], t, dates[i + 12])[0]
            rows.append(row)
        if i % 12 == 0:
            say(f"panel {ts}: {len(rows)} rows so far, {len(fundamentals.cache)} companies' filings parsed")
    panel = pd.DataFrame(rows)
    spy = prices["SPY"]
    bench = {d.strftime("%Y-%m-%d"): period_return(spy, d, dates[j + 1])[0]
             for j, d in enumerate(dates[:-1])}
    bench12 = {d.strftime("%Y-%m-%d"): period_return(spy, d, dates[j + 12])[0]
               for j, d in enumerate(dates[:-12])}
    panel["spy_next"] = panel["date"].map(bench)
    panel["spy_12m"] = panel["date"].map(bench12)
    if "ret_12m" not in panel:
        panel["ret_12m"] = np.nan
    return panel, coverage(panel)


def coverage(panel: pd.DataFrame) -> dict[str, Any]:
    n = len(panel)
    usable = int((panel["missing"] == "").sum())
    reasons = panel.loc[panel["missing"] != "", "missing"].value_counts().to_dict()
    return {"member_months": n, "usable": usable, "usable_share": round(usable / n, 4) if n else 0.0,
            "missing_by_reason": {k: int(v) for k, v in reasons.items()},
            "ended_early": int(panel.get("ended_early", pd.Series(dtype=bool)).fillna(False).sum())}
