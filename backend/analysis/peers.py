"""Peer comparison module.

Compares a ticker against a curated set of industry peers on valuation, growth,
profitability, and price momentum. Returns a ranked table plus a 0-100 relative
value score and plain-English takeaways.

Design notes:
- Peers are chosen from a hand-curated map keyed to the Fox Fund watchlist
  rather than yfinance sector/industry (which is too coarse and sometimes wrong).
- For each metric we track direction ("lower_better" for P/E, P/S, EV/EBITDA;
  "higher_better" for growth, margin, momentum) so the ranker can orient correctly.
- Negative or missing values are marked "n/a" and excluded from the score.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_SESSION = curl_requests.Session(impersonate="chrome")


# --- Curated peer map ------------------------------------------------------
# Each group is a universe of "reasonable comparables" for Fox Fund's watchlist.
# A ticker looks up its group in TICKER_TO_GROUP; peers = group minus self.

PEER_GROUPS: dict[str, list[str]] = {
    "megacap_platforms":   ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "semiconductors":      ["NVDA", "AMD", "AVGO", "INTC", "QCOM", "TSM"],
    "semi_equipment":      ["AMAT", "LRCX", "KLAC", "ASML", "TER"],
    "eda":                 ["SNPS", "CDNS", "ANSS"],
    "enterprise_software": ["ADBE", "NOW", "CRM", "ORCL", "INTU", "WDAY"],
}

TICKER_TO_GROUP: dict[str, str] = {
    # megacap
    "AAPL": "megacap_platforms", "MSFT": "megacap_platforms",
    "GOOGL": "megacap_platforms", "META": "megacap_platforms",
    "AMZN": "megacap_platforms",
    # semis
    "NVDA": "semiconductors", "AMD": "semiconductors",
    "AVGO": "semiconductors", "INTC": "semiconductors",
    "QCOM": "semiconductors", "TSM": "semiconductors",
    # semi equipment
    "AMAT": "semi_equipment", "LRCX": "semi_equipment",
    "KLAC": "semi_equipment", "ASML": "semi_equipment",
    "TER":  "semi_equipment",
    # eda
    "SNPS": "eda", "CDNS": "eda", "ANSS": "eda",
    # enterprise software
    "ADBE": "enterprise_software", "NOW": "enterprise_software",
    "CRM":  "enterprise_software", "ORCL": "enterprise_software",
    "INTU": "enterprise_software", "WDAY": "enterprise_software",
}

# Metric ID -> (yfinance info key, display label, direction)
# direction: "lower_better" (cheap = good) or "higher_better" (strong = good)
METRIC_SPEC: list[tuple[str, str, str, str]] = [
    ("pe",       "trailingPE",                    "P/E (TTM)",      "lower_better"),
    ("ps",       "priceToSalesTrailing12Months",  "P/S (TTM)",      "lower_better"),
    ("ev_ebitda","enterpriseToEbitda",            "EV/EBITDA",      "lower_better"),
    ("rev_grow", "revenueGrowth",                 "Revenue growth", "higher_better"),
    ("gross_m",  "grossMargins",                  "Gross margin",   "higher_better"),
    # momentum is computed separately from price history, not from info
    ("mom_6m",   "__computed__",                  "6-month return", "higher_better"),
]


# --- Dataclasses -----------------------------------------------------------

@dataclass
class MetricValue:
    metric_id: str
    label: str
    value: float | None        # raw value (e.g., 28.5 for P/E, 0.17 for 17% growth)
    rank: int | None           # 1 = best in peer set for this metric
    percentile: float | None   # 0..100, higher = better along the direction
    status: str                # "best", "mid", "worst", "na"


@dataclass
class PeerRow:
    ticker: str
    name: str
    market_cap: float | None
    metrics: dict[str, MetricValue]


@dataclass
class PeerComparison:
    ticker: str
    group: str | None
    peers_used: list[str]
    target_row: PeerRow | None
    peer_rows: list[PeerRow] = field(default_factory=list)
    relative_value_score: float | None = None   # 0..100, target's percentile avg
    relative_value_label: str = "n/a"           # cheap/fair/expensive/n/a
    status_note: str = ""                        # e.g. "No peer group found."
    explanations: dict[str, str] = field(default_factory=dict)


# --- Fetch helpers ---------------------------------------------------------

@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda t: f"peers_info:{t}")
def _fetch_extended_info(ticker: str) -> dict[str, Any]:
    """Pull extended valuation/profitability info from yfinance."""
    try:
        raw = yf.Ticker(ticker, session=_SESSION).info or {}
    except Exception:
        raw = {}
    keep_keys = {
        "shortName", "longName", "marketCap",
        "trailingPE", "priceToSalesTrailing12Months", "enterpriseToEbitda",
        "revenueGrowth", "grossMargins", "profitMargins",
    }
    return {k: raw.get(k) for k in keep_keys if k in raw}


@cached(ttl_seconds=CACHE_TTL, key_fn=lambda t: f"peers_mom:{t}")
def _fetch_momentum(ticker: str) -> float | None:
    """6-month price return. Cached separately so it refreshes at history cadence."""
    try:
        df = yf.Ticker(ticker, session=_SESSION).history(period="1y", auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty or len(df) < 120:
        return None
    # ~126 trading days = 6 months
    look = min(126, len(df) - 1)
    start = float(df["Close"].iloc[-look - 1])
    end = float(df["Close"].iloc[-1])
    if start <= 0:
        return None
    return (end / start) - 1.0


# --- Metric extraction -----------------------------------------------------

def _extract_metric(metric_id: str, info: dict[str, Any], ticker: str) -> float | None:
    if metric_id == "mom_6m":
        return _fetch_momentum(ticker)
    spec = next((s for s in METRIC_SPEC if s[0] == metric_id), None)
    if spec is None:
        return None
    key = spec[1]
    v = info.get(key)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    # Negative valuation multiples (e.g., negative P/E from losses) are unusable
    # for "lower is better" ranking — treat as n/a. Negative growth/margin is OK.
    if spec[3] == "lower_better" and v <= 0:
        return None
    return v


# --- Ranking ---------------------------------------------------------------

def _rank_metric(values: list[tuple[str, float | None]],
                 direction: str) -> dict[str, tuple[int | None, float | None, str]]:
    """Given [(ticker, value), ...] return {ticker: (rank, percentile, status)}.

    Percentile: 100 = best along direction, 0 = worst. n/a if value missing.
    """
    valid = [(t, v) for t, v in values if v is not None]
    out: dict[str, tuple[int | None, float | None, str]] = {}
    if not valid:
        for t, _ in values:
            out[t] = (None, None, "na")
        return out

    reverse = (direction == "higher_better")
    # Sort best -> worst
    valid.sort(key=lambda tv: tv[1], reverse=reverse)
    n = len(valid)
    rank_by_t: dict[str, int] = {t: i + 1 for i, (t, _) in enumerate(valid)}

    for t, v in values:
        if v is None:
            out[t] = (None, None, "na")
            continue
        r = rank_by_t[t]
        pct = 100.0 if n == 1 else 100.0 * (n - r) / (n - 1)
        if r == 1:
            status = "best"
        elif r == n:
            status = "worst"
        else:
            status = "mid"
        out[t] = (r, pct, status)
    return out


# --- Main entrypoint -------------------------------------------------------

def _find_peers(ticker: str) -> tuple[str | None, list[str]]:
    """Look up curated peer group. Returns (group_name, peers_excluding_self)."""
    t = ticker.upper().strip()
    group = TICKER_TO_GROUP.get(t)
    if group is None:
        return None, []
    peers = [p for p in PEER_GROUPS[group] if p != t]
    return group, peers


def _build_row(ticker: str) -> PeerRow | None:
    info = _fetch_extended_info(ticker)
    if not info:
        return None
    metrics: dict[str, MetricValue] = {}
    for metric_id, _key, label, _direction in METRIC_SPEC:
        v = _extract_metric(metric_id, info, ticker)
        metrics[metric_id] = MetricValue(
            metric_id=metric_id, label=label,
            value=v, rank=None, percentile=None,
            status="na" if v is None else "mid",
        )
    return PeerRow(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName") or ticker,
        market_cap=info.get("marketCap"),
        metrics=metrics,
    )


def _apply_rankings(rows: list[PeerRow]) -> None:
    """Mutate rows in place so each metric gets a rank/percentile/status."""
    for metric_id, _key, _label, direction in METRIC_SPEC:
        values = [(r.ticker, r.metrics[metric_id].value) for r in rows]
        ranked = _rank_metric(values, direction)
        for r in rows:
            rank, pct, status = ranked[r.ticker]
            mv = r.metrics[metric_id]
            mv.rank = rank
            mv.percentile = pct
            mv.status = status


def _relative_value_score(target: PeerRow) -> tuple[float | None, str]:
    """Average percentile across metrics with valid data. Returns (score, label)."""
    pcts = [mv.percentile for mv in target.metrics.values() if mv.percentile is not None]
    if not pcts:
        return None, "n/a"
    score = float(np.mean(pcts))
    # Label: treat score across valuation+growth+momentum. Above 65 = looks cheap/strong,
    # below 35 = looks expensive/weak, middle = fair.
    if score >= 65:
        label = "cheap / attractive"
    elif score <= 35:
        label = "expensive / weak"
    else:
        label = "fair"
    return score, label


def _explain(target: PeerRow | None, peers: list[PeerRow],
             group: str | None, score: float | None,
             label: str, status_note: str) -> dict[str, str]:
    if status_note and target is None:
        return {"overview": status_note}
    if target is None:
        return {"overview": "No data."}

    peer_names = ", ".join(r.ticker for r in peers) or "(no peers)"
    overview = (
        f"{target.ticker} is benchmarked against {len(peers)} peers in the "
        f"'{group}' group: {peer_names}. Each metric is ranked within that set "
        f"— 1 = best, last = worst. The relative value score is the average of "
        f"{target.ticker}'s percentile ranks across all metrics with valid data."
    )

    # Valuation standing: count where target is "best"/"worst"
    bests = [mv.label for mv in target.metrics.values() if mv.status == "best"]
    worsts = [mv.label for mv in target.metrics.values() if mv.status == "worst"]
    nas = [mv.label for mv in target.metrics.values() if mv.status == "na"]

    standing_bits = []
    if bests:
        standing_bits.append(f"Best in group on: {', '.join(bests)}.")
    if worsts:
        standing_bits.append(f"Worst in group on: {', '.join(worsts)}.")
    if nas:
        standing_bits.append(f"Not comparable (missing data): {', '.join(nas)}.")
    standing = " ".join(standing_bits) or "No extreme rankings — the name sits mid-pack on every metric."

    # Valuation vs growth tension check
    pe_mv = target.metrics.get("pe")
    ps_mv = target.metrics.get("ps")
    grow_mv = target.metrics.get("rev_grow")
    val_pcts = [mv.percentile for mv in (pe_mv, ps_mv)
                if mv and mv.percentile is not None]
    val_pct = float(np.mean(val_pcts)) if val_pcts else None
    grow_pct = grow_mv.percentile if grow_mv else None

    if val_pct is not None and grow_pct is not None:
        if val_pct < 35 and grow_pct > 65:
            vg = ("Valuation looks rich relative to peers, but growth is also "
                  "best-in-group — premium may be justified if growth sustains.")
        elif val_pct > 65 and grow_pct < 35:
            vg = ("Trades at a discount to peers, but growth is weakest in "
                  "the group — cheap for a reason, watch for value-trap risk.")
        elif val_pct > 65 and grow_pct > 65:
            vg = ("Cheaper than peers AND growing faster — the most attractive "
                  "setup available in this group on a relative basis.")
        elif val_pct < 35 and grow_pct < 35:
            vg = ("Expensive AND growing slower than peers — the least attractive "
                  "profile in the group on a relative basis.")
        else:
            vg = ("Valuation and growth are roughly in line with peers — no "
                  "dominant relative edge either way.")
    else:
        vg = "Valuation-vs-growth comparison unavailable (missing P/E, P/S, or growth)."

    if score is None:
        interpretation = ("Insufficient comparable data to compute a relative value "
                          "score. Use the per-metric table above and treat the peer "
                          "view qualitatively.")
    else:
        interpretation = (
            f"Relative value score: {score:.0f}/100 → {label}. "
            f"This averages {target.ticker}'s percentile across "
            f"{sum(1 for mv in target.metrics.values() if mv.percentile is not None)} "
            f"valid metrics. A score above 65 means the name ranks in the top third "
            f"of its peer set on most metrics; below 35 means the bottom third. "
            f"Score alone is not a buy/sell call — read it alongside the fundamental "
            f"thesis and the standing above."
        )

    return {
        "overview": overview,
        "standing": standing,
        "valuation_vs_growth": vg,
        "interpretation": interpretation,
    }


def compute(ticker: str) -> PeerComparison:
    ticker = ticker.upper().strip()
    group, peers = _find_peers(ticker)

    if group is None:
        return PeerComparison(
            ticker=ticker, group=None, peers_used=[],
            target_row=_build_row(ticker),
            status_note=(f"No curated peer group for {ticker}. Add it to "
                         f"TICKER_TO_GROUP in backend/analysis/peers.py."),
            explanations={
                "overview": (f"No peer group found for {ticker}. Peer comparison "
                             f"is curated, not auto-derived, so tickers outside the "
                             f"Fox Fund watchlist need to be added manually.")
            },
        )

    target_row = _build_row(ticker)
    peer_rows = [r for r in (_build_row(p) for p in peers) if r is not None]

    if target_row is None:
        return PeerComparison(
            ticker=ticker, group=group, peers_used=[r.ticker for r in peer_rows],
            target_row=None, peer_rows=peer_rows,
            status_note=f"yfinance returned no info for {ticker}.",
            explanations={"overview": f"No data available for {ticker}."},
        )

    all_rows = [target_row] + peer_rows
    _apply_rankings(all_rows)

    score, label = _relative_value_score(target_row)

    return PeerComparison(
        ticker=ticker,
        group=group,
        peers_used=[r.ticker for r in peer_rows],
        target_row=target_row,
        peer_rows=peer_rows,
        relative_value_score=score,
        relative_value_label=label,
        status_note="",
        explanations=_explain(target_row, peer_rows, group, score, label, ""),
    )


# --- Serialization ---------------------------------------------------------

def _row_to_dict(row: PeerRow) -> dict[str, Any]:
    return {
        "ticker": row.ticker,
        "name": row.name,
        "market_cap": row.market_cap,
        "metrics": {mid: asdict(mv) for mid, mv in row.metrics.items()},
    }


def to_dict(result: PeerComparison) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "group": result.group,
        "peers_used": result.peers_used,
        "target_row": _row_to_dict(result.target_row) if result.target_row else None,
        "peer_rows": [_row_to_dict(r) for r in result.peer_rows],
        "relative_value_score": result.relative_value_score,
        "relative_value_label": result.relative_value_label,
        "status_note": result.status_note,
        "explanations": result.explanations,
        "metric_order": [m[0] for m in METRIC_SPEC],
        "metric_labels": {m[0]: m[2] for m in METRIC_SPEC},
    }
