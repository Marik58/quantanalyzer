"""Fama-French factor adjustment — is the edge real, or just momentum?

A strategy can look skilful simply by loading on a factor everyone already
knows about. Buying recent winners, for example, is the momentum factor, not a
discovery. The test is a regression:

    strategy return = alpha + b1*Market + b2*Size + b3*Value
                            + b4*Profitability + b5*Investment + b6*Momentum

`alpha` is what is left after the known factors are paid their due. If alpha is
indistinguishable from zero, the strategy is a repackaging of known factors,
however good its raw return looked.

Data comes free from Kenneth French's library at Dartmouth (built on CRSP), so
this is one of the few genuinely research-grade inputs available at no cost.
Files are cached locally for 30 days.

Note: French publishes with roughly a two-month lag, so the most recent
rebalances usually cannot be adjusted and are dropped from the regression —
the returned `n_periods` says how many actually matched.
"""
from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF5_ZIP = BASE + "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_ZIP = BASE + "F-F_Momentum_Factor_daily_CSV.zip"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "factors"
REFRESH_DAYS = 30

FACTOR_NAMES = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
_CACHE: pd.DataFrame | None = None


@dataclass
class FactorFit:
    """Result of regressing a strategy's returns on the factor set."""
    n_periods: int
    alpha_per_period: float
    alpha_annualized: float
    alpha_t: float
    alpha_p: float
    r_squared: float
    betas: dict[str, float] = field(default_factory=dict)
    beta_t: dict[str, float] = field(default_factory=dict)
    factors_through: str | None = None
    verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_periods": self.n_periods,
            "alpha_per_period": self.alpha_per_period,
            "alpha_annualized": self.alpha_annualized,
            "alpha_t": self.alpha_t,
            "alpha_p": self.alpha_p,
            "r_squared": self.r_squared,
            "betas": self.betas,
            "beta_t": self.beta_t,
            "factors_through": self.factors_through,
            "verdict": self.verdict,
        }


def _download(url: str) -> str | None:
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(url, impersonate="chrome", timeout=60)
        if r.status_code != 200:
            log.warning("French library returned HTTP %s for %s", r.status_code, url)
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        return z.read(z.namelist()[0]).decode("latin-1")
    except Exception as exc:
        log.warning("factor download failed (%s): %s", url, exc)
        return None


