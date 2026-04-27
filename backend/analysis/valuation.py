"""DCF valuation module.

Builds a 5-year discounted cash flow model from yfinance financials, with three
scenarios (Bear / Base / Bull), a probability-weighted intrinsic value, and a
3x3 sensitivity matrix (discount rate × terminal growth).

Method summary:
  1. Pull 4-5 years of Free Cash Flow history. If the "Free Cash Flow" row is
     missing, fall back to Operating Cash Flow + Capital Expenditure (CapEx is
     stored negative on yfinance, so we add it directly).
  2. Historical FCF CAGR → base growth assumption (clamped to [-5%, +15%]).
  3. Discount rate = CAPM: rf + β × equity risk premium.
     (Using static rf=4.5%, ERP=5.5% — configurable at top of file.)
  4. Forecast 5 years with linear fade from initial to terminal growth.
  5. Terminal value = Gordon Growth: FCF_6 / (r - g). Clamped when r ≤ g.
  6. EV = Σ PV(FCF) + PV(TV); Equity = EV + Cash − Debt; per-share = Equity/Shares.

Design notes:
  - If FCF history is negative or erratic, the module reports method=
    "unreliable" and still emits a best-effort number with a loud caveat.
  - The three scenarios are not simulations — they are hand-parameterized
    sensitivity cases so a student analyst can read exactly how each assumption
    moved the output.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.analysis import data as data_mod
from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_SESSION = curl_requests.Session(impersonate="chrome")

# CAPM defaults. Review quarterly or sub in a dynamic fetch.
RISK_FREE_RATE = 0.045       # 10-year Treasury yield
EQUITY_RISK_PREMIUM = 0.055  # historical US long-run equity premium
FORECAST_YEARS = 5
SCENARIO_WEIGHTS = {"Bear": 0.25, "Base": 0.50, "Bull": 0.25}


# --- Dataclasses ----------------------------------------------------------

@dataclass
class FCFHistory:
    years: list[str]
    fcf_values: list[float]
    latest_fcf: float
    avg_fcf: float
    cagr: float | None                   # None if years have sign changes
    fcf_method: str                      # "free_cash_flow" | "ocf_minus_capex"
    reliability: str                     # "good" | "volatile" | "negative" | "sparse"


@dataclass
class DCFAssumptions:
    initial_growth: float
    terminal_growth: float
    discount_rate: float
    forecast_years: int
    shares_outstanding: float
    cash: float
    debt: float


@dataclass
class ForecastRow:
    year: int                            # 1..N
    growth_rate: float
    fcf: float
    present_value: float


@dataclass
class DCFScenario:
    name: str                            # Bear | Base | Bull
    assumptions: DCFAssumptions
    forecast: list[ForecastRow]
    terminal_value: float
    terminal_pv: float
    enterprise_value: float
    equity_value: float
    intrinsic_per_share: float
    current_price: float
    upside_pct: float                    # (intrinsic - current) / current
    margin_of_safety: float              # (intrinsic - current) / intrinsic


@dataclass
class SensitivityCell:
    discount_rate: float
    terminal_growth: float
    intrinsic_per_share: float
    upside_pct: float


@dataclass
class DCFValuation:
    ticker: str
    method: str                          # "dcf_fcf" | "unavailable"
    current_price: float
    history: FCFHistory | None
    base_beta: float | None
    base_discount_rate: float | None
    base_growth: float | None
    scenarios: list[DCFScenario]
    sensitivity: list[SensitivityCell]
    weighted_intrinsic: float | None
    weighted_upside_pct: float | None
    recommendation: str                  # Buy / Fairly valued / Overvalued / n/a
    explanations: dict[str, str] = field(default_factory=dict)
    error: str | None = None


# --- Fetch helpers --------------------------------------------------------

@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda t: f"dcf_financials:{t}")
def _fetch_financials(ticker: str) -> dict[str, Any]:
    try:
        t = yf.Ticker(ticker, session=_SESSION)
        return {
            "cashflow": t.cashflow,
            "balance_sheet": t.balance_sheet,
            "info": t.info or {},
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _row_by_names(df: pd.DataFrame | None, names: list[str]) -> pd.Series | None:
    """Find the first index row that matches any of `names` (case-insensitive)."""
    if df is None or df.empty:
        return None
    norm = {str(i).lower().strip(): i for i in df.index}
    for name in names:
        key = name.lower().strip()
        if key in norm:
            return df.loc[norm[key]]
    return None


def _extract_fcf_history(cashflow: pd.DataFrame | None) -> FCFHistory | None:
    if cashflow is None or cashflow.empty:
        return None

    fcf_row = _row_by_names(cashflow, ["Free Cash Flow", "FreeCashFlow"])
    method = "free_cash_flow"

    if fcf_row is None:
        ocf = _row_by_names(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex = _row_by_names(cashflow, ["Capital Expenditure", "Capital Expenditures"])
        if ocf is None or capex is None:
            return None
        # CapEx is reported as a negative number on yfinance → add directly
        fcf_row = ocf + capex
        method = "ocf_minus_capex"

    fcf_row = fcf_row.dropna()
    if len(fcf_row) < 2:
        return None

    # yfinance returns most-recent-first; we want chronological
    fcf_row = fcf_row.sort_index()
    years = [str(d.year) if hasattr(d, "year") else str(d) for d in fcf_row.index]
    vals = [float(v) for v in fcf_row.values]

    latest = vals[-1]
    avg = float(np.mean(vals))

    # CAGR only meaningful when first and last are both positive
    cagr: float | None = None
    if vals[0] > 0 and vals[-1] > 0 and len(vals) >= 2:
        years_span = len(vals) - 1
        cagr = float((vals[-1] / vals[0]) ** (1 / years_span) - 1)

    # Reliability classification
    pos_count = sum(1 for v in vals if v > 0)
    if pos_count < len(vals):
        reliability = "negative" if latest < 0 else "volatile"
    elif len(vals) < 3:
        reliability = "sparse"
    else:
        vol = float(np.std(vals) / abs(avg)) if avg != 0 else 1.0
        reliability = "volatile" if vol > 0.5 else "good"

    return FCFHistory(
        years=years, fcf_values=vals,
        latest_fcf=latest, avg_fcf=avg, cagr=cagr,
        fcf_method=method, reliability=reliability,
    )


def _extract_balance_sheet(bs: pd.DataFrame | None) -> tuple[float, float]:
    if bs is None or bs.empty:
        return 0.0, 0.0
    # Use the most-recent column
    col = bs.columns[0]
    cash_row = _row_by_names(bs, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash"])
    debt_row = _row_by_names(bs, ["Total Debt", "Long Term Debt"])
    cash = float(cash_row[col]) if cash_row is not None and pd.notna(cash_row[col]) else 0.0
    debt = float(debt_row[col]) if debt_row is not None and pd.notna(debt_row[col]) else 0.0
    return cash, debt


# --- DCF math -------------------------------------------------------------

def _fade_growth(year: int, years: int, initial: float, terminal: float) -> float:
    """Linear fade: year 1 = initial, year N = terminal."""
    if years <= 1:
        return terminal
    t = (year - 1) / (years - 1)
    return initial * (1.0 - t) + terminal * t


def _project(base_fcf: float, initial_growth: float, terminal_growth: float,
             discount_rate: float, years: int) -> tuple[list[ForecastRow], float, float]:
    """Return (rows, terminal_value, terminal_pv)."""
    rows: list[ForecastRow] = []
    current = base_fcf
    for yr in range(1, years + 1):
        g = _fade_growth(yr, years, initial_growth, terminal_growth)
        current = current * (1.0 + g)
        pv = current / (1.0 + discount_rate) ** yr
        rows.append(ForecastRow(year=yr, growth_rate=g, fcf=current, present_value=pv))

    last_fcf = rows[-1].fcf
    # Guard: Gordon is undefined when discount ≤ terminal growth
    r = discount_rate
    g = terminal_growth
    if r - g < 0.005:
        r = g + 0.005
    tv = last_fcf * (1.0 + g) / (r - g)
    tv_pv = tv / (1.0 + discount_rate) ** years
    return rows, tv, tv_pv


def _build_scenario(name: str, base_fcf: float, initial_growth: float,
                    terminal_growth: float, discount_rate: float,
                    forecast_years: int, shares: float, cash: float,
                    debt: float, current_price: float) -> DCFScenario:
    rows, tv, tv_pv = _project(base_fcf, initial_growth, terminal_growth,
                                discount_rate, forecast_years)
    ev = sum(r.present_value for r in rows) + tv_pv
    equity = ev + cash - debt
    per_share = equity / shares if shares > 0 else 0.0
    upside = (per_share - current_price) / current_price if current_price > 0 else 0.0
    mos = (per_share - current_price) / per_share if per_share > 0 else 0.0
    return DCFScenario(
        name=name,
        assumptions=DCFAssumptions(
            initial_growth=initial_growth, terminal_growth=terminal_growth,
            discount_rate=discount_rate, forecast_years=forecast_years,
            shares_outstanding=shares, cash=cash, debt=debt,
        ),
        forecast=rows,
        terminal_value=tv, terminal_pv=tv_pv,
        enterprise_value=ev, equity_value=equity,
        intrinsic_per_share=per_share,
        current_price=current_price,
        upside_pct=upside,
        margin_of_safety=mos,
    )


def _build_sensitivity(base_fcf: float, initial_growth: float,
                       base_discount: float, forecast_years: int,
                       shares: float, cash: float, debt: float,
                       current_price: float) -> list[SensitivityCell]:
    cells: list[SensitivityCell] = []
    discount_axis = [base_discount - 0.02, base_discount, base_discount + 0.02]
    terminal_axis = [0.015, 0.025, 0.035]
    for r in discount_axis:
        for g in terminal_axis:
            rows, _, tv_pv = _project(base_fcf, initial_growth, g, r, forecast_years)
            ev = sum(row.present_value for row in rows) + tv_pv
            equity = ev + cash - debt
            per_share = equity / shares if shares > 0 else 0.0
            up = (per_share - current_price) / current_price if current_price > 0 else 0.0
            cells.append(SensitivityCell(
                discount_rate=float(r), terminal_growth=float(g),
                intrinsic_per_share=float(per_share), upside_pct=float(up),
            ))
    return cells


# --- Explanations / recommendation ---------------------------------------

def _recommend(weighted_upside: float | None, base_reliability: str) -> str:
    if weighted_upside is None:
        return "n/a"
    if base_reliability in ("negative", "volatile"):
        return "DCF unreliable — cross-check with peers/relative value"
    if weighted_upside > 0.25:
        return "Undervalued"
    if weighted_upside > 0.10:
        return "Modestly undervalued"
    if weighted_upside > -0.10:
        return "Fairly valued"
    if weighted_upside > -0.25:
        return "Modestly overvalued"
    return "Overvalued"


def _explain(ticker: str, history: FCFHistory, base_growth: float,
             discount_rate: float, beta: float | None,
             scenarios: list[DCFScenario], weighted_intrinsic: float,
             weighted_upside: float, current_price: float,
             recommendation: str) -> dict[str, str]:
    scen_by_name = {s.name: s for s in scenarios}
    base = scen_by_name.get("Base")
    bear = scen_by_name.get("Bear")
    bull = scen_by_name.get("Bull")

    method_note = ("Free Cash Flow row pulled directly from yfinance."
                   if history.fcf_method == "free_cash_flow"
                   else "FCF derived from Operating Cash Flow + Capital Expenditure "
                        "(yfinance did not expose a Free Cash Flow row).")

    cagr_txt = (f"{history.cagr:+.1%} historical CAGR"
                if history.cagr is not None else "CAGR not meaningful (sign changes)")

    overview = (
        f"{ticker} DCF: 5-year free-cash-flow forecast discounted at "
        f"{discount_rate:.1%} (CAPM: β={beta:.2f} × {EQUITY_RISK_PREMIUM:.1%} "
        f"ERP + {RISK_FREE_RATE:.1%} rf). "
        f"Historical FCF: {cagr_txt}; used {base_growth:+.1%} as the base-case "
        f"year-1 growth rate, fading linearly to the terminal rate. {method_note}"
    )

    if base is not None:
        base_txt = (
            f"Base case intrinsic value: ${base.intrinsic_per_share:,.2f}/share "
            f"vs current ${current_price:,.2f} → upside {base.upside_pct:+.1%}, "
            f"margin of safety {base.margin_of_safety:+.1%}. "
            f"Enterprise value = ${base.enterprise_value/1e9:,.1f}B, "
            f"equity value = ${base.equity_value/1e9:,.1f}B."
        )
    else:
        base_txt = "Base case unavailable."

    if bear is not None and bull is not None:
        range_txt = (
            f"Scenario range: Bear ${bear.intrinsic_per_share:,.2f} "
            f"(upside {bear.upside_pct:+.1%}) to Bull ${bull.intrinsic_per_share:,.2f} "
            f"(upside {bull.upside_pct:+.1%}). The {bull.upside_pct - bear.upside_pct:.0%} "
            f"spread is a rough valuation confidence interval — narrow spreads "
            f"mean DCF is relatively insensitive here; wide spreads mean the "
            f"answer is dominated by assumptions."
        )
    else:
        range_txt = "Scenario range unavailable."

    weighted_txt = (
        f"Probability-weighted intrinsic (Bear 25% / Base 50% / Bull 25%): "
        f"${weighted_intrinsic:,.2f}/share → {weighted_upside:+.1%} expected upside. "
        f"Recommendation: {recommendation}."
    )

    caveats = (
        "DCF caveats for institutional use: "
        "(1) small changes in terminal growth swing the output dramatically — "
        "see the sensitivity matrix. "
        "(2) FCF reliability is flagged as '" + history.reliability + "' — "
        "if volatile or negative, treat the DCF as directional only and "
        "cross-reference with EV/EBITDA, P/E, and peer multiples. "
        "(3) This model uses static risk-free rate and equity risk premium; "
        "update if Treasury yields have moved materially."
    )

    return {
        "overview": overview,
        "base_case": base_txt,
        "scenario_range": range_txt,
        "weighted_result": weighted_txt,
        "caveats": caveats,
    }


# --- Main entrypoint ------------------------------------------------------

def compute(ticker: str) -> DCFValuation:
    ticker = ticker.upper().strip()
    td = data_mod.load(ticker)
    if td is None:
        return DCFValuation(
            ticker=ticker, method="unavailable", current_price=0.0,
            history=None, base_beta=None, base_discount_rate=None,
            base_growth=None, scenarios=[], sensitivity=[],
            weighted_intrinsic=None, weighted_upside_pct=None,
            recommendation="n/a",
            explanations={"overview": f"No price data for {ticker}."},
            error=f"No price history for {ticker}.",
        )

    current_price = td.last_price
    fin = _fetch_financials(ticker)
    if fin.get("error"):
        return DCFValuation(
            ticker=ticker, method="unavailable", current_price=current_price,
            history=None, base_beta=None, base_discount_rate=None,
            base_growth=None, scenarios=[], sensitivity=[],
            weighted_intrinsic=None, weighted_upside_pct=None,
            recommendation="n/a",
            explanations={"overview": f"Financials fetch failed: {fin['error']}"},
            error=fin["error"],
        )

    history = _extract_fcf_history(fin.get("cashflow"))
    if history is None:
        return DCFValuation(
            ticker=ticker, method="unavailable", current_price=current_price,
            history=None, base_beta=None, base_discount_rate=None,
            base_growth=None, scenarios=[], sensitivity=[],
            weighted_intrinsic=None, weighted_upside_pct=None,
            recommendation="n/a",
            explanations={"overview": (f"{ticker} does not expose enough Free "
                                        f"Cash Flow history on yfinance for a "
                                        f"DCF. Use peer multiples instead.")},
            error="Insufficient FCF history.",
        )

    info = fin.get("info", {})
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    try:
        shares = float(shares) if shares else 0.0
    except (TypeError, ValueError):
        shares = 0.0
    if shares <= 0:
        return DCFValuation(
            ticker=ticker, method="unavailable", current_price=current_price,
            history=history, base_beta=None, base_discount_rate=None,
            base_growth=None, scenarios=[], sensitivity=[],
            weighted_intrinsic=None, weighted_upside_pct=None,
            recommendation="n/a",
            explanations={"overview": "Shares outstanding unavailable — cannot "
                                       "convert equity value to per-share."},
            error="Missing sharesOutstanding.",
        )

    cash, debt = _extract_balance_sheet(fin.get("balance_sheet"))
    beta = info.get("beta")
    try:
        beta = float(beta) if beta is not None else 1.0
    except (TypeError, ValueError):
        beta = 1.0
    beta = float(np.clip(beta, 0.2, 3.0))  # reasonable guard

    discount_rate = RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM

    base_growth_raw = history.cagr if history.cagr is not None else 0.05
    base_growth = float(np.clip(base_growth_raw, -0.05, 0.15))
    base_fcf = history.latest_fcf

    scenarios: list[DCFScenario] = []
    scenario_specs = [
        # name, initial_growth_mul, terminal_growth, discount_mul
        ("Bear", 0.5, 0.020, 1.20),
        ("Base", 1.0, 0.025, 1.00),
        ("Bull", 1.20, 0.030, 0.90),
    ]
    for name, g_mul, term_g, disc_mul in scenario_specs:
        g_init = float(np.clip(base_growth * g_mul, -0.08, 0.20))
        r = float(np.clip(discount_rate * disc_mul, 0.03, 0.20))
        scenarios.append(_build_scenario(
            name=name, base_fcf=base_fcf,
            initial_growth=g_init, terminal_growth=term_g,
            discount_rate=r, forecast_years=FORECAST_YEARS,
            shares=shares, cash=cash, debt=debt, current_price=current_price,
        ))

    sensitivity = _build_sensitivity(
        base_fcf=base_fcf, initial_growth=base_growth,
        base_discount=discount_rate, forecast_years=FORECAST_YEARS,
        shares=shares, cash=cash, debt=debt, current_price=current_price,
    )

    weighted_intrinsic = sum(
        SCENARIO_WEIGHTS[s.name] * s.intrinsic_per_share for s in scenarios
    )
    weighted_upside = ((weighted_intrinsic - current_price) / current_price
                       if current_price > 0 else 0.0)

    recommendation = _recommend(weighted_upside, history.reliability)
    explanations = _explain(
        ticker, history, base_growth, discount_rate, beta,
        scenarios, weighted_intrinsic, weighted_upside,
        current_price, recommendation,
    )

    return DCFValuation(
        ticker=ticker, method="dcf_fcf", current_price=current_price,
        history=history, base_beta=beta, base_discount_rate=discount_rate,
        base_growth=base_growth,
        scenarios=scenarios, sensitivity=sensitivity,
        weighted_intrinsic=float(weighted_intrinsic),
        weighted_upside_pct=float(weighted_upside),
        recommendation=recommendation,
        explanations=explanations,
    )


# --- Serialization --------------------------------------------------------

def to_dict(v: DCFValuation) -> dict[str, Any]:
    def scen(s: DCFScenario) -> dict[str, Any]:
        return {
            "name": s.name,
            "assumptions": asdict(s.assumptions),
            "forecast": [asdict(r) for r in s.forecast],
            "terminal_value": s.terminal_value,
            "terminal_pv": s.terminal_pv,
            "enterprise_value": s.enterprise_value,
            "equity_value": s.equity_value,
            "intrinsic_per_share": s.intrinsic_per_share,
            "current_price": s.current_price,
            "upside_pct": s.upside_pct,
            "margin_of_safety": s.margin_of_safety,
        }

    return {
        "ticker": v.ticker,
        "method": v.method,
        "error": v.error,
        "current_price": v.current_price,
        "history": asdict(v.history) if v.history else None,
        "base_beta": v.base_beta,
        "base_discount_rate": v.base_discount_rate,
        "base_growth": v.base_growth,
        "scenarios": [scen(s) for s in v.scenarios],
        "sensitivity": [asdict(c) for c in v.sensitivity],
        "weighted_intrinsic": v.weighted_intrinsic,
        "weighted_upside_pct": v.weighted_upside_pct,
        "recommendation": v.recommendation,
        "scenario_weights": SCENARIO_WEIGHTS,
        "assumptions_global": {
            "risk_free_rate": RISK_FREE_RATE,
            "equity_risk_premium": EQUITY_RISK_PREMIUM,
            "forecast_years": FORECAST_YEARS,
        },
        "explanations": v.explanations,
    }
