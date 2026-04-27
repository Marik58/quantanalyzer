"""Advanced statistical and probabilistic analysis.

Layered on top of the legacy distribution.py — this module adds:
  * Student-t distribution fit for fat-tail modelling
  * CVaR / Expected Shortfall at 95% and 99%
  * Downside-aware ratios: Sortino, Calmar, Omega
  * Empirical copula vs SPY with lower/upper tail dependence

Every metric has a plain-English explanation so a PM can read the output
without knowing what a Student-t degree-of-freedom is.

All functions are pure; no I/O, no network. Works on a price Series.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

TRADING_DAYS = 252


@dataclass
class StudentTFit:
    df: float            # degrees of freedom — lower = fatter tails
    loc: float           # location parameter
    scale: float         # scale parameter
    is_fat_tailed: bool  # True when df < 10
    tail_severity: str   # "normal-like" | "moderate" | "fat" | "extreme"


@dataclass
class DownsideMetrics:
    cvar_95: float         # Expected Shortfall at 95% (mean of worst 5% daily)
    cvar_99: float         # Expected Shortfall at 99%
    sortino_annual: float  # annualized downside-adjusted Sharpe
    calmar: float          # annualized return / max drawdown
    omega_ratio: float     # prob-weighted gains / losses above 0 threshold


@dataclass
class CopulaTailDependence:
    pearson: float         # linear correlation
    kendall_tau: float     # rank correlation (robust to non-linearity)
    lower_tail_dep: float  # prob of joint extreme losses (stock, SPY)
    upper_tail_dep: float  # prob of joint extreme gains
    overlap_days: int


@dataclass
class AdvancedStats:
    tfit: StudentTFit
    downside: DownsideMetrics
    copula: CopulaTailDependence | None
    explanations: dict[str, str]


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift()).dropna()


def _classify_tail(df: float) -> str:
    if df < 3:
        return "extreme"
    if df < 6:
        return "fat"
    if df < 10:
        return "moderate"
    return "normal-like"


def _fit_student_t(rets: pd.Series) -> StudentTFit:
    # scipy.stats.t.fit returns (df, loc, scale)
    df, loc, scale = stats.t.fit(rets.values)
    # df can be wild if the fit is degenerate — clip display-side downstream
    df = max(1.5, float(df))
    return StudentTFit(
        df=df, loc=float(loc), scale=float(scale),
        is_fat_tailed=df < 10.0,
        tail_severity=_classify_tail(df),
    )


def _downside_metrics(rets: pd.Series) -> DownsideMetrics:
    # CVaR / Expected Shortfall
    q95 = np.percentile(rets, 5)
    q99 = np.percentile(rets, 1)
    tail95 = rets[rets <= q95]
    tail99 = rets[rets <= q99]
    cvar95 = float(tail95.mean()) if len(tail95) else float("nan")
    cvar99 = float(tail99.mean()) if len(tail99) else float("nan")

    # Sortino — annualized, downside deviation in denominator
    downside = rets[rets < 0]
    dd_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    mu = float(rets.mean())
    sortino = (mu / dd_std) * np.sqrt(TRADING_DAYS) if dd_std > 0 else 0.0

    # Calmar — annualized return / abs(max drawdown)
    cum = np.exp(rets.cumsum())
    total_return = float(cum.iloc[-1]) - 1.0
    n_years = len(rets) / TRADING_DAYS
    ann_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0
    run_max = cum.cummax()
    dd = float((cum / run_max - 1).min())
    calmar = float(ann_return / abs(dd)) if dd < 0 else float("nan")

    # Omega ratio at threshold = 0
    gains = float(rets[rets > 0].sum())
    losses = float(-rets[rets < 0].sum())
    omega = (gains / losses) if losses > 0 else float("nan")

    return DownsideMetrics(
        cvar_95=cvar95, cvar_99=cvar99,
        sortino_annual=float(sortino),
        calmar=calmar, omega_ratio=omega,
    )


def _empirical_tail_dep(u: np.ndarray, v: np.ndarray, q: float) -> float:
    """Empirical tail-dependence estimator.

    For q < 0.5  -> lower tail  P(U <= q, V <= q) / q
    For q > 0.5  -> upper tail  P(U >= q, V >= q) / (1 - q)
    Output in [0, 1]: 0 = no tail dependence, 1 = always move together in the tail.
    """
    if q < 0.5:
        if q <= 0:
            return float("nan")
        return float(((u <= q) & (v <= q)).mean() / q)
    if q >= 1:
        return float("nan")
    return float(((u >= q) & (v >= q)).mean() / (1 - q))


def _copula(stock_rets: pd.Series, bench_rets: pd.Series) -> CopulaTailDependence | None:
    joined = pd.concat(
        [stock_rets.rename("s"), bench_rets.rename("b")],
        axis=1, join="inner",
    ).dropna()
    if len(joined) < 50:
        return None
    s = joined["s"].to_numpy()
    b = joined["b"].to_numpy()
    # Rank-transform to uniform margins — this is what makes it a copula
    n = len(joined)
    u = (pd.Series(s).rank().to_numpy() - 0.5) / n
    v = (pd.Series(b).rank().to_numpy() - 0.5) / n
    pearson = float(np.corrcoef(s, b)[0, 1])
    tau = float(stats.kendalltau(s, b).statistic)
    lower = _empirical_tail_dep(u, v, 0.05)
    upper = _empirical_tail_dep(u, v, 0.95)
    return CopulaTailDependence(
        pearson=pearson, kendall_tau=tau,
        lower_tail_dep=float(lower), upper_tail_dep=float(upper),
        overlap_days=int(n),
    )


def _explain(tfit: StudentTFit, d: DownsideMetrics,
             cop: CopulaTailDependence | None) -> dict[str, str]:
    out: dict[str, str] = {}

    # Student-t — the central "are the tails fat?" question
    if tfit.tail_severity == "extreme":
        out["student_t"] = (
            f"Returns fit a Student-t with {tfit.df:.1f} degrees of freedom — extreme "
            "fat tails. Outsized moves happen far more often than a normal distribution "
            "predicts. Any risk model that assumes normality (including most textbook VaR) "
            "will badly understate tail risk here."
        )
    elif tfit.tail_severity == "fat":
        out["student_t"] = (
            f"Student-t fit with df = {tfit.df:.1f} — genuinely fat tails. Expect outsized "
            "moves several times a year. Use CVaR, not vanilla VaR, for position sizing."
        )
    elif tfit.tail_severity == "moderate":
        out["student_t"] = (
            f"Student-t df = {tfit.df:.1f} — moderately fat tails. Tail risk is elevated "
            "vs. a normal assumption, but not pathological."
        )
    else:
        out["student_t"] = (
            f"Student-t df = {tfit.df:.1f} — tails look close to normal. Standard risk "
            "measures are reasonably trustworthy for this name."
        )

    # CVaR / ES — what actually happens on bad days
    out["cvar"] = (
        f"Expected Shortfall at 95%: on the worst 5% of days, the average daily loss is "
        f"{d.cvar_95:.2%}. At 99% (the worst 1% of days), the average loss is "
        f"{d.cvar_99:.2%}. Unlike VaR (which only tells you the threshold), CVaR tells "
        "you the average pain when you're already in the tail — the right number for "
        "sizing positions against a bad week."
    )

    # Sortino
    if d.sortino_annual > 2:
        out["sortino"] = (
            f"Sortino ratio {d.sortino_annual:.2f}: excellent. Returns are strongly "
            "positive relative to downside volatility — upside is not being paid for "
            "with painful drawdowns."
        )
    elif d.sortino_annual > 1:
        out["sortino"] = (
            f"Sortino ratio {d.sortino_annual:.2f}: solid. Above 1 means downside-adjusted "
            "returns are respectable."
        )
    elif d.sortino_annual > 0:
        out["sortino"] = (
            f"Sortino ratio {d.sortino_annual:.2f}: modest. Positive but the stock is not "
            "paying much for the downside risk it carries."
        )
    else:
        out["sortino"] = (
            f"Sortino ratio {d.sortino_annual:.2f}: negative. Recent downside exceeds "
            "upside — the stock has been paying you to hold downside without reward."
        )

    # Calmar
    if np.isnan(d.calmar):
        out["calmar"] = "Calmar ratio is undefined (no drawdown in the sample window)."
    elif d.calmar > 1:
        out["calmar"] = (
            f"Calmar {d.calmar:.2f}: annualized return exceeds the max drawdown — "
            "the stock compensates you more than the worst peak-to-trough hit."
        )
    elif d.calmar > 0:
        out["calmar"] = (
            f"Calmar {d.calmar:.2f}: positive but below 1 — drawdowns have eaten most "
            "of the annual return."
        )
    else:
        out["calmar"] = (
            f"Calmar {d.calmar:.2f}: negative annualized return combined with a drawdown "
            "— no reward for the risk."
        )

    # Omega
    if np.isnan(d.omega_ratio):
        out["omega"] = "Omega ratio is undefined (no negative return days in sample)."
    elif d.omega_ratio > 1.5:
        out["omega"] = (
            f"Omega {d.omega_ratio:.2f}: gains clearly dominate losses on a probability-"
            "weighted basis. Positive return profile."
        )
    elif d.omega_ratio > 1:
        out["omega"] = (
            f"Omega {d.omega_ratio:.2f}: slight edge to gains over losses — modestly "
            "positive asymmetry."
        )
    else:
        out["omega"] = (
            f"Omega {d.omega_ratio:.2f}: losses outweigh gains on a probability-weighted "
            "basis. The return distribution is tilted against you."
        )

    # Copula — tail dependence vs SPY
    if cop is None:
        out["copula"] = "Copula vs SPY could not be computed (insufficient overlapping history)."
    else:
        linear = f"Pearson {cop.pearson:+.2f}, Kendall τ {cop.kendall_tau:+.2f}"
        if cop.lower_tail_dep > 0.5:
            crash = (
                f"Lower-tail dependence is {cop.lower_tail_dep:.0%} — when SPY crashes, "
                "this stock crashes with it almost every time. Diversification benefit "
                "disappears precisely when you need it."
            )
        elif cop.lower_tail_dep > 0.25:
            crash = (
                f"Lower-tail dependence is {cop.lower_tail_dep:.0%} — moderate crash "
                "correlation to the market. Some diversification in a sell-off, but not much."
            )
        else:
            crash = (
                f"Lower-tail dependence is {cop.lower_tail_dep:.0%} — low crash correlation. "
                "This name has historically held up better than the market in sell-offs."
            )
        if cop.upper_tail_dep > 0.5:
            rally = (
                f" Upper-tail dependence {cop.upper_tail_dep:.0%} — also rallies hard "
                "when SPY rallies, so it's a high-beta name on the way up."
            )
        else:
            rally = (
                f" Upper-tail dependence {cop.upper_tail_dep:.0%} — less tied to the "
                "market on rallies than on crashes (asymmetric beta)."
            ) if cop.lower_tail_dep > cop.upper_tail_dep + 0.1 else (
                f" Upper-tail dependence {cop.upper_tail_dep:.0%}."
            )
        out["copula"] = f"{linear}. {crash}{rally}"

    return out


def compute(
    close: pd.Series,
    benchmark_close: pd.Series | None = None,
    lookback_days: int = 504,
) -> AdvancedStats:
    """Main entrypoint.

    Args:
        close: price Series for the target stock.
        benchmark_close: price Series for the benchmark (SPY); optional.
        lookback_days: trailing window in trading days. 504 ≈ 2 years.
    """
    rets = _log_returns(close)
    if len(rets) < 30:
        raise ValueError("Need at least 30 return observations for advanced stats.")
    sample = rets.iloc[-min(len(rets), lookback_days):]

    tfit = _fit_student_t(sample)
    down = _downside_metrics(sample)

    cop = None
    if benchmark_close is not None:
        bench_rets = _log_returns(benchmark_close)
        if len(bench_rets) >= 30:
            bench_sample = bench_rets.iloc[-min(len(bench_rets), lookback_days):]
            cop = _copula(sample, bench_sample)

    return AdvancedStats(
        tfit=tfit, downside=down, copula=cop,
        explanations=_explain(tfit, down, cop),
    )


def to_dict(s: AdvancedStats) -> dict[str, Any]:
    """JSON-safe dict for the API layer."""
    def clean(d: dict) -> dict:
        return {k: (None if isinstance(v, float) and (np.isnan(v) or np.isinf(v)) else v)
                for k, v in d.items()}
    return {
        "student_t": clean(asdict(s.tfit)),
        "downside": clean(asdict(s.downside)),
        "copula": clean(asdict(s.copula)) if s.copula else None,
        "explanations": s.explanations,
    }
