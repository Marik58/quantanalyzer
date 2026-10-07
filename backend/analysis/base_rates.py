"""Base rates: what usually happened next, from the point-in-time S&P 500 panel.

The mobile-trading-app study (Liu et al. 2025, Information Systems Research) found that
easier trading raised trend-chasing, which cancelled its benefits. The counter used
here is history, not a lecture: when someone looks at (or paper-buys) a stock that just
jumped, show how often stocks that jumped that much went on to beat the index.

Everything comes from `data/cache/screens_panel.pkl` (S&P 500 members, month-ends since
2011, prices by the company's current ticker) and is saved to
context/research/base_rates.json with its sample sizes. The 12-month windows overlap,
so differences come with a t-statistic that allows for that overlap (Newey-West).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis import pit_data

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "context" / "research" / "base_rates.json"

# Past-move buckets, as (label, low, high) on the past return (decimals).
BUCKETS_1M = [("fell 20%+", -9.0, -0.20), ("fell 10-20%", -0.20, -0.10), ("moved less than 10%", -0.10, 0.10),
              ("rose 10-20%", 0.10, 0.20), ("rose 20%+", 0.20, 9.0)]
BUCKETS_12M = [("fell 30%+", -9.0, -0.30), ("fell 0-30%", -0.30, 0.0), ("rose 0-30%", 0.0, 0.30),
               ("rose 30-60%", 0.30, 0.60), ("rose 60%+", 0.60, 99.0)]


def add_past_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Past 1- and 12-month total returns at each month-end, from cached prices."""
    p = panel[(panel["missing"] == "") & panel["ret_12m"].notna() & panel["spy_12m"].notna()].copy()
    dates = sorted(pd.to_datetime(panel["date"].unique()))
    prev = {d.strftime("%Y-%m-%d"): (dates[i - 1] if i >= 1 else None, dates[i - 12] if i >= 12 else None)
            for i, d in enumerate(dates)}
    ahead3 = {d.strftime("%Y-%m-%d"): (dates[i + 3] if i + 3 < len(dates) else None) for i, d in enumerate(dates)}
    cache: dict[str, pd.DataFrame] = {}
    r1, r12, low3 = [], [], []
    for sym, d in zip(p["symbol"], p["date"]):
        if sym not in cache:
            path = pit_data._price_path(sym)
            cache[sym] = pd.read_pickle(path) if path.exists() else None
        px, (d1, d12) = cache[sym], prev[d]
        now = pit_data.price_on(px, pd.Timestamp(d)) if px is not None else None
        a = pit_data.price_on(px, d1) if px is not None and d1 is not None else None
        b = pit_data.price_on(px, d12) if px is not None and d12 is not None else None
        r1.append(now / a - 1 if now and a else np.nan)
        r12.append(now / b - 1 if now and b else np.nan)
        # lowest close in the next 3 months vs today: did it fall 30%+ at any point?
        end3 = ahead3[d]
        if px is not None and now and end3 is not None:
            window = px.loc[(px.index > pd.Timestamp(d)) & (px.index <= end3), "AdjClose"]
            low3.append(float(window.min()) / now - 1 if len(window) else np.nan)
        else:
            low3.append(np.nan)
    p["past_1m"], p["past_12m"], p["low_3m"] = r1, r12, low3
    p["drop30_3m"] = (p["low_3m"] <= -0.30).astype(float).where(p["low_3m"].notna())
    p["beat_12m"] = (p["ret_12m"] > p["spy_12m"]).astype(float)
    p["beat_1m"] = (p["ret_next"] > p["spy_next"]).astype(float)
    return p


def _nw_t(x: pd.Series, lags: int = 12) -> float:
    """t-statistic of a monthly series' mean, allowing for overlap (Newey-West)."""
    x = x.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < lags + 2:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


def bucket_table(p: pd.DataFrame, col: str, buckets: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    """For each past-move bucket: how often it beat SPY next month and over 12 months,
    and whether that differs from all stocks (t, overlap-adjusted)."""
    all_by_month = p.groupby("date")["beat_12m"].mean()
    months = sorted(p["date"].unique())
    rows = []
    for label, lo, hi in buckets:
        b = p[(p[col] > lo) & (p[col] <= hi)]
        if len(b) < 100:
            continue
        # Each month's total surprise: sum over the bucket's stocks of (beat - that month's
        # rate for all stocks). Its mean is proportional to the pooled difference, so the
        # sign always matches the reported rate; months with a crash (many stocks moving
        # together) count as one cluster, and the overlap is handled by Newey-West.
        surprise = (b["beat_12m"] - b["date"].map(all_by_month)).groupby(b["date"]).sum()
        diff = surprise.reindex(months, fill_value=0.0)
        rows.append({"bucket": label, "low": lo, "high": hi, "n": int(len(b)),
                     "months": int(b["date"].nunique()),
                     "beat_spy_next_month": round(float(b["beat_1m"].mean()), 3),
                     "beat_spy_next_12m": round(float(b["beat_12m"].mean()), 3),
                     "fell_30pct_within_3m": round(float(b["drop30_3m"].mean()), 4),
                     # what all stocks did in those same months: the fair comparison
                     "same_months_all_stocks": round(float(b["date"].map(all_by_month).mean()), 3),
                     "avg_excess_12m": round(float((b["ret_12m"] - b["spy_12m"]).mean()), 4),
                     "vs_all_stocks_t": round(_nw_t(diff), 2)})
    return rows


def build(panel: pd.DataFrame | None = None, out: Path = OUT) -> dict[str, Any]:
    if panel is None:
        panel = pd.read_pickle(ROOT / "data" / "cache" / "screens_panel.pkl")
    p = add_past_returns(panel)
    result = {
        "built": date.today().isoformat(),
        "source": "data/cache/screens_panel.pkl via scripts/build_base_rates.py",
        "universe": "S&P 500 members at each month-end (point-in-time), usable rows only",
        "period": f"{p['date'].min()} to {p['date'].max()} (formation months with a full 12 months after)",
        "all_stocks": {"n": int(len(p)), "months": int(p["date"].nunique()),
                       "beat_spy_next_month": round(float(p["beat_1m"].mean()), 3),
                       "beat_spy_next_12m": round(float(p["beat_12m"].mean()), 3),
                       "made_25pct_next_12m": round(float((p["ret_12m"] >= 0.25).mean()), 3),
                       "fell_30pct_within_3m": round(float(p["drop30_3m"].mean()), 4)},
        "after_1_month_move": bucket_table(p, "past_1m", BUCKETS_1M),
        "after_12_month_move": bucket_table(p, "past_12m", BUCKETS_12M),
        "caveats": ["Large caps only (S&P 500), 2011 onward.",
                    "Companies that no longer trade are missing (no free prices).",
                    "12-month windows overlap; t-statistics allow for that (Newey-West, 12 lags).",
                    "History describes what happened; it is not a forecast for one stock."],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def load(path: Path = OUT) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def for_move(past_return: float, horizon: str = "1m", rates: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The bucket a past move falls in, with what usually followed, or None if unknown."""
    rates = rates if rates is not None else load()
    if not rates or past_return is None or not np.isfinite(past_return):
        return None
    key = "after_1_month_move" if horizon == "1m" else "after_12_month_move"
    for row in rates.get(key, []):
        if row["low"] < past_return <= row["high"]:
            return {**row, "all_stocks_beat_spy_next_12m": rates["all_stocks"]["beat_spy_next_12m"],
                    "period": rates["period"]}
    return None
