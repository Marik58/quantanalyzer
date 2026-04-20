"""Risk rating: low / medium / high based on annualized vol and recent drawdown."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.analysis.indicators import annualized_volatility, max_drawdown


@dataclass
class RiskRating:
    rating: str            # "low" | "medium" | "high"
    annualized_vol: float
    max_drawdown_1y: float
    notes: str


def rate(close: pd.Series) -> RiskRating:
    vol_series = annualized_volatility(close, 30).dropna()
    vol = float(vol_series.iloc[-1]) if len(vol_series) else 0.0
    dd = max_drawdown(close, 252)

    # Vol thresholds (annualized): equities baseline ~15-20%
    if vol < 0.25:
        base = "low"
    elif vol < 0.45:
        base = "medium"
    else:
        base = "high"

    # Bump up one tier on severe drawdown
    if dd < -0.35 and base == "low":
        base = "medium"
    elif dd < -0.50 and base == "medium":
        base = "high"

    notes = f"30-day annualized volatility is {vol:.0%}; 1-year max drawdown was {dd:.0%}."
    return RiskRating(rating=base, annualized_vol=vol, max_drawdown_1y=dd, notes=notes)
