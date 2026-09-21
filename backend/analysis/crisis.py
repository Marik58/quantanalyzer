"""Crisis event studies — how the app's own risk tools behaved when markets broke.

The AI-lending paper (Liu, Li & Zheng, ISR 2024) uses natural disasters as
external shocks to test whether a system helps when it matters. The market
equivalent is asking what our diagnostics said during the four worst stretches
of the last decade, rather than on the calm average day.

For each window we measure three things, all strictly point-in-time:

  VaR breaches   Each day's loss is compared with the 95% value-at-risk
                 estimated from the PREVIOUS 252 trading days only. About 5%
                 of days should breach. Far more means the risk model was
                 underestimating danger exactly when it counted.

  Regime timing  The HMM is refitted on data up to each sampled date, so the
                 label is what the app would have shown that morning. We report
                 how many trading days passed before it first called Bear or
                 Volatile.

  Drawdown       Peak-to-trough inside the window.

Convention: `compute()` -> dataclass -> `to_dict()` -> endpoint. Results are
cached for a week, since history does not change.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend import cache
from backend.analysis import data as data_mod
from backend.analysis import regime_hmm as regime_mod

log = logging.getLogger(__name__)

TRADING_DAYS_YEAR = 252
VAR_LOOKBACK = 252          # trailing window for the VaR estimate
VAR_QUANTILE = 5            # 95% VaR
REGIME_EVERY = 5            # refit the HMM every 5 trading days (weekly)
PRE_DAYS = 20               # context shown before the window opens
CACHE_TTL = 7 * 24 * 3600   # a week; past crises do not move

CRISIS_WINDOWS: list[dict[str, str]] = [
    {"id": "covid", "name": "COVID crash", "start": "2020-02-19", "end": "2020-04-30",
     "note": "The fastest 30% drawdown in S&P 500 history, then an equally fast rebound."},
    {"id": "rates2022", "name": "2022 rate shock", "start": "2022-01-03", "end": "2022-10-14",
     "note": "A slow grind lower as the Fed raised rates — a very different shape from 2020."},
    {"id": "svb", "name": "SVB collapse", "start": "2023-03-01", "end": "2023-04-30",
     "note": "A sector-specific bank run; the index barely moved while regional banks halved."},
    {"id": "vol2024", "name": "August 2024 volatility spike", "start": "2024-07-15",
     "end": "2024-08-30",
     "note": "A yen carry-trade unwind: violent for two days, then over."},
]


@dataclass
class DayPoint:
    date: str
    indexed: float              # price rebased to 100 at the start of the window
    ret_pct: float
    var_pct: float | None       # 95% VaR estimated from the prior 252 days
    breach: bool


@dataclass
class RegimePoint:
    date: str
    regime: str
    confidence: float


@dataclass
class CrisisStudy:
    window_id: str
    window_name: str
    note: str
    ticker: str
    start: str
    end: str
    n_days: int
    max_drawdown_pct: float
    total_return_pct: float
    var_breaches: int
    var_breaches_expected: float
    worst_day_pct: float
    days_to_bear_call: int | None      # trading days until the HMM said Bear/Volatile
    first_bear_date: str | None
    series: list[DayPoint] = field(default_factory=list)
    regimes: list[RegimePoint] = field(default_factory=list)
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_windows() -> list[dict[str, str]]:
    return [dict(w) for w in CRISIS_WINDOWS]


def _window(window_id: str) -> dict[str, str] | None:
    return next((w for w in CRISIS_WINDOWS if w["id"] == window_id), None)


def _study(ticker: str, window_id: str) -> CrisisStudy:
    w = _window(window_id)
    if w is None:
        return CrisisStudy(window_id=window_id, window_name="?", note="", ticker=ticker,
                           start="", end="", n_days=0, max_drawdown_pct=0.0,
                           total_return_pct=0.0, var_breaches=0, var_breaches_expected=0.0,
                           worst_day_pct=0.0, days_to_bear_call=None, first_bear_date=None,
                           error=f"unknown crisis window '{window_id}'")

    td = data_mod.load(ticker, period="10y")
    if td is None or td.history is None or td.history.empty:
        return CrisisStudy(window_id=w["id"], window_name=w["name"], note=w["note"],
                           ticker=ticker, start=w["start"], end=w["end"], n_days=0,
                           max_drawdown_pct=0.0, total_return_pct=0.0, var_breaches=0,
                           var_breaches_expected=0.0, worst_day_pct=0.0,
                           days_to_bear_call=None, first_bear_date=None,
                           error=f"no price history for {ticker}")

    close = td.history["Close"].dropna()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    rets = close.pct_change()

    start, end = pd.Timestamp(w["start"]), pd.Timestamp(w["end"])
    in_window = close.index[(close.index >= start) & (close.index <= end)]
    if len(in_window) < 5:
        return CrisisStudy(window_id=w["id"], window_name=w["name"], note=w["note"],
                           ticker=ticker, start=w["start"], end=w["end"], n_days=0,
                           max_drawdown_pct=0.0, total_return_pct=0.0, var_breaches=0,
                           var_breaches_expected=0.0, worst_day_pct=0.0,
                           days_to_bear_call=None, first_bear_date=None,
                           error=f"{ticker} has no price history inside this window "
                                 f"(listed later, or data missing)")

    first_loc = close.index.get_loc(in_window[0])
    last_loc = close.index.get_loc(in_window[-1])
    base = float(close.iloc[first_loc])
    ctx_from = max(0, first_loc - PRE_DAYS)

    # --- day-by-day VaR breaches, using only prior data for the estimate ----
    points: list[DayPoint] = []
    breaches = 0
    for loc in range(ctx_from, last_loc + 1):
        date = close.index[loc]
        r = float(rets.iloc[loc]) if loc > 0 and np.isfinite(rets.iloc[loc]) else 0.0
        prior = rets.iloc[max(0, loc - VAR_LOOKBACK):loc].dropna()
        var = float(np.percentile(prior, VAR_QUANTILE)) if len(prior) >= 60 else None
        inside = loc >= first_loc
        breach = bool(var is not None and inside and r < var)
        if breach:
            breaches += 1
        points.append(DayPoint(date=date.strftime("%Y-%m-%d"),
                               indexed=round(float(close.iloc[loc]) / base * 100.0, 2),
                               ret_pct=round(r * 100.0, 2),
                               var_pct=None if var is None else round(var * 100.0, 2),
                               breach=breach))

    window_close = close.iloc[first_loc:last_loc + 1]
    dd = float((window_close / window_close.cummax() - 1.0).min()) * 100.0
    total = (float(window_close.iloc[-1]) / base - 1.0) * 100.0
    worst = float(rets.iloc[first_loc:last_loc + 1].min()) * 100.0
    n_days = len(window_close)

    # --- regime label as it would have appeared, refitted weekly ------------
    regimes: list[RegimePoint] = []
    days_to_bear: int | None = None
    first_bear: str | None = None
    for step, loc in enumerate(range(first_loc, last_loc + 1, REGIME_EVERY)):
        hist = close.iloc[:loc + 1]
        if len(hist) < 120:
            continue
        try:
            r = regime_mod.compute(hist.iloc[-504:], timeline_days=120)
            label = r.current_regime
            conf = float(r.current_confidence or 0.0)
        except Exception:
            continue
        regimes.append(RegimePoint(date=close.index[loc].strftime("%Y-%m-%d"),
                                   regime=label, confidence=round(conf, 3)))
        if days_to_bear is None and label in ("Bear", "Volatile"):
            days_to_bear = loc - first_loc
            first_bear = close.index[loc].strftime("%Y-%m-%d")

    study = CrisisStudy(
        window_id=w["id"], window_name=w["name"], note=w["note"], ticker=ticker.upper(),
        start=w["start"], end=w["end"], n_days=n_days,
        max_drawdown_pct=round(dd, 1), total_return_pct=round(total, 1),
        var_breaches=breaches,
        var_breaches_expected=round(n_days * VAR_QUANTILE / 100.0, 1),
        worst_day_pct=round(worst, 1),
        days_to_bear_call=days_to_bear, first_bear_date=first_bear,
        series=points, regimes=regimes,
    )
    study.explanations = _explain(study)
    return study


def _explain(s: CrisisStudy) -> dict[str, str]:
    ex: dict[str, str] = {"overview": (
        f"{s.ticker} through the {s.window_name} ({s.start} to {s.end}): "
        f"{s.total_return_pct:+.1f}% over {s.n_days} trading days, with a "
        f"{s.max_drawdown_pct:.1f}% peak-to-trough drawdown and a worst single day of "
        f"{s.worst_day_pct:.1f}%. {s.note}")}

    ratio = (s.var_breaches / s.var_breaches_expected) if s.var_breaches_expected > 0 else 0.0
    if s.var_breaches == 0:
        ex["var"] = ("No day breached the 95% value-at-risk estimate. The risk model held up "
                     "in this window.")
    elif ratio >= 2:
        ex["var"] = (
            f"{s.var_breaches} days breached the 95% VaR, against about "
            f"{s.var_breaches_expected:.1f} expected — roughly {ratio:.0f}x too many. VaR is "
            f"estimated from the prior year of returns, so a calm year sets a threshold that a "
            f"crisis blows through repeatedly. This is the concrete version of the warning in "
            f"the glossary: VaR describes ordinary days, not the ones that hurt.")
    else:
        ex["var"] = (
            f"{s.var_breaches} days breached the 95% VaR against about "
            f"{s.var_breaches_expected:.1f} expected — close to what the model promised.")

    if s.days_to_bear_call is None:
        ex["regime"] = (
            "The regime model never called Bear or Volatile inside this window. It is fitted on "
            "trend and volatility, so a fast shock can be over before the labels move.")
    else:
        ex["regime"] = (
            f"The regime model first called Bear or Volatile on {s.first_bear_date}, "
            f"{s.days_to_bear_call} trading days after the window opened. It is refitted on data "
            f"up to each date, so this is what the app would have shown that morning — useful as "
            f"a description of conditions, not as a warning you could have traded on.")

    ex["caveats"] = (
        "Two things to keep in mind. The regime labels are relative clusters fitted to each "
        "stock's own history, so a 'Bear' label means the quietest or weakest of four fitted "
        "states, not an actual bear market — it can appear while prices are still rising. And "
        "the window dates were chosen with hindsight. Read this as a worked example of how the "
        "tools behave under stress, not as evidence that they predict stress.")
    return ex


def compute(ticker: str = "SPY", window_id: str = "covid") -> CrisisStudy:
    ticker = (ticker or "SPY").upper().strip()
    key = f"crisis:{ticker}:{window_id}:v1"
    hit = cache.get(key, CACHE_TTL)
    if hit is not None:
        return hit
    study = _study(ticker, window_id)
    if study.error is None:
        cache.set_(key, study)
    return study


def to_dict(s: CrisisStudy) -> dict[str, Any]:
    return s.to_dict()
