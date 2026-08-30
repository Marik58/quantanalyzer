"""Historical what-if: growth of a fixed investment vs. SPY.

"If I had put $10,000 into this ticker N years ago, what would I have now,
what would the ride have felt like, and would I have beaten the market?"

Pure reuse of data.load (10y history) — no new data dependencies. Follows the
house convention: compute() -> dataclass -> to_dict() -> endpoint.

Educational by design: every horizon pairs the ending value with the max
drawdown en route, because the drawdown is the number that decides whether a
real person would have held on long enough to collect the CAGR.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis import data as data_mod

TRADING_DAYS_PER_YEAR = 252

# (label, years) — longest horizon that fits the data also drives the chart
HORIZONS: list[tuple[str, int]] = [("1y", 1), ("3y", 3), ("5y", 5), ("10y", 10)]


@dataclass
class HorizonStats:
    label: str                     # "1y", "3y", ...
    start_date: str
    end_date: str
    years: float                   # actual span in years (may be < nominal)
    final_value: float             # amount grown in the ticker
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float        # most negative peak-to-trough, e.g. -35.2
    ann_vol_pct: float
    spy_final_value: float | None  # same amount in SPY over the same window
    spy_cagr_pct: float | None
    vs_spy_final: float | None     # final_value - spy_final_value (dollars)


@dataclass
class YearRow:
    year: int
    ticker_return_pct: float
    spy_return_pct: float | None


@dataclass
class WhatIfResult:
    ticker: str
    amount: float
    horizons: list[HorizonStats] = field(default_factory=list)
    calendar_years: list[YearRow] = field(default_factory=list)
    series: dict[str, list] = field(default_factory=dict)   # dates, ticker_value, spy_value
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _max_drawdown(values: pd.Series) -> float:
    """Most negative peak-to-trough decline, as a percentage (e.g. -35.2)."""
    running_peak = values.cummax()
    dd = values / running_peak - 1.0
    return float(dd.min() * 100.0)


def _horizon_stats(label: str, close: pd.Series, spy: pd.Series | None,
                   amount: float) -> HorizonStats:
    start, end = close.index[0], close.index[-1]
    years = max((end - start).days / 365.25, 1 / 365.25)
    growth = close / close.iloc[0]
    final_value = float(amount * growth.iloc[-1])
    total_ret = float((growth.iloc[-1] - 1.0) * 100.0)
    cagr = float(((growth.iloc[-1]) ** (1 / years) - 1.0) * 100.0)
    daily = close.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)

    spy_final = spy_cagr = vs_spy = None
    if spy is not None and len(spy) >= 2:
        spy_growth = float(spy.iloc[-1] / spy.iloc[0])
        spy_final = float(amount * spy_growth)
        spy_cagr = float((spy_growth ** (1 / years) - 1.0) * 100.0)
        vs_spy = float(final_value - spy_final)

    return HorizonStats(
        label=label,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        years=round(years, 2),
        final_value=round(final_value, 2),
        total_return_pct=round(total_ret, 1),
        cagr_pct=round(cagr, 1),
        max_drawdown_pct=round(_max_drawdown(close), 1),
        ann_vol_pct=round(ann_vol, 1),
        spy_final_value=round(spy_final, 2) if spy_final is not None else None,
        spy_cagr_pct=round(spy_cagr, 1) if spy_cagr is not None else None,
        vs_spy_final=round(vs_spy, 2) if vs_spy is not None else None,
    )


def _calendar_years(close: pd.Series, spy: pd.Series | None) -> list[YearRow]:
    """Full-calendar-year returns (first partial year is skipped)."""
    rows: list[YearRow] = []
    spy_last_by_year: dict[int, float] = {}
    if spy is not None:
        for y, grp in spy.groupby(spy.index.year):
            spy_last_by_year[int(y)] = float(grp.iloc[-1])

    prev_close: float | None = None
    prev_spy: float | None = None
    for y, grp in close.groupby(close.index.year):
        y = int(y)
        last = float(grp.iloc[-1])
        spy_last = spy_last_by_year.get(y)
        if prev_close is not None:
            t_ret = (last / prev_close - 1.0) * 100.0
            s_ret = ((spy_last / prev_spy - 1.0) * 100.0
                     if spy_last is not None and prev_spy else None)
            rows.append(YearRow(
                year=y,
                ticker_return_pct=round(t_ret, 1),
                spy_return_pct=round(s_ret, 1) if s_ret is not None else None,
            ))
        prev_close = last
        prev_spy = spy_last if spy_last is not None else prev_spy
    return rows


def _explain(res: WhatIfResult) -> dict[str, str]:
    if not res.horizons:
        return {"overview": "Not enough history to run a what-if."}
    longest = res.horizons[-1]
    ex: dict[str, str] = {}
    ex["overview"] = (
        f"${res.amount:,.0f} invested in {res.ticker} on {longest.start_date} "
        f"would be ${longest.final_value:,.0f} on {longest.end_date} "
        f"({longest.total_return_pct:+.0f}% total, {longest.cagr_pct:+.1f}%/yr)."
    )
    if longest.spy_final_value is not None:
        beat = longest.final_value - longest.spy_final_value
        word = "MORE" if beat >= 0 else "LESS"
        ex["vs_market"] = (
            f"The same money in SPY (the S&P 500) would be "
            f"${longest.spy_final_value:,.0f} — {res.ticker} left you "
            f"${abs(beat):,.0f} {word} than the index. Beating the index is the "
            f"bar: anyone can buy SPY in one click, so a single stock has to be "
            f"judged against that default, not against zero."
        )
    ex["the_ride"] = (
        f"En route, the position fell {longest.max_drawdown_pct:.0f}% from its "
        f"peak at the worst point, with {longest.ann_vol_pct:.0f}% annualized "
        f"volatility. The drawdown is the number that matters emotionally: the "
        f"ending value only belongs to investors who did not sell at the bottom."
    )
    ex["caveats"] = (
        "Past growth is not a forecast. This uses dividend-adjusted prices, "
        "ignores taxes and trading costs, and — most importantly — you are "
        "looking at a stock you already know survived and prospered. In real "
        "time, nobody knows which ticker gets this chart (survivorship bias)."
    )
    return ex


def compute(ticker: str, amount: float = 10_000.0) -> WhatIfResult:
    ticker = ticker.upper().strip()
    res = WhatIfResult(ticker=ticker, amount=float(amount))

    td = data_mod.load(ticker, period="10y")
    if td is None or td.history is None or td.history.empty:
        res.error = f"No price history for {ticker}."
        res.explanations = {"overview": res.error}
        return res
    close = td.history["Close"].dropna()
    if len(close) < TRADING_DAYS_PER_YEAR:
        res.error = "Less than one year of history — what-if not meaningful."
        res.explanations = {"overview": res.error}
        return res

    spy_td = data_mod.load("SPY", period="10y")
    spy = spy_td.history["Close"].dropna() if spy_td is not None else None

    for label, yrs in HORIZONS:
        n = yrs * TRADING_DAYS_PER_YEAR
        if len(close) < n:
            continue
        window = close.iloc[-n:]
        spy_window = None
        if spy is not None:
            spy_window = spy[spy.index >= window.index[0]]
            if len(spy_window) < 2:
                spy_window = None
        res.horizons.append(_horizon_stats(label, window, spy_window, res.amount))
    # Fall back to whatever we have if no nominal horizon fit
    if not res.horizons:
        spy_window = spy[spy.index >= close.index[0]] if spy is not None else None
        res.horizons.append(_horizon_stats("max", close, spy_window, res.amount))

    # Chart series over the longest computed horizon (thin to ~2 points/week)
    longest_label = res.horizons[-1].label
    n = (dict(HORIZONS).get(longest_label, 0) * TRADING_DAYS_PER_YEAR) or len(close)
    window = close.iloc[-n:]
    growth = window / window.iloc[0] * res.amount
    step = max(1, len(growth) // 520)
    thin = growth.iloc[::step]
    series: dict[str, list] = {
        "dates": [d.strftime("%Y-%m-%d") for d in thin.index],
        "ticker_value": [round(float(v), 2) for v in thin],
        "spy_value": [],
    }
    if spy is not None:
        spy_win = spy[spy.index >= window.index[0]]
        if len(spy_win) >= 2:
            spy_growth = spy_win / spy_win.iloc[0] * res.amount
            spy_aligned = spy_growth.reindex(thin.index, method="ffill")
            series["spy_value"] = [None if pd.isna(v) else round(float(v), 2)
                                   for v in spy_aligned]
    res.series = series

    res.calendar_years = _calendar_years(close, spy)
    res.explanations = _explain(res)
    return res
