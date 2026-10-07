"""Growth Screen and Value Screen: the rule-based twins of the Growth Hunter and the
Quality & Value analyst (docs/AGENT_CHARTERS.md §9.2-9.3), and their backtest.

**The rules below were written on 2026-10-07, before any result was seen.** They are
versioned: changing any threshold makes a new version, and every version that is run
is recorded in the trials ledger, so a lucky variant can't be quietly kept. Thresholds
are round numbers taken from the charters' method, not tuned.

Growth Screen (growth-v1), all must hold:
  - revenue grew at least 15% in the latest fiscal year, and at least 12% a year
    over the last three (growth that has lasted, not one good year)
  - operating cash flow is positive (profit turning into cash)
  - operating margin fell by no more than 5 percentage points (quality of growth)
  - the diluted share count grew by no more than 5% (growth not paid for with new shares)
  - price-to-sales is not in the top 10% of the S&P 500 that month (the price doesn't
    already assume perfection)

Value Screen (value-v1, "cheap and high quality"), all must hold:
  - cheap: in the cheapest 30% of the S&P 500 that month on the average rank of
    earnings yield, free-cash-flow yield and book-to-market (at least two available)
  - profitable: net income and operating cash flow both positive
  - quality: operating income / total assets at or above that month's median
  - no dilution: diluted share count grew by no more than 2%

Yardstick (charters §13-14): each month's picks, equal-weighted, against the Candidate
Pool (every usable S&P 500 member that month, equal-weighted) and SPY, after a trading
cost, with factor-adjusted alpha. Stage A passes only if alpha against the pool has
t >= 3 and holds up in most sub-periods.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

RULES: dict[str, dict[str, float]] = {
    "growth-v1": {"revenue_growth_min": 0.15, "revenue_cagr3_min": 0.12,
                  "margin_drop_max": 0.05, "share_growth_max": 0.05, "ps_pct_max": 0.90},
    "value-v1": {"cheap_top_share": 0.30, "min_value_measures": 2,
                 "op_roa_pct_min": 0.50, "share_growth_max": 0.02},
}
MIN_NAMES = 5          # fewer picks than this: the month holds the pool instead (and is counted)
COST_BPS = 10.0        # per trade, each way
T_BAR = 3.0            # Harvey, Liu & Zhu (2016): the bar when many ideas get tested


def add_ratios(g: pd.DataFrame) -> pd.DataFrame:
    """Per-stock ratios from the panel's first-filed numbers and that month's price."""
    g = g.copy()
    num = lambda c: pd.to_numeric(g.get(c), errors="coerce")   # noqa: E731
    rev, rev1, rev3 = num("revenue"), num("revenue_1"), num("revenue_3")
    op, op1, cap = num("operating_income"), num("operating_income_1"), num("mcap")
    g["rev_growth"] = rev / rev1 - 1
    g["rev_cagr3"] = (rev / rev3) ** (1 / 3) - 1
    g["margin_change"] = op / rev - op1 / rev1
    g["share_growth"] = num("shares") / num("shares_1") - 1
    g["ps"] = cap / rev
    g["ep"] = num("net_income") / cap
    g["fcfy"] = (num("operating_cash_flow") - num("capex")) / cap
    g["bm"] = num("equity") / cap
    g["op_roa"] = op / num("total_assets")
    for c in ("rev_growth", "rev_cagr3", "margin_change", "share_growth", "ps", "ep", "fcfy", "bm", "op_roa"):
        g[c] = g[c].replace([np.inf, -np.inf], np.nan)
    g.loc[(rev1 <= 0) | (rev3 <= 0), ["rev_growth", "rev_cagr3"]] = np.nan
    # Data-error guards, not screen rules. Filings sometimes carry a number with the
    # wrong scale (thousands vs units), which would pose as 1000% growth or a 99.9%
    # buyback. A ratio outside these wide bounds is treated as unknown, so the stock
    # fails any rule that needs it instead of passing on a typo.
    bounds = {"rev_growth": (-0.9, 5.0), "rev_cagr3": (-0.6, 2.0), "margin_change": (-2.0, 2.0),
              "share_growth": (-0.5, 1.0), "ep": (-1.0, 1.0), "fcfy": (-1.0, 1.0), "bm": (-5.0, 20.0),
              "op_roa": (-2.0, 2.0)}
    g["data_guarded"] = 0
    for c, (lo, hi) in bounds.items():
        bad = g[c].notna() & ~g[c].between(lo, hi)
        g.loc[bad, c] = np.nan
        g["data_guarded"] += bad.astype(int)
    return g


def growth_screen(g: pd.DataFrame, r: dict[str, float]) -> pd.Series:
    ps_cap = g["ps"].quantile(r["ps_pct_max"])
    return ((g["rev_growth"] >= r["revenue_growth_min"]) & (g["rev_cagr3"] >= r["revenue_cagr3_min"])
            & (pd.to_numeric(g["operating_cash_flow"], errors="coerce") > 0)
            & (g["margin_change"] >= -r["margin_drop_max"])
            & (g["share_growth"] <= r["share_growth_max"])
            & (g["ps"] <= ps_cap)).fillna(False)


def value_screen(g: pd.DataFrame, r: dict[str, float]) -> pd.Series:
    ranks = g[["ep", "fcfy", "bm"]].rank(pct=True)            # 1.0 = cheapest
    enough = ranks.notna().sum(axis=1) >= r["min_value_measures"]
    score = ranks.mean(axis=1).where(enough)
    cheap = score >= score.quantile(1 - r["cheap_top_share"])
    profitable = ((pd.to_numeric(g["net_income"], errors="coerce") > 0)
                  & (pd.to_numeric(g["operating_cash_flow"], errors="coerce") > 0))
    quality = g["op_roa"] >= g["op_roa"].quantile(r["op_roa_pct_min"])
    return (cheap & profitable & quality & (g["share_growth"] <= r["share_growth_max"])).fillna(False)


SCREENS: dict[str, Callable[[pd.DataFrame, dict[str, float]], pd.Series]] = {
    "growth-v1": growth_screen, "value-v1": value_screen}


# --- Backtest ---------------------------------------------------------------------

def monthly_returns(panel: pd.DataFrame, version: str, cost_bps: float = COST_BPS) -> pd.DataFrame:
    """One row per month: pool, picks (gross and after costs), SPY, and the picks themselves."""
    screen, rules = SCREENS[version], RULES[version]
    usable = panel[(panel["missing"] == "") & panel["ret_next"].notna()]
    rows, prev = [], None
    for d, g in usable.groupby("date", sort=True):
        g = add_ratios(g)
        picked = g[screen(g, rules)]
        pool = float(g["ret_next"].mean())
        thin = len(picked) < MIN_NAMES
        held = None if thin else set(picked["cik"])
        if held is None:
            gross, turnover = pool, (0.0 if prev is None else 1.0)
        else:
            gross = float(picked["ret_next"].mean())
            turnover = 1.0 if prev is None else 1 - len(held & prev) / len(held)
        cost = turnover * (1 if prev is None else 2) * cost_bps / 1e4
        rows.append({"date": d, "n_pool": len(g), "n_picks": len(picked), "thin": thin,
                     "pool": pool, "gross": gross, "net": gross - cost, "turnover": turnover,
                     "spy": float(g["spy_next"].iloc[0]) if "spy_next" in g else np.nan,
                     "picks": " ".join(sorted(picked["ticker"]))})
        prev = held
    m = pd.DataFrame(rows)
    m["excess"] = m["net"] - m["pool"]
    return m


def _cagr(r: pd.Series) -> float:
    r = r.dropna()
    return float((1 + r).prod() ** (12 / len(r)) - 1) if len(r) else float("nan")


def _t(x: pd.Series) -> float:
    x = x.dropna()
    sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    return float(x.mean() / sd * np.sqrt(len(x))) if sd > 0 else 0.0


def factor_alpha(m: pd.DataFrame) -> dict[str, Any] | None:
    """Excess return over the pool, regressed on Fama-French 5 + momentum compounded
    over each exact holding month. Alpha is what's left once known tilts are paid."""
    from backend.analysis import factors

    f = factors.load_factors()
    dates = list(pd.to_datetime(m["date"]))
    ys, xs = [], []
    for i in range(len(dates) - 1):
        chunk = f[(f.index > dates[i]) & (f.index <= dates[i + 1])]
        if len(chunk) < 15 or dates[i + 1] > f.index[-1]:
            continue
        xs.append([(1 + chunk[c]).prod() - 1 for c in factors.FACTOR_NAMES])
        ys.append(float(m["excess"].iloc[i]))
    if len(ys) < 24:
        return None
    X = np.column_stack([np.ones(len(ys)), np.array(xs)])
    beta, tvals, r2 = factors._ols(np.array(ys), X)
    return {"months": len(ys), "alpha_per_year": round(float(beta[0]) * 12, 4),
            "alpha_t": round(float(tvals[0]), 2), "r2": round(r2, 3),
            "betas": {n: round(float(b), 2) for n, b in zip(factors.FACTOR_NAMES, beta[1:])},
            "factors_through": f.index[-1].strftime("%Y-%m-%d")}


