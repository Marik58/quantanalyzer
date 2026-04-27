"""Risk framework module.

Institutional-grade risk assessment surfaced as a standalone endpoint:
  - Historical stress tests against named crisis windows
  - Macro correlations vs SPY/TLT/GLD/USO/UUP
  - Tail risk (historical + parametric Student-t VaR / CVaR)
  - Drawdown profile (max, current, worst rolling, duration)
  - Kelly Criterion position sizing

All calculations are empirical from price history — no simulated paths.
Kept separate from the existing backend.analysis.risk rating used by the
signal/report pipeline so those outputs stay stable.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests
from scipy import stats as scipy_stats

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_SESSION = curl_requests.Session(impersonate="chrome")

# --- Historical stress windows (peak → trough of the S&P 500) -------------
STRESS_WINDOWS: list[tuple[str, str, str]] = [
    ("2008 Financial Crisis", "2007-10-09", "2009-03-09"),
    ("2011 Eurozone Crisis",  "2011-04-29", "2011-10-03"),
    ("2018 Q4 Selloff",       "2018-09-20", "2018-12-24"),
    ("2020 COVID Crash",      "2020-02-19", "2020-03-23"),
    ("2022 Bear Market",      "2022-01-03", "2022-10-12"),
]

# Macro ETFs for correlation panel
MACRO_ETFS: list[tuple[str, str]] = [
    ("SPY", "US Equities (S&P 500)"),
    ("TLT", "Long Treasuries (20+yr)"),
    ("GLD", "Gold"),
    ("USO", "Oil"),
    ("UUP", "US Dollar"),
]


# --- Dataclasses ----------------------------------------------------------

@dataclass
class StressScenario:
    name: str
    period: str
    market_drawdown: float | None       # SPY peak-to-trough over window
    estimated_impact: float | None      # ticker's estimated return
    method: str                          # "historical" | "beta_estimated" | "na"
    explanation: str


@dataclass
class MacroCorrelation:
    asset: str
    label: str
    correlation_1y: float | None
    interpretation: str


@dataclass
class DrawdownStats:
    max_drawdown: float
    max_drawdown_start: str | None
    max_drawdown_trough: str | None
    current_drawdown: float             # from 1-year rolling high
    worst_3m: float
    worst_6m: float
    max_drawdown_duration_days: int     # longest continuous streak below prior peak


@dataclass
class TailRisk:
    var_95_historical: float
    var_99_historical: float
    cvar_95: float
    cvar_99: float
    var_95_student_t: float
    var_99_student_t: float
    student_t_df: float
    notes: str


@dataclass
class KellyAnalysis:
    win_rate: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float | None
    kelly_fraction: float
    half_kelly: float
    recommendation: str


@dataclass
class RiskFrameworkResult:
    ticker: str
    n_observations: int
    beta_vs_spy: float | None
    stress_scenarios: list[StressScenario]
    macro_correlations: list[MacroCorrelation]
    drawdown: DrawdownStats | None
    tail_risk: TailRisk | None
    kelly: KellyAnalysis | None
    overall_risk_score: float           # 0..100, higher = riskier
    overall_risk_label: str             # "Low" | "Moderate" | "High" | "Extreme"
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None


# --- Fetch helpers --------------------------------------------------------

@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda t: f"risk_fw_hist:{t}")
def _fetch_full_history(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(ticker, session=_SESSION).history(period="max", auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _close_from(df: pd.DataFrame | None) -> pd.Series | None:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    s = df["Close"].dropna()
    return s if len(s) > 0 else None


# --- Math helpers ---------------------------------------------------------

def _window_return(close: pd.Series, start: str, end: str) -> float | None:
    """Return start→end total return if both dates have data in the series."""
    if close is None or close.empty:
        return None
    sliced = close.loc[start:end]
    if len(sliced) < 5:
        return None
    return float(sliced.iloc[-1] / sliced.iloc[0] - 1.0)


def _peak_to_trough(close: pd.Series, start: str, end: str) -> float | None:
    """Worst peak-to-trough return within a window (always ≤ 0)."""
    if close is None or close.empty:
        return None
    sliced = close.loc[start:end]
    if len(sliced) < 5:
        return None
    peak = sliced.cummax()
    dd = (sliced / peak) - 1.0
    return float(dd.min())


def _beta(stock_ret: pd.Series, market_ret: pd.Series) -> float | None:
    aligned = pd.concat([stock_ret, market_ret], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return None
    cov = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
    var = aligned.iloc[:, 1].var()
    if var == 0 or not np.isfinite(var):
        return None
    return float(cov / var)


def _max_drawdown_duration(close: pd.Series) -> int:
    running_max = close.cummax()
    in_dd = (close < running_max).values
    longest = cur = 0
    for bad in in_dd:
        if bad:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return int(longest)


def _drawdown_stats(close: pd.Series) -> DrawdownStats:
    running_max = close.cummax()
    dd = (close / running_max) - 1.0
    trough_idx = dd.idxmin()
    peak_idx = close.loc[:trough_idx].idxmax() if trough_idx is not None else None

    last_year = close.iloc[-min(252, len(close)):]
    curr_dd = float(last_year.iloc[-1] / last_year.max() - 1.0)

    # Worst rolling N-day total returns
    ret_3m = close.pct_change(63).dropna()
    ret_6m = close.pct_change(126).dropna()
    worst_3m = float(ret_3m.min()) if len(ret_3m) else 0.0
    worst_6m = float(ret_6m.min()) if len(ret_6m) else 0.0

    return DrawdownStats(
        max_drawdown=float(dd.min()),
        max_drawdown_start=peak_idx.strftime("%Y-%m-%d") if peak_idx is not None else None,
        max_drawdown_trough=trough_idx.strftime("%Y-%m-%d") if trough_idx is not None else None,
        current_drawdown=curr_dd,
        worst_3m=worst_3m,
        worst_6m=worst_6m,
        max_drawdown_duration_days=_max_drawdown_duration(close),
    )


def _tail_risk(returns: pd.Series) -> TailRisk:
    r = returns.dropna().values
    var_95_hist = float(np.percentile(r, 5))
    var_99_hist = float(np.percentile(r, 1))
    cvar_95 = float(np.mean(r[r <= var_95_hist])) if np.any(r <= var_95_hist) else var_95_hist
    cvar_99 = float(np.mean(r[r <= var_99_hist])) if np.any(r <= var_99_hist) else var_99_hist

    try:
        df_, loc, scale = scipy_stats.t.fit(r)
        var_95_t = float(scipy_stats.t.ppf(0.05, df_, loc=loc, scale=scale))
        var_99_t = float(scipy_stats.t.ppf(0.01, df_, loc=loc, scale=scale))
    except Exception:
        df_ = float("nan")
        var_95_t = var_95_hist
        var_99_t = var_99_hist

    if np.isfinite(df_) and df_ < 5:
        notes = (f"Student-t df ≈ {df_:.1f} → very fat tails. Extreme moves are "
                 f"meaningfully more likely than a normal distribution would predict.")
    elif np.isfinite(df_) and df_ < 10:
        notes = (f"Student-t df ≈ {df_:.1f} → moderately fat tails. Tail risk is "
                 f"non-trivial but not extreme.")
    elif np.isfinite(df_):
        notes = (f"Student-t df ≈ {df_:.1f} → tails behave close to normal. "
                 f"Historical VaR estimates are reasonably reliable.")
    else:
        notes = "Student-t fit failed; only historical VaR reported."

    return TailRisk(
        var_95_historical=var_95_hist,
        var_99_historical=var_99_hist,
        cvar_95=cvar_95,
        cvar_99=cvar_99,
        var_95_student_t=var_95_t,
        var_99_student_t=var_99_t,
        student_t_df=float(df_) if np.isfinite(df_) else 0.0,
        notes=notes,
    )


def _kelly(returns: pd.Series) -> KellyAnalysis:
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r < 0]
    n = len(r)
    win_rate = float(len(wins) / n) if n else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0  # negative
    ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else None
    if ratio and ratio > 0:
        f_star = win_rate - (1 - win_rate) / ratio
    else:
        f_star = 0.0
    f_star = float(np.clip(f_star, -1.0, 1.0))
    half = float(f_star / 2.0)

    if f_star <= 0:
        rec = ("Full Kelly ≤ 0 — on daily bars this name does not carry a positive "
               "edge. Position sizing by Kelly would suggest no exposure. Kelly on "
               "daily returns is noisy; use this as one input, not a verdict.")
    elif f_star < 0.05:
        rec = (f"Full Kelly = {f_star:.1%}, half-Kelly = {half:.1%}. Thin edge — "
               f"small position sizing suggested.")
    elif f_star < 0.25:
        rec = (f"Full Kelly = {f_star:.1%}, half-Kelly = {half:.1%}. Moderate edge. "
               f"Half-Kelly is the practical target; full Kelly maximizes growth but "
               f"suffers deep interim drawdowns.")
    else:
        rec = (f"Full Kelly = {f_star:.1%}, half-Kelly = {half:.1%}. Large edge on "
               f"this sample — treat with skepticism since daily Kelly overstates "
               f"position size. Half-Kelly or lower is the institutional norm.")

    return KellyAnalysis(
        win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
        win_loss_ratio=float(ratio) if ratio is not None else None,
        kelly_fraction=f_star, half_kelly=half, recommendation=rec,
    )


def _interpret_corr(c: float) -> str:
    a = abs(c)
    direction = "positive" if c > 0 else "negative"
    if a < 0.2:
        return f"weakly {direction} (near-zero)"
    if a < 0.4:
        return f"weakly {direction}"
    if a < 0.6:
        return f"moderately {direction}"
    if a < 0.8:
        return f"strongly {direction}"
    return f"very strongly {direction}"


def _macro_correlations(stock_ret: pd.Series) -> list[MacroCorrelation]:
    out: list[MacroCorrelation] = []
    window = stock_ret.iloc[-min(252, len(stock_ret)):]
    for ticker, label in MACRO_ETFS:
        df = _fetch_full_history(ticker)
        c = _close_from(df)
        if c is None:
            out.append(MacroCorrelation(asset=ticker, label=label,
                                         correlation_1y=None,
                                         interpretation="data unavailable"))
            continue
        other_ret = c.pct_change().dropna()
        other_ret = other_ret.iloc[-min(252, len(other_ret)):]
        aligned = pd.concat([window, other_ret], axis=1, join="inner").dropna()
        if len(aligned) < 30:
            out.append(MacroCorrelation(asset=ticker, label=label,
                                         correlation_1y=None,
                                         interpretation="insufficient overlap"))
            continue
        corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        out.append(MacroCorrelation(asset=ticker, label=label,
                                     correlation_1y=corr,
                                     interpretation=_interpret_corr(corr)))
    return out


def _stress_tests(stock_close: pd.Series, spy_close: pd.Series | None,
                  beta: float | None) -> list[StressScenario]:
    out: list[StressScenario] = []
    for name, start, end in STRESS_WINDOWS:
        market_dd = _peak_to_trough(spy_close, start, end) if spy_close is not None else None
        # Prefer historical realized drawdown for the ticker if it traded the window
        ticker_dd = _peak_to_trough(stock_close, start, end)
        if ticker_dd is not None:
            method = "historical"
            impact = ticker_dd
            expl = (f"{name}: ticker drew down {ticker_dd:.1%} vs SPY "
                    f"{market_dd:.1%}." if market_dd is not None
                    else f"{name}: ticker drew down {ticker_dd:.1%}.")
        elif market_dd is not None and beta is not None:
            method = "beta_estimated"
            impact = float(beta * market_dd)
            expl = (f"{name}: ticker did not trade this window. Estimated "
                    f"impact = β({beta:.2f}) × SPY({market_dd:.1%}) = {impact:.1%}.")
        else:
            method = "na"
            impact = None
            expl = f"{name}: insufficient data to estimate impact."
        out.append(StressScenario(
            name=name, period=f"{start} → {end}",
            market_drawdown=market_dd, estimated_impact=impact,
            method=method, explanation=expl,
        ))
    return out


# --- Composite score -----------------------------------------------------

def _overall_score(ann_vol: float, max_dd: float, curr_dd: float,
                   var_99: float) -> float:
    vol_s = np.clip(ann_vol / 0.60, 0.0, 1.0) * 100       # 60% vol → full risk
    dd_s = np.clip(abs(max_dd) / 0.80, 0.0, 1.0) * 100    # 80% DD  → full risk
    cur_s = np.clip(abs(curr_dd) / 0.40, 0.0, 1.0) * 100  # 40% DD  → full risk
    var_s = np.clip(abs(var_99) / 0.10, 0.0, 1.0) * 100   # -10% d  → full risk
    return float(0.30 * vol_s + 0.30 * dd_s + 0.20 * cur_s + 0.20 * var_s)


def _risk_label(score: float) -> str:
    if score < 25:
        return "Low"
    if score < 50:
        return "Moderate"
    if score < 75:
        return "High"
    return "Extreme"


# --- Main entrypoint ------------------------------------------------------

def compute(ticker: str) -> RiskFrameworkResult:
    ticker = ticker.upper().strip()
    stock_df = _fetch_full_history(ticker)
    stock_close = _close_from(stock_df)

    if stock_close is None or len(stock_close) < 120:
        return RiskFrameworkResult(
            ticker=ticker, n_observations=0, beta_vs_spy=None,
            stress_scenarios=[], macro_correlations=[],
            drawdown=None, tail_risk=None, kelly=None,
            overall_risk_score=0.0, overall_risk_label="n/a",
            error=f"Not enough price history for {ticker} (need ≥120 bars).",
        )

    stock_ret = stock_close.pct_change().dropna()
    spy_close = _close_from(_fetch_full_history("SPY"))
    spy_ret = spy_close.pct_change().dropna() if spy_close is not None else pd.Series(dtype=float)

    beta = _beta(stock_ret, spy_ret) if len(spy_ret) else None

    stress = _stress_tests(stock_close, spy_close, beta)
    macros = _macro_correlations(stock_ret)
    dd = _drawdown_stats(stock_close)
    tail = _tail_risk(stock_ret)
    kelly = _kelly(stock_ret)

    ann_vol = float(stock_ret.std() * np.sqrt(252))
    score = _overall_score(ann_vol, dd.max_drawdown, dd.current_drawdown,
                           tail.var_99_historical)
    label = _risk_label(score)

    explanations = _explain(ticker, beta, ann_vol, dd, tail, kelly,
                            stress, macros, score, label)

    return RiskFrameworkResult(
        ticker=ticker,
        n_observations=len(stock_ret),
        beta_vs_spy=beta,
        stress_scenarios=stress,
        macro_correlations=macros,
        drawdown=dd,
        tail_risk=tail,
        kelly=kelly,
        overall_risk_score=score,
        overall_risk_label=label,
        explanations=explanations,
        error=None,
    )


def _explain(ticker: str, beta: float | None, ann_vol: float,
             dd: DrawdownStats, tail: TailRisk, kelly: KellyAnalysis,
             stress: list[StressScenario],
             macros: list[MacroCorrelation],
             score: float, label: str) -> dict[str, str]:
    beta_txt = f"{beta:.2f}" if beta is not None else "n/a"
    overview = (
        f"{ticker} annualized vol = {ann_vol:.1%}, β vs SPY = {beta_txt}. "
        f"Composite risk score = {score:.0f}/100 → {label}. "
        f"The score blends volatility, max drawdown, current drawdown, and "
        f"one-day 99% VaR — higher means a wider distribution of bad outcomes."
    )

    worst_stress = min(
        (s for s in stress if s.estimated_impact is not None),
        key=lambda s: s.estimated_impact, default=None,
    )
    if worst_stress is not None:
        stress_txt = (
            f"Worst historical analog: {worst_stress.name} "
            f"({worst_stress.estimated_impact:.1%}, {worst_stress.method}). "
            f"If a similar shock repeated today, this is the order-of-magnitude "
            f"loss to expect — not a forecast, a reference point."
        )
    else:
        stress_txt = "No stress windows had sufficient overlap with available data."

    strong_macro = max(macros, key=lambda m: abs(m.correlation_1y or 0.0), default=None)
    if strong_macro is not None and strong_macro.correlation_1y is not None:
        macro_txt = (
            f"Strongest 1-year correlation: {strong_macro.asset} "
            f"({strong_macro.correlation_1y:+.2f}, {strong_macro.interpretation}). "
            f"Use this to check whether the portfolio is doubling up on the same "
            f"underlying macro exposure."
        )
    else:
        macro_txt = "Macro correlation data unavailable."

    tail_txt = (
        f"Historical 1-day VaR 95% = {tail.var_95_historical:.1%}, "
        f"99% = {tail.var_99_historical:.1%}. "
        f"CVaR 99% = {tail.cvar_99:.1%} (average loss on the worst 1% of days). "
        f"{tail.notes}"
    )

    dd_txt = (
        f"Max drawdown (full history): {dd.max_drawdown:.1%} "
        f"({dd.max_drawdown_start} → {dd.max_drawdown_trough}). "
        f"Current drawdown from 1-year high: {dd.current_drawdown:.1%}. "
        f"Worst 3-month return: {dd.worst_3m:.1%}; worst 6-month: {dd.worst_6m:.1%}. "
        f"Longest stretch below a prior peak: {dd.max_drawdown_duration_days} trading days."
    )

    kelly_txt = (
        f"Daily win rate: {kelly.win_rate:.1%}. Avg win: {kelly.avg_win:+.2%}; "
        f"avg loss: {kelly.avg_loss:+.2%}. {kelly.recommendation}"
    )

    return {
        "overview": overview,
        "stress_tests": stress_txt,
        "macro_correlations": macro_txt,
        "tail_risk": tail_txt,
        "drawdown": dd_txt,
        "kelly": kelly_txt,
    }


# --- Serialization --------------------------------------------------------

def to_dict(result: RiskFrameworkResult) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "n_observations": result.n_observations,
        "beta_vs_spy": result.beta_vs_spy,
        "stress_scenarios": [asdict(s) for s in result.stress_scenarios],
        "macro_correlations": [asdict(m) for m in result.macro_correlations],
        "drawdown": asdict(result.drawdown) if result.drawdown else None,
        "tail_risk": asdict(result.tail_risk) if result.tail_risk else None,
        "kelly": asdict(result.kelly) if result.kelly else None,
        "overall_risk_score": result.overall_risk_score,
        "overall_risk_label": result.overall_risk_label,
        "explanations": result.explanations,
        "error": result.error,
    }
