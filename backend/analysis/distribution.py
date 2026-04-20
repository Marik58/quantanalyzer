"""Statistical distribution analysis of daily log returns."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class DistributionStats:
    mean_daily: float
    stdev_daily: float
    skew: float
    kurtosis: float
    var_95: float          # 95% Value at Risk (daily, negative number)
    var_99: float
    sharpe_annual: float
    last_return_z: float   # how many stdevs the latest day moved
    is_normal_p: float     # Shapiro-Wilk p-value vs normal


def compute(close: pd.Series) -> DistributionStats:
    rets = np.log(close / close.shift()).dropna()
    sample = rets.iloc[-min(len(rets), 504):]  # ~2y of trading days
    mu = float(sample.mean())
    sd = float(sample.std(ddof=1))
    sk = float(stats.skew(sample))
    kt = float(stats.kurtosis(sample))
    var95 = float(np.percentile(sample, 5))
    var99 = float(np.percentile(sample, 1))
    sharpe = float((mu / sd) * np.sqrt(252)) if sd > 0 else 0.0
    last_z = float((sample.iloc[-1] - mu) / sd) if sd > 0 else 0.0
    # Shapiro is slow on big samples; use a 250-day window
    try:
        _, p = stats.shapiro(sample.iloc[-250:])
    except Exception:
        p = float("nan")
    return DistributionStats(
        mean_daily=mu, stdev_daily=sd, skew=sk, kurtosis=kt,
        var_95=var95, var_99=var99, sharpe_annual=sharpe,
        last_return_z=last_z, is_normal_p=float(p),
    )