def _cached_text(url: str, name: str) -> str | None:
    path = CACHE_DIR / name
    if path.exists():
        age = (datetime.now().timestamp() - path.stat().st_mtime) / 86400
        if age < REFRESH_DAYS:
            return path.read_text(encoding="utf-8")
    text = _download(url)
    if text is None:
        return path.read_text(encoding="utf-8") if path.exists() else None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _parse(text: str) -> pd.DataFrame:
    """French files carry a prose header, then YYYYMMDD rows in percent."""
    rows: list[list[str]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if header is None:
            if len(parts) > 1 and parts[0] == "" and any(p for p in parts[1:]):
                header = [p for p in parts[1:] if p]
            continue
        if not parts or not parts[0].isdigit() or len(parts[0]) != 8:
            continue                       # blank line, or the annual section below
        rows.append(parts[: len(header) + 1])
    if header is None or not rows:
        raise ValueError("could not parse a factor file")
    df = pd.DataFrame(rows, columns=["date"] + header)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in header:
        df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0   # percent -> decimal
    return df.set_index("date").sort_index()


def load_factors(force_refresh: bool = False) -> pd.DataFrame:
    """Daily factor returns as decimals, indexed by date."""
    global _CACHE
    if _CACHE is not None and not force_refresh:
        return _CACHE
    ff5_txt = _cached_text(FF5_ZIP, "ff5_daily.csv")
    mom_txt = _cached_text(MOM_ZIP, "mom_daily.csv")
    if ff5_txt is None or mom_txt is None:
        raise RuntimeError("Fama-French factor data unavailable (offline and no local copy)")
    ff5, mom = _parse(ff5_txt), _parse(mom_txt)
    mom = mom.rename(columns={mom.columns[0]: "Mom"})
    out = ff5.join(mom[["Mom"]], how="inner").dropna()
    _CACHE = out
    return out


def window_returns(start_dates: Iterable[str | pd.Timestamp], fwd_days: int) -> pd.DataFrame:
    """Compound each factor over the `fwd_days` trading days after each start date.

    This matches how the backtest measures its own forward return, so the
    regression compares like with like.
    """
    f = load_factors()
    idx = f.index
    rows: list[dict[str, Any]] = []
    for d in start_dates:
        ts = pd.Timestamp(d)
        pos = idx.searchsorted(ts, side="right")       # strictly after the scoring date
        if pos + fwd_days > len(idx):
            continue                                    # factors not published this far yet
        chunk = f.iloc[pos: pos + fwd_days]
        if len(chunk) < fwd_days:
            continue
        row: dict[str, Any] = {"date": ts.strftime("%Y-%m-%d")}
        for c in FACTOR_NAMES:
            row[c] = float((1.0 + chunk[c]).prod() - 1.0)
        rows.append(row)
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def _ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Plain OLS with t-statistics. Returns (coefficients, t-stats, R^2)."""
    n, k = X.shape
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, n - k)
    sigma2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 1e-300))
    tvals = beta / se
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else 0.0
    return beta, tvals, r2


def fit(strategy_returns: dict[str, float] | pd.Series, fwd_days: int) -> FactorFit | None:
    """Regress per-rebalance strategy returns on the factor set.

    strategy_returns: {scoring date -> return over the following fwd_days}.
    """
    from scipy import stats as _st

    s = pd.Series(strategy_returns, dtype=float).dropna()
    if len(s) < 12:
        return None
    s.index = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in s.index]
    fac = window_returns(s.index, fwd_days)
    if fac.empty:
        return None
    joined = fac.join(s.rename("y"), how="inner").dropna()
    if len(joined) < 12:
        return None

    y = joined["y"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(joined))] + [joined[c].to_numpy(dtype=float)
                                                  for c in FACTOR_NAMES])
    beta, tvals, r2 = _ols(y, X)
    dof = max(1, len(joined) - X.shape[1])
    alpha, alpha_t = float(beta[0]), float(tvals[0])
    # A numerically perfect fit (e.g. the strategy IS a factor) leaves residuals
    # at floating-point noise, which makes the t-stat meaningless. Treat an
    # economically zero alpha as zero rather than reporting a huge t.
    if abs(alpha) < 1e-8:
        alpha, alpha_t = 0.0, 0.0
    alpha_p = float(2.0 * _st.t.sf(abs(alpha_t), df=dof))
    periods_per_year = 252.0 / fwd_days

    betas = {name: round(float(b), 4) for name, b in zip(FACTOR_NAMES, beta[1:])}
    beta_t = {name: round(float(t), 2) for name, t in zip(FACTOR_NAMES, tvals[1:])}

    if abs(alpha_t) < 2.0:
        top = max(betas, key=lambda k: abs(betas[k]))
        verdict = (
            f"Alpha is not distinguishable from zero (t = {alpha_t:+.2f}). After paying the known "
            f"factors their due, nothing is left over — the strategy's returns are explained by "
            f"factor exposure, mostly {top} (beta {betas[top]:+.2f}). This is the outcome that "
            f"separates a discovery from a repackaging.")
    elif alpha > 0:
        verdict = (
            f"Alpha is {alpha * periods_per_year:+.1%} a year and statistically significant "
            f"(t = {alpha_t:+.2f}) after controlling for market, size, value, profitability, "
            f"investment and momentum. Worth investigating further — check other samples, "
            f"windows and costs before believing it.")
    else:
        verdict = (f"Alpha is significantly NEGATIVE ({alpha * periods_per_year:+.1%} a year, "
                   f"t = {alpha_t:+.2f}): the strategy underperforms what its factor exposure alone "
                   f"would deliver.")

    f_all = load_factors()
    return FactorFit(
        n_periods=len(joined),
        alpha_per_period=round(alpha, 6),
        alpha_annualized=round(alpha * periods_per_year, 5),
        alpha_t=round(alpha_t, 2),
        alpha_p=round(alpha_p, 4),
        r_squared=round(r2, 4),
        betas=betas, beta_t=beta_t,
        factors_through=f_all.index[-1].strftime("%Y-%m-%d"),
        verdict=verdict,
    )


def coverage() -> dict[str, Any]:
    f = load_factors()
    return {"rows": len(f), "start": f.index[0].strftime("%Y-%m-%d"),
            "end": f.index[-1].strftime("%Y-%m-%d"), "factors": FACTOR_NAMES}