def summarize(m: pd.DataFrame, panel: pd.DataFrame | None = None) -> dict[str, Any]:
    ex = m["excess"]
    years = pd.to_datetime(m["date"]).dt.year
    blocks = {"2011-2015": years <= 2015, "2016-2020": (years >= 2016) & (years <= 2020),
              "2021-2026": years >= 2021}
    sub = {k: {"months": int(b.sum()), "excess_per_year": round(float(ex[b].mean() * 12), 4),
               "t": round(_t(ex[b]), 2)} for k, b in blocks.items() if b.sum() >= 12}
    by_year = (m.assign(y=years).groupby("y")[["net", "pool", "spy"]]
               .apply(lambda d: (1 + d).prod() - 1))
    months_per_year = years.value_counts()
    full_years = [y for y in by_year.index if months_per_year.get(y, 0) == 12]
    alpha = factor_alpha(m)
    out = {
        "months": len(m), "start": m["date"].iloc[0], "end": m["date"].iloc[-1],
        "thin_months": int(m["thin"].sum()), "avg_picks": round(float(m.loc[~m["thin"], "n_picks"].mean()), 1),
        "avg_pool": round(float(m["n_pool"].mean()), 1),
        "cagr_picks_net": round(_cagr(m["net"]), 4), "cagr_pool": round(_cagr(m["pool"]), 4),
        "cagr_spy": round(_cagr(m["spy"]), 4),
        "excess_per_year": round(float(ex.mean() * 12), 4), "excess_t": round(_t(ex), 2),
        "information_ratio": round(float(ex.mean() / ex.std(ddof=1) * np.sqrt(12)), 2),
        "months_beating_pool": round(float((ex > 0).mean()), 3),
        "avg_turnover": round(float(m["turnover"].mean()), 3),
        "sub_periods": sub, "factor_adjusted": alpha,
        # only full calendar years count toward the 25% hurdle (the last year is usually partial)
        "years_at_25pct": int((by_year.loc[full_years, "net"] >= 0.25).sum()), "years": len(full_years),
        "by_year": {int(y): {k: round(float(v), 4) for k, v in r.items()} for y, r in by_year.iterrows()},
    }
    passes_t = alpha is not None and alpha["alpha_t"] >= T_BAR
    holds = sum(1 for s in sub.values() if s["excess_per_year"] > 0) >= max(2, len(sub) - 1)
    out["stage_a"] = "pass" if passes_t and holds else "fail"
    return out


def pick_base_rates(panel: pd.DataFrame, m: pd.DataFrame) -> dict[str, Any]:
    """How often a pick (vs any pool stock) beat SPY, or made 25%+, over the next 12 months.
    These are the base rates a forecaster must beat (charters §13). Windows overlap, so
    treat them as descriptions, not tests."""
    p = panel[(panel["missing"] == "") & panel["ret_12m"].notna() & panel["spy_12m"].notna()]
    picks = {(r.date, t) for r in m.itertuples() if not r.thin for t in r.picks.split()}
    is_pick = [(d, t) in picks for d, t in zip(p["date"], p["ticker"])]
    beat = p["ret_12m"] > p["spy_12m"]
    big = p["ret_12m"] >= 0.25
    sel = pd.Series(is_pick, index=p.index)
    return {"pool": {"n": int(len(p)), "beat_spy": round(float(beat.mean()), 3),
                     "made_25pct": round(float(big.mean()), 3)},
            "picks": {"n": int(sel.sum()), "beat_spy": round(float(beat[sel].mean()), 3) if sel.any() else None,
                      "made_25pct": round(float(big[sel].mean()), 3) if sel.any() else None}}
