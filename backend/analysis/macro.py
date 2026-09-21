"""Macro inputs from FRED (Federal Reserve Bank of St. Louis).

The DCF previously hardcoded a 4.5% risk-free rate. Treasury yields move, and
a one-point change in the discount rate moves a long-duration valuation by
roughly 15-25%, so a stale constant quietly biases every fair value in the app.

FRED's CSV download endpoint needs no API key and no registration, which keeps
the zero-cost, zero-setup property of the project:

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10

Values are cached on disk for 12 hours, and every reader gets the observation
date alongside the number so the UI can say how fresh it is. If FRED cannot be
reached the documented fallback constant is returned, flagged as such — the app
never silently pretends a stale number is live.

Series used:
    DGS10   10-year Treasury constant maturity yield (percent)
    VIXCLS  CBOE volatility index (level)
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from typing import Any

from backend import cache

log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
CACHE_TTL = 12 * 3600

FALLBACK_RISK_FREE = 0.045      # what the code used before this module existed
FALLBACK_VIX = 18.0


@dataclass
class MacroValue:
    series: str
    value: float
    as_of: str | None
    source: str                 # "FRED" | "fallback"
    is_live: bool

    def to_dict(self) -> dict[str, Any]:
        return {"series": self.series, "value": self.value, "as_of": self.as_of,
                "source": self.source, "is_live": self.is_live}


def _fetch_latest(series: str) -> tuple[float, str] | None:
    """Most recent non-missing observation as (value, date). FRED writes '.' for gaps."""
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(FRED_CSV.format(series=series), impersonate="chrome", timeout=25)
        if r.status_code != 200:
            log.warning("FRED %s returned HTTP %s", series, r.status_code)
            return None
        rows = list(csv.reader(io.StringIO(r.text)))
        for row in reversed(rows[1:]):
            if len(row) < 2:
                continue
            raw = row[1].strip()
            if raw and raw != ".":
                return float(raw), row[0].strip()
    except Exception as exc:
        log.warning("FRED %s fetch failed: %s", series, exc)
    return None


def series_latest(series: str, fallback: float) -> MacroValue:
    key = f"fred:{series}:latest"
    hit = cache.get(key, CACHE_TTL)
    if hit is not None:
        return hit
    got = _fetch_latest(series)
    if got is None:
        return MacroValue(series=series, value=fallback, as_of=None,
                          source="fallback", is_live=False)
    value, as_of = got
    mv = MacroValue(series=series, value=value, as_of=as_of, source="FRED", is_live=True)
    cache.set_(key, mv)
    return mv


def risk_free_rate() -> MacroValue:
    """10-year Treasury yield as a DECIMAL (0.0501), not a percent."""
    mv = series_latest("DGS10", FALLBACK_RISK_FREE * 100.0)
    return MacroValue(series=mv.series, value=round(mv.value / 100.0, 5),
                      as_of=mv.as_of, source=mv.source, is_live=mv.is_live)


def vix() -> MacroValue:
    return series_latest("VIXCLS", FALLBACK_VIX)


def snapshot() -> dict[str, Any]:
    rf, vx = risk_free_rate(), vix()
    return {
        "risk_free_rate": rf.to_dict(),
        "vix": vx.to_dict(),
        "note": ("Live macro inputs from FRED, cached for 12 hours. When FRED is unreachable the "
                 "app falls back to a documented constant and marks the value as not live."),
    }
