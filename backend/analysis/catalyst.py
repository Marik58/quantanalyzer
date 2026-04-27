"""Catalyst tracker — upcoming events that move the stock.

Pulls six near-term catalyst signals from yfinance:

  1. Next earnings date + EPS estimate
  2. Ex-dividend date + dividend amount + yield
  3. Analyst price targets (high / median / low) and upside-to-median
  4. Recent rating changes (last 30 days)
  5. Short interest as % of float
  6. Insider ownership %

Every field is wrapped in try/except — yfinance frequently returns None or
KeyError for short interest, insider ownership, and rating-change history.
The module degrades gracefully: missing fields become None and the
explanation reads "n/a" rather than raising.

Output mirrors the convention used by valuation.py / quant_score.py:
  - dataclass result with an `explanations` dict (plain English per field)
  - to_dict() helper for JSON serialization
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_SESSION = curl_requests.Session(impersonate="chrome")


@dataclass
class Catalysts:
    ticker: str
    earnings: dict[str, Any] | None = None
    dividend: dict[str, Any] | None = None
    analyst_targets: dict[str, Any] | None = None
    rating_changes_30d: list[dict[str, Any]] = field(default_factory=list)
    short_interest_pct_float: float | None = None
    insider_ownership_pct: float | None = None
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _safe(fn, default=None):
    """Run a callable, swallow any exception, return default."""
    try:
        v = fn()
        return v if v is not None else default
    except Exception:
        return default


def _days_until(d: Any) -> int | None:
    if d is None:
        return None
    try:
        if isinstance(d, str):
            d = pd.to_datetime(d).date()
        elif isinstance(d, pd.Timestamp):
            d = d.date()
        elif isinstance(d, datetime):
            d = d.date()
        today = datetime.now(timezone.utc).date()
        return (d - today).days
    except Exception:
        return None


def _earnings(t: yf.Ticker) -> dict[str, Any] | None:
    cal = _safe(lambda: t.calendar)
    if not cal:
        return None
    # yfinance returns a dict like {"Earnings Date": [date1, date2], "Earnings Average": 1.52, ...}
    if isinstance(cal, dict):
        dates = cal.get("Earnings Date") or []
        if not dates:
            return None
        next_date = dates[0]
        eps_est = cal.get("Earnings Average")
        return {
            "next_date": str(next_date),
            "eps_estimate": float(eps_est) if eps_est is not None else None,
            "days_until": _days_until(next_date),
        }
    return None


def _dividend(t: yf.Ticker, info: dict[str, Any]) -> dict[str, Any] | None:
    ex_date = info.get("exDividendDate")
    rate = info.get("dividendRate")
    yld = info.get("dividendYield")
    if ex_date is None and rate is None:
        return None
    # yfinance ex-div date is usually a unix timestamp
    ex_date_str = None
    if ex_date is not None:
        try:
            ex_date_str = datetime.fromtimestamp(int(ex_date), tz=timezone.utc).date().isoformat()
        except Exception:
            ex_date_str = str(ex_date)
    return {
        "ex_date": ex_date_str,
        "amount": float(rate) if rate is not None else None,
        "yield_pct": float(yld) if yld is not None else None,
        "days_until": _days_until(ex_date_str),
    }


def _analyst_targets(t: yf.Ticker, info: dict[str, Any]) -> dict[str, Any] | None:
    tgt = _safe(lambda: t.analyst_price_targets)
    if not tgt:
        return None
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    median = tgt.get("median") or tgt.get("mean")
    upside = None
    if current and median and current > 0:
        upside = (float(median) - float(current)) / float(current)
    return {
        "high": float(tgt["high"]) if tgt.get("high") is not None else None,
        "median": float(median) if median is not None else None,
        "low": float(tgt["low"]) if tgt.get("low") is not None else None,
        "current": float(current) if current is not None else None,
        "upside_to_median_pct": upside,
        "n_analysts": int(tgt["numberOfAnalystOpinions"]) if tgt.get("numberOfAnalystOpinions") is not None else None,
    }


def _rating_changes(t: yf.Ticker, days: int = 30) -> list[dict[str, Any]]:
    df = _safe(lambda: t.upgrades_downgrades)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    df = df.copy()
    if df.index.name == "GradeDate" or "GradeDate" not in df.columns:
        df = df.reset_index()
    if "GradeDate" not in df.columns:
        return []
    df["GradeDate"] = pd.to_datetime(df["GradeDate"], utc=True, errors="coerce")
    df = df[df["GradeDate"] >= cutoff].sort_values("GradeDate", ascending=False)
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        out.append({
            "date": row["GradeDate"].date().isoformat(),
            "firm": str(row.get("Firm", "")),
            "from": str(row.get("FromGrade", "") or ""),
            "to": str(row.get("ToGrade", "") or ""),
            "action": str(row.get("Action", "") or ""),
        })
    return out


def _explain(c: Catalysts) -> dict[str, str]:
    e: dict[str, str] = {}

    # Earnings
    if c.earnings and c.earnings.get("days_until") is not None:
        d = c.earnings["days_until"]
        eps = c.earnings.get("eps_estimate")
        eps_txt = f" Street is expecting EPS of ${eps:.2f}." if eps is not None else ""
        if d < 0:
            e["earnings"] = f"Earnings already reported ({-d} days ago)."
        elif d <= 7:
            e["earnings"] = (f"Earnings in {d} days — high-volatility window. "
                             f"Expect outsized moves.{eps_txt}")
        elif d <= 30:
            e["earnings"] = f"Earnings in {d} days — within the next month.{eps_txt}"
        else:
            e["earnings"] = f"Earnings in {d} days — no near-term print.{eps_txt}"
    else:
        e["earnings"] = "No earnings date available from yfinance."

    # Dividend
    if c.dividend:
        d = c.dividend.get("days_until")
        amt = c.dividend.get("amount")
        yld = c.dividend.get("yield_pct")
        bits = []
        if amt is not None:
            bits.append(f"pays ${amt:.2f}/share")
        if yld is not None:
            bits.append(f"yielding {yld * 100:.2f}%")
        head = ", ".join(bits) if bits else "dividend on file"
        if d is not None and d >= 0:
            e["dividend"] = f"{head.capitalize()}; next ex-div in {d} days."
        else:
            e["dividend"] = f"{head.capitalize()}; ex-div date n/a or in past."
    else:
        e["dividend"] = "Non-dividend-paying or data unavailable."

    # Analyst targets
    if c.analyst_targets and c.analyst_targets.get("median") is not None:
        a = c.analyst_targets
        ups = a.get("upside_to_median_pct")
        n = a.get("n_analysts")
        n_txt = f" ({n} analysts)" if n else ""
        if ups is None:
            e["analyst_targets"] = (f"Median target ${a['median']:.2f}, "
                                    f"range ${a['low']:.2f}–${a['high']:.2f}.{n_txt}")
        elif ups > 0.15:
            e["analyst_targets"] = (f"Street median ${a['median']:.2f} implies "
                                    f"+{ups * 100:.1f}% upside — meaningfully bullish.{n_txt}")
        elif ups < -0.05:
            e["analyst_targets"] = (f"Street median ${a['median']:.2f} implies "
                                    f"{ups * 100:.1f}% downside — Street is cautious.{n_txt}")
        else:
            e["analyst_targets"] = (f"Street median ${a['median']:.2f} ({ups * 100:+.1f}%) "
                                    f"— roughly fair-valued by consensus.{n_txt}")
    else:
        e["analyst_targets"] = "Analyst price targets unavailable."

    # Rating changes
    n_chg = len(c.rating_changes_30d)
    if n_chg == 0:
        e["rating_changes_30d"] = "No analyst rating changes in the last 30 days."
    else:
        ups = sum(1 for r in c.rating_changes_30d if "up" in r.get("action", "").lower())
        downs = sum(1 for r in c.rating_changes_30d if "down" in r.get("action", "").lower())
        e["rating_changes_30d"] = (f"{n_chg} rating change(s) in last 30 days "
                                    f"({ups} upgrade, {downs} downgrade).")

    # Short interest
    if c.short_interest_pct_float is None:
        e["short_interest"] = "Short interest data not reported by yfinance for this ticker."
    else:
        si = c.short_interest_pct_float * 100
        if si < 3:
            e["short_interest"] = f"Short interest {si:.1f}% of float — low; no crowded short."
        elif si < 10:
            e["short_interest"] = f"Short interest {si:.1f}% of float — moderate."
        elif si < 20:
            e["short_interest"] = f"Short interest {si:.1f}% of float — elevated; squeeze risk on positive news."
        else:
            e["short_interest"] = f"Short interest {si:.1f}% of float — heavily shorted."

    # Insider ownership
    if c.insider_ownership_pct is None:
        e["insider_ownership"] = "Insider ownership not reported."
    else:
        io = c.insider_ownership_pct * 100
        if io < 1:
            e["insider_ownership"] = f"Insider ownership {io:.2f}% — low skin in the game (typical of large caps)."
        elif io < 5:
            e["insider_ownership"] = f"Insider ownership {io:.1f}% — moderate alignment."
        else:
            e["insider_ownership"] = f"Insider ownership {io:.1f}% — high alignment with shareholders."

    return e


@cached(ttl_seconds=CACHE_TTL, key_fn=lambda t: f"catalyst:{t.upper()}")
def compute(ticker: str) -> Catalysts:
    ticker = ticker.upper()
    try:
        t = yf.Ticker(ticker, session=_SESSION)
        info = _safe(lambda: t.info, default={}) or {}
    except Exception as ex:
        return Catalysts(ticker=ticker, error=f"yfinance fetch failed: {ex}")

    c = Catalysts(
        ticker=ticker,
        earnings=_earnings(t),
        dividend=_dividend(t, info),
        analyst_targets=_analyst_targets(t, info),
        rating_changes_30d=_rating_changes(t),
        short_interest_pct_float=_safe(lambda: float(info["shortPercentOfFloat"]))
            if info.get("shortPercentOfFloat") is not None else None,
        insider_ownership_pct=_safe(lambda: float(info["heldPercentInsiders"]))
            if info.get("heldPercentInsiders") is not None else None,
    )
    c.explanations = _explain(c)
    return c


def to_dict(c: Catalysts) -> dict[str, Any]:
    return {
        "ticker": c.ticker,
        "earnings": c.earnings,
        "dividend": c.dividend,
        "analyst_targets": c.analyst_targets,
        "rating_changes_30d": c.rating_changes_30d,
        "short_interest_pct_float": c.short_interest_pct_float,
        "insider_ownership_pct": c.insider_ownership_pct,
        "explanations": c.explanations,
        "error": c.error,
    }
