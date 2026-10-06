"""Rule-based "twins": plain-code versions of each agent's philosophy.

A twin's calls go into the prediction ledger exactly like an agent's, so the
AI agent can later be compared with the rules it is supposed to improve on
(docs/AGENT_CHARTERS.md §13). The first twin is the Trend Trader's: the
existing technical score in backend/analysis/signals.py, unchanged, recording
one call per stock per week on a fixed tracking list.

The tracking list is a seeded random sample of S&P 500 members, not a
hand-picked list, so it carries no selection bias. It is written to
data/tracking_list.json once and then kept fixed (stocks that later leave the
index stay on it), and it doubles as the twin's candidate pool.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from backend import ledger
from backend.analysis import data as data_mod
from backend.analysis import indicators as ind_mod
from backend.analysis import signals as signals_mod
from backend.analysis import universe as universe_mod

TRACKING_LIST_PATH = Path(__file__).resolve().parent.parent / "data" / "tracking_list.json"
TRACKING_SIZE = 50
TRACKING_SEED = 2026

TREND_TWIN = {
    "agent_id": "trend_twin",
    "charter_version": "v0-signals-technical-score",
    "model_id": "rules",
    "horizon_days": 20,  # four weeks, the same horizon as This Week's 10
}
_STANCE = {"BUY": "positive", "HOLD": "neutral", "SELL": "negative"}

Loader = Callable[[str], "data_mod.TickerData | None"]


def tracking_list(path: Path | None = None) -> dict[str, Any]:
    """The fixed tracking list, creating it on first use."""
    path = path or TRACKING_LIST_PATH
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    as_of = ledger._today().isoformat()
    tickers = [universe_mod.to_yahoo(t) for t in
               universe_mod.sample_members(TRACKING_SIZE, as_of=as_of, seed=TRACKING_SEED)]
    spec = {
        "description": ("Seeded random sample of S&P 500 members used as the twins' "
                        "tracking list and candidate pool. Kept fixed: names that later "
                        "leave the index stay on it."),
        "created_on": as_of,
        "method": f"backend.analysis.universe.sample_members(n={TRACKING_SIZE}, "
                  f"as_of='{as_of}', seed={TRACKING_SEED})",
        "tickers": sorted(tickers),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return spec


def _closes(history) -> dict[str, float]:
    return {ts.strftime("%Y-%m-%d"): round(float(v), 4)
            for ts, v in history["Close"].dropna().items()}


def _complete(sig) -> bool:
    """True only if the score and every factor are real numbers."""
    import math
    values = [sig.composite, sig.confidence, *(f.score for f in sig.factors)]
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _frame(closes: dict[str, float]) -> pd.DataFrame:
    """A price frame from stored closes. The technical score uses only closing
    prices; highs and lows feed ATR, which the score doesn't use."""
    s = pd.Series(closes, dtype=float)
    s.index = pd.to_datetime(s.index)
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 0.0})


def reproduce_trend_twin(packet: dict[str, Any]) -> dict[str, Any]:
    """Recompute a sealed Trend-twin call from its stored evidence alone.

    This is the Auditor's code check for this twin: if the result disagrees
    with the recorded output, the call wasn't made the way the ledger says.
    (Stored closes are rounded to 4 decimals, so the composite can differ in
    its last digit; the action must match.)"""
    bench = ledger.get_packet(packet["benchmark_packet"])
    if bench is None:
        raise ValueError("the benchmark evidence this call references is missing")
    df = ind_mod.compute_all(_frame(packet["closes"]))
    ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
    sig = signals_mod.compute(ready, _frame(bench["closes"]))
    return {"action": sig.action, "stance": _STANCE.get(sig.action, "neutral"),
            "composite": sig.composite}


def record_trend_twin(tickers: list[str], loader: Loader | None = None,
                      max_stale_days: int = 4) -> dict[str, Any]:
    """Record one Trend-twin call per ticker for this week. Re-running in the
    same week only fills in tickers that were missed."""
    load = loader or data_mod.load
    today = ledger._today()
    summary: dict[str, Any] = {"recorded": 0, "already_done": 0, "skipped": []}

    bench_td = load(ledger.BENCHMARK)
    if bench_td is None:
        summary["error"] = "benchmark history unavailable; no calls recorded"
        return summary
    bench_hash = ledger.store_packet({
        "ticker": ledger.BENCHMARK,
        "source": "yfinance daily history (auto-adjusted) via backend.analysis.data.load",
        "closes": _closes(bench_td.history),
    })
    names = sorted({t.strip().upper() for t in tickers if t.strip()})
    pool_id = ledger.record_pool("trend_twin tracking list", today, names)
    done = ledger.called_this_week(TREND_TWIN["agent_id"])

    for t in names:
        if t in done:
            summary["already_done"] += 1
            continue
        td = load(t)
        if td is None:
            summary["skipped"].append({"ticker": t, "reason": "no price history"})
            continue
        last = td.history.index[-1].date()
        if (today - last).days > max_stale_days:
            summary["skipped"].append({"ticker": t, "reason": f"data is stale (last bar {last})"})
            continue
        df = ind_mod.compute_all(td.history)
        ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
        if ready.empty:
            summary["skipped"].append({"ticker": t, "reason": "not enough history for SMA200"})
            continue
        sig = signals_mod.compute(ready, bench_td.history)
        if not _complete(sig):
            # e.g. a recent listing: its 3-month return can't be measured on the
            # rows that already have a 200-day average, so the score is NaN. A
            # call built on that would be made up (Q got a sealed "HOLD, 100%
            # confidence" this way on 2026-10-05).
            summary["skipped"].append({"ticker": t, "reason": "signal incomplete: a factor "
                                       "couldn't be computed from the available history"})
            continue
        output = {
            "stance": _STANCE.get(sig.action, "neutral"),
            "action": sig.action,
            "composite": sig.composite,
            "confidence": sig.confidence,
            "factors": [{"name": f.name, "score": f.score} for f in sig.factors],
            "p_beat_market": None,  # a rules twin states no probability
        }
        packet = {
            "ticker": t,
            "as_of": last.isoformat(),
            "source": "yfinance daily history (auto-adjusted) via backend.analysis.data.load",
            "method": "backend.analysis.signals.compute(indicators.compute_all(history), SPY)",
            "closes": _closes(td.history),
            "benchmark_packet": bench_hash,
        }
        ledger.record_call(agent_id=TREND_TWIN["agent_id"],
                           charter_version=TREND_TWIN["charter_version"],
                           model_id=TREND_TWIN["model_id"], subject=t, as_of=last,
                           horizon_days=TREND_TWIN["horizon_days"], output=output,
                           packet=packet, source_tag="tracking-list", pool_id=pool_id)
        summary["recorded"] += 1
    return summary
