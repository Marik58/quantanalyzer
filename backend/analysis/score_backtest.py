"""Quant Score Backbone backtest.

Walks the watchlist back through history, computes the price-derived components
of the Quant Score at monthly cutoffs, records forward returns, and reports
information coefficient (IC), information ratio (IR), hit rate, and a long-top
/ short-bottom quintile portfolio.

What is measured (the "backbone" — ~65% of the full Quant Score weight):

    technical  (signals)         0.25 / 0.65
    regime     (HMM)             0.20 / 0.65
    statistics (Sortino)         0.10 / 0.65
    spectral   (cycle phase)     0.05 / 0.65
    topology   (TDA signal)      0.05 / 0.65

What is NOT measured here (35% of full score; requires paid data for an honest
point-in-time backtest):

    valuation  (peer multiples) — needs point-in-time fundamentals (Polygon/FMP)
    sentiment  (news flow)      — yfinance only returns recent headlines
    risk       (risk_framework) — fetches its own data and is not sliceable

This is deliberate: any of those three would inject lookahead bias if backtested
on yfinance. Once a paid feed is wired in, those components can be added.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis import data as data_mod
from backend.analysis import indicators as ind_mod
from backend.analysis import regime_hmm as regime_hmm_mod
from backend.analysis import signals as signals_mod
from backend.analysis import spectral as spectral_mod
from backend.analysis import statistics as stats_mod
from backend.analysis import topology as topology_mod


BACKBONE_WEIGHTS: dict[str, float] = {
    "technical":  0.25,
    "regime":     0.20,
    "statistics": 0.10,
    "spectral":   0.05,
    "topology":   0.05,
}
_BACKBONE_TOTAL = sum(BACKBONE_WEIGHTS.values())   # 0.65

# Components left out of this backtest because they cannot be evaluated
# point-in-time on yfinance without injecting lookahead.
EXCLUDED_COMPONENTS: dict[str, str] = {
    "valuation": "needs point-in-time peer multiples (paid data feed required)",
    "sentiment": "yfinance only returns recent news; no historical archive",
    "risk":      "risk_framework fetches its own data; not sliceable to a cutoff",
}

# Minimum slice length we will score. SMA200 + indicator warmup + HMM minimums.
MIN_SLICE_BARS = 260


# --- Dataclasses ----------------------------------------------------------

@dataclass
class Observation:
    """One scoring event: one ticker, one as-of date, one forward return."""
    date: str                            # ISO date of the cutoff
    ticker: str
    backbone_score: float                # in [-100, +100]
    fwd_return: float                    # forward total return over fwd_days
    fwd_days: int
    components: dict[str, float | None]  # per-component score, None if module failed
    active_weight: float                 # sum of weights of components that voted


@dataclass
class TickerSeries:
    ticker: str
    observations: list[Observation]
    error: str | None = None


@dataclass
class Summary:
    n_observations: int
    n_tickers: int
    n_months: int
    date_range: tuple[str, str]
    fwd_days: int

    # Cross-sectional IC: Spearman rank corr between score and fwd return,
    # measured per month across the cross-section, then averaged.
    ic_mean: float
    ic_std: float
    ic_t_stat: float                     # ic_mean / (ic_std / sqrt(n_months))
    ir_annualized: float                 # ic_mean / ic_std * sqrt(12)

    # Pooled IC: Spearman rank corr across the full pooled sample (all obs).
    pooled_ic: float

    # Hit rates conditioned on score sign.
    hit_rate_long: float                 # P(fwd > 0 | score > 0)
    hit_rate_short: float                # P(fwd < 0 | score < 0)
    n_long_signals: int
    n_short_signals: int

    # Mean forward return by score quintile (Q1 = lowest score, Q5 = highest).
    quintile_returns: list[float]
    quintile_counts: list[int]

    # Long-top-quintile / short-bottom-quintile portfolio, equal-weight,
    # rebalanced monthly. Returns are simple-summed per period (not compounded).
    long_short_mean_monthly: float       # average L-S return per rebalance
    long_short_total: float              # sum across all rebalances


@dataclass
class BacktestResult:
    summary: Summary | None
    series: list[TickerSeries]
    explanations: dict[str, str]
    excluded_components: dict[str, str] = field(default_factory=lambda: dict(EXCLUDED_COMPONENTS))
    error: str | None = None


# --- Component scoring on a slice ----------------------------------------

def _score_technical(history_slice: pd.DataFrame) -> float | None:
    try:
        df = ind_mod.compute_all(history_slice)
        df_ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
        if df_ready.empty:
            df_ready = df.dropna(subset=["SMA50", "MACD_HIST"])
        if df_ready.empty:
            return None
        sig = signals_mod.compute(df_ready, benchmark_df=None)
        return float(sig.composite)
    except Exception:
        return None


def _score_regime(close_slice: pd.Series) -> float | None:
    try:
        # Cap timeline_days to what the slice can support; HMM needs ~120+ bars.
        tl = min(504, max(120, len(close_slice) - 5))
        r = regime_hmm_mod.compute(close_slice, timeline_days=tl)
        conf = float(r.current_confidence or 0.0)
        base = {"Bull": +80.0, "Bear": -80.0, "Sideways": 0.0, "Volatile": -40.0}
        s = base.get(r.current_regime, 0.0) * conf
        return float(np.clip(s, -100.0, 100.0))
    except Exception:
        return None


def _score_statistics(close_slice: pd.Series) -> float | None:
    try:
        s = stats_mod.compute(close_slice, bench_close=None)
        sortino = float(s.downside.sortino_annual)
        return float(np.clip(np.tanh(sortino / 1.5) * 100.0, -100.0, 100.0))
    except Exception:
        return None


def _score_spectral(close_slice: pd.Series) -> float | None:
    try:
        lb = min(504, max(120, len(close_slice) - 5))
        s = spectral_mod.compute(close_slice, lookback_days=lb)
        return float(np.clip(s.cycle.score * 100.0, -100.0, 100.0))
    except Exception:
        return None


def _score_topology(close_slice: pd.Series) -> float | None:
    try:
        t = topology_mod.compute(close_slice)
        if t.error or len(close_slice) < 22:
            return None
        ret20 = float(close_slice.iloc[-1] / close_slice.iloc[-21] - 1.0)
        direction_sign = -1.0 if ret20 > 0.02 else (1.0 if ret20 < -0.02 else 0.0)
        return float(np.clip(t.topological_signal * direction_sign * 50.0, -100.0, 100.0))
    except Exception:
        return None


def _score_backbone(history_slice: pd.DataFrame) -> tuple[float, dict[str, float | None], float]:
    """Return (combined backbone score in [-100, +100], per-component scores, active weight)."""
    close = history_slice["Close"]
    components: dict[str, float | None] = {
        "technical":  _score_technical(history_slice),
        "regime":     _score_regime(close),
        "statistics": _score_statistics(close),
        "spectral":   _score_spectral(close),
        "topology":   _score_topology(close),
    }
    active = {k: v for k, v in components.items() if v is not None}
    if not active:
        return 0.0, components, 0.0
    active_weight = sum(BACKBONE_WEIGHTS[k] for k in active)
    weighted = sum(BACKBONE_WEIGHTS[k] * v for k, v in active.items())
    # Renormalize so missing components do not bias the score toward zero.
    score = weighted / active_weight
    return float(np.clip(score, -100.0, 100.0)), components, float(active_weight)


# --- Per-ticker walk -----------------------------------------------------

def _monthly_cutoffs(history: pd.DataFrame, lookback_years: int, fwd_days: int) -> list[pd.Timestamp]:
    """Trading days at month-end over the last `lookback_years`, leaving room for fwd_days."""
    end_idx = len(history) - fwd_days - 1
    if end_idx < MIN_SLICE_BARS:
        return []
    end_date = history.index[end_idx]
    start_date = end_date - pd.DateOffset(years=lookback_years)
    candidate_idx = history.index[(history.index >= start_date) & (history.index <= end_date)]
    if len(candidate_idx) == 0:
        return []
    monthly = (
        pd.Series(candidate_idx, index=candidate_idx)
        .groupby([candidate_idx.year, candidate_idx.month])
        .last()
        .tolist()
    )
    return [pd.Timestamp(d) for d in monthly]


def compute_for_ticker(ticker: str,
                       lookback_years: int = 3,
                       fwd_days: int = 21) -> TickerSeries:
    td = data_mod.load(ticker, period="5y")
    if td is None or len(td.history) < MIN_SLICE_BARS + fwd_days:
        return TickerSeries(ticker=ticker.upper(), observations=[],
                             error="not enough history (need ~5y for a 3y backtest)")

    history = td.history
    cutoffs = _monthly_cutoffs(history, lookback_years, fwd_days)
    if not cutoffs:
        return TickerSeries(ticker=ticker.upper(), observations=[],
                             error="no valid cutoff dates inside lookback window")

    closes = history["Close"]
    obs: list[Observation] = []
    for cutoff in cutoffs:
        loc = history.index.get_loc(cutoff)
        if loc < MIN_SLICE_BARS or loc + fwd_days >= len(history):
            continue
        history_slice = history.iloc[: loc + 1]
        score, components, active_weight = _score_backbone(history_slice)
        if active_weight == 0.0:
            continue
        fwd_ret = float(closes.iloc[loc + fwd_days] / closes.iloc[loc] - 1.0)
        obs.append(Observation(
            date=cutoff.strftime("%Y-%m-%d"),
            ticker=ticker.upper(),
            backbone_score=score,
            fwd_return=fwd_ret,
            fwd_days=fwd_days,
            components=components,
            active_weight=active_weight,
        ))
    return TickerSeries(ticker=ticker.upper(), observations=obs)


# --- Aggregation ---------------------------------------------------------

def _spearman(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return 0.0
    sa = pd.Series(a).rank()
    sb = pd.Series(b).rank()
    if sa.std(ddof=0) == 0 or sb.std(ddof=0) == 0:
        return 0.0
    return float(sa.corr(sb))


def _summarize(all_obs: list[Observation], fwd_days: int) -> Summary | None:
    if not all_obs:
        return None

    df = pd.DataFrame([
        {"date": o.date, "ticker": o.ticker, "score": o.backbone_score, "fwd": o.fwd_return}
        for o in all_obs
    ])

    # Cross-sectional IC per month (need at least 3 names that month).
    monthly_ics: list[float] = []
    for _, group in df.groupby("date"):
        if len(group) >= 3:
            monthly_ics.append(_spearman(group["score"].tolist(), group["fwd"].tolist()))

    n_months = len(monthly_ics)
    ic_mean = float(np.mean(monthly_ics)) if monthly_ics else 0.0
    ic_std = float(np.std(monthly_ics, ddof=1)) if n_months > 1 else 0.0
    ic_t = (ic_mean / (ic_std / np.sqrt(n_months))) if (ic_std > 0 and n_months > 1) else 0.0
    # Annualize assuming monthly rebalance.
    annual_periods = 252.0 / fwd_days
    ir = (ic_mean / ic_std * np.sqrt(annual_periods)) if ic_std > 0 else 0.0

    pooled_ic = _spearman(df["score"].tolist(), df["fwd"].tolist())

    longs = df[df["score"] > 0]
    shorts = df[df["score"] < 0]
    hit_long = float((longs["fwd"] > 0).mean()) if len(longs) > 0 else 0.0
    hit_short = float((shorts["fwd"] < 0).mean()) if len(shorts) > 0 else 0.0

    # Quintiles by score (Q1 lowest score, Q5 highest).
    quintile_returns: list[float] = []
    quintile_counts: list[int] = []
    if len(df) >= 5:
        try:
            df["q"] = pd.qcut(df["score"], 5, labels=False, duplicates="drop")
            for q in range(5):
                bucket = df[df["q"] == q]["fwd"]
                quintile_returns.append(float(bucket.mean()) if len(bucket) > 0 else 0.0)
                quintile_counts.append(int(len(bucket)))
        except Exception:
            quintile_returns = [0.0] * 5
            quintile_counts = [0] * 5
    else:
        quintile_returns = [0.0] * 5
        quintile_counts = [0] * 5

    # Monthly long-top / short-bottom (equal-weight within bucket).
    monthly_ls: list[float] = []
    for _, group in df.groupby("date"):
        if len(group) < 5:
            continue
        try:
            ranks = group["score"].rank(method="first")
            cut = max(1, len(group) // 5)
            top = group.loc[ranks.nlargest(cut).index, "fwd"].mean()
            bot = group.loc[ranks.nsmallest(cut).index, "fwd"].mean()
            monthly_ls.append(float(top - bot))
        except Exception:
            continue
    ls_mean = float(np.mean(monthly_ls)) if monthly_ls else 0.0
    ls_total = float(np.sum(monthly_ls)) if monthly_ls else 0.0

    return Summary(
        n_observations=len(df),
        n_tickers=int(df["ticker"].nunique()),
        n_months=n_months,
        date_range=(df["date"].min(), df["date"].max()),
        fwd_days=fwd_days,
        ic_mean=ic_mean,
        ic_std=ic_std,
        ic_t_stat=float(ic_t),
        ir_annualized=float(ir),
        pooled_ic=pooled_ic,
        hit_rate_long=hit_long,
        hit_rate_short=hit_short,
        n_long_signals=int(len(longs)),
        n_short_signals=int(len(shorts)),
        quintile_returns=quintile_returns,
        quintile_counts=quintile_counts,
        long_short_mean_monthly=ls_mean,
        long_short_total=ls_total,
    )


def _explain(summary: Summary | None) -> dict[str, str]:
    if summary is None:
        return {"overview": "No observations were produced — every ticker failed history checks."}

    ir = summary.ir_annualized
    ir_label = (
        "strong (>0.5 is institutionally meaningful)" if ir > 0.5
        else "moderate (0.2–0.5 is usable with risk controls)" if ir > 0.2
        else "weak / not statistically convincing" if ir > 0
        else "negative — the score points the wrong way over this window"
    )

    ic_label = (
        "the cross-sectional rank correlation is positive on average — the score "
        "discriminates winners from losers in the same period"
        if summary.ic_mean > 0 else
        "the cross-sectional rank correlation is negative on average — the score "
        "is mis-ordering names in this sample"
    )

    overview = (
        f"Backbone Quant Score backtest: {summary.n_observations} "
        f"(ticker × month) observations across {summary.n_tickers} tickers and "
        f"{summary.n_months} months ({summary.date_range[0]} → "
        f"{summary.date_range[1]}). Forward window: {summary.fwd_days} trading days."
    )

    skill = (
        f"Monthly cross-sectional IC: mean {summary.ic_mean:+.3f}, "
        f"std {summary.ic_std:.3f}, t-stat {summary.ic_t_stat:+.2f}. "
        f"Annualized IR: {summary.ir_annualized:+.2f} — {ir_label}. "
        f"Pooled IC across all observations: {summary.pooled_ic:+.3f}. "
        f"Interpretation: {ic_label}."
    )

    hits = (
        f"Hit rates conditioned on signal direction: "
        f"long signals (n={summary.n_long_signals}) closed positive "
        f"{summary.hit_rate_long*100:.0f}% of the time; "
        f"short signals (n={summary.n_short_signals}) closed negative "
        f"{summary.hit_rate_short*100:.0f}% of the time. "
        f"50% would mean the signal adds no edge over a coin flip."
    )

    quintiles = ", ".join(
        f"Q{i+1}={r*100:+.2f}% (n={c})"
        for i, (r, c) in enumerate(zip(summary.quintile_returns, summary.quintile_counts))
    )

    portfolio = (
        f"Equal-weight long-top-quintile / short-bottom-quintile portfolio, "
        f"rebalanced every {summary.fwd_days} trading days: "
        f"mean per-period return {summary.long_short_mean_monthly*100:+.2f}%, "
        f"summed across the window {summary.long_short_total*100:+.2f}%. "
        f"This is a simple sum, not a compounded total — it isolates the per-rebalance "
        f"edge before transaction costs, financing, and slippage."
    )

    caveats = (
        "Caveats: (1) This is a 'backbone' backtest — it covers ~65% of the "
        "Quant Score by weight (technical, regime, statistics, spectral, topology). "
        "Peer/valuation, sentiment, and risk_framework are excluded because yfinance "
        "cannot supply them point-in-time without lookahead bias. (2) Costs, slippage, "
        "and short-borrow are ignored. (3) The watchlist is a single sector cluster, so "
        "the cross-section is small — IR estimates are noisy."
    )

    return {
        "overview": overview,
        "skill": skill,
        "hits": hits,
        "quintiles": "Mean forward return by score quintile (Q1=lowest score → Q5=highest): " + quintiles,
        "portfolio": portfolio,
        "caveats": caveats,
    }


# --- Top-level entrypoint ------------------------------------------------

def compute(tickers: list[str],
            lookback_years: int = 3,
            fwd_days: int = 21) -> BacktestResult:
    if not tickers:
        return BacktestResult(summary=None, series=[], explanations={},
                              error="no tickers supplied")

    series: list[TickerSeries] = []
    all_obs: list[Observation] = []
    for t in tickers:
        s = compute_for_ticker(t, lookback_years=lookback_years, fwd_days=fwd_days)
        series.append(s)
        all_obs.extend(s.observations)

    summary = _summarize(all_obs, fwd_days=fwd_days)
    return BacktestResult(
        summary=summary,
        series=series,
        explanations=_explain(summary),
    )


# --- Serialization -------------------------------------------------------

def to_dict(r: BacktestResult) -> dict[str, Any]:
    return {
        "summary": asdict(r.summary) if r.summary else None,
        "series": [
            {
                "ticker": s.ticker,
                "error": s.error,
                "n_observations": len(s.observations),
                "observations": [asdict(o) for o in s.observations],
            }
            for s in r.series
        ],
        "excluded_components": r.excluded_components,
        "explanations": r.explanations,
        "error": r.error,
    }
