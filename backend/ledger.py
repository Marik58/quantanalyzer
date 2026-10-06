"""Prediction ledger: every call any model or agent makes, sealed when it is made.

Why this exists (ROADMAP Phase 1, docs/AGENT_CHARTERS.md §7): an AI agent cannot
be honestly backtested on dates its training data already covers, so its track
record has to be built forward, one dated call at a time. A call is only worth
grading if nobody could change it afterwards, and it can only be audited if we
know exactly what the agent saw. So every call stores:

  - who made it: agent_id, charter_version and model_id (a new model = a new version)
  - the complete evidence packet, stored once and keyed by its SHA-256 hash
  - as_of (the data date), the date it was recorded, and the horizon in trading days
  - the source tag (which screen or scout surfaced it) and its candidate pool
  - whether the packet was a deliberate trap (trap calls are never graded)

Calls are append-only. The only field that can change later is the audit status.

Grading uses the benchmark's (SPY) trading calendar. Entry is the close of the
first trading day after both as_of and the recording date, so a call can never
be "made" at a price that was already known when it was written down. Exit is
horizon_days trading days later. Returns are total returns from a single fresh
dividend-and-split-adjusted fetch (never the app's stale-cache fallback). A
stock with no live prices is graded from the stored daily snapshots, or flagged
"needs_review" for a manual final return; it is never silently dropped.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from backend import db

BENCHMARK = "SPY"
STANCES = ("strong_negative", "negative", "neutral", "positive", "strong_positive")
AUDIT_STATUSES = ("unaudited", "passed", "warned", "failed")
FINAL_GRADE_STATUSES = ("graded", "graded_snapshot", "graded_manual")
MAX_HORIZON_DAYS = 252 * 5
# If a stock didn't trade on the exact entry/exit day (a halt), use the first
# close within this many trading days; past that, the call needs review.
GRACE_DAYS = 5

# fetcher(tickers, start, end) -> {ticker: Series of adjusted closes indexed by "YYYY-MM-DD"}
CloseFetcher = Callable[[list[str], str, str], dict[str, pd.Series]]
# fetcher(tickers, start, end) -> {ticker: DataFrame[close, adj_close, dividend, split]}
BarFetcher = Callable[[list[str], str, str], dict[str, pd.DataFrame]]


class LedgerError(ValueError):
    """A call or grade was rejected; the message says why."""


def _today() -> date:
    """Today on the exchange's calendar (US Eastern). Tests replace this."""
    return pd.Timestamp.now(tz="America/New_York").date()


def _parse_date(value: str | date, name: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise LedgerError(f"{name} must be YYYY-MM-DD, got {value!r}") from exc


def _clean(obj: Any) -> Any:
    """Make a packet JSON-safe and deterministic: NaN/inf become None, numpy
    scalars become Python numbers, dates become ISO strings."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def _canonical(obj: Any) -> str:
    return json.dumps(_clean(obj), sort_keys=True, separators=(",", ":"), allow_nan=False)


def packet_hash(packet: dict[str, Any]) -> str:
    """SHA-256 of the packet's canonical JSON: the same evidence, the same hash."""
    return hashlib.sha256(_canonical(packet).encode("utf-8")).hexdigest()


def _required(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise LedgerError(f"{name} is required")
    return value


# --- Recording ---------------------------------------------------------------

def store_packet(packet: dict[str, Any]) -> str:
    """Store evidence once and return its hash. Shared evidence (the benchmark's
    price history, say) can be stored once and referenced by hash from many calls."""
    packet_json = _canonical(packet)
    p_hash = hashlib.sha256(packet_json.encode("utf-8")).hexdigest()
    db.execute("INSERT INTO ledger_packets(packet_hash, packet) VALUES(?, ?) "
               "ON CONFLICT DO NOTHING", (p_hash, packet_json))
    return p_hash


def get_packet(p_hash: str) -> dict[str, Any] | None:
    rows = db.query("SELECT packet FROM ledger_packets WHERE packet_hash = ?", (p_hash,))
    return json.loads(rows[0][0]) if rows else None


def record_pool(label: str, as_of: str | date, tickers: list[str]) -> str:
    """Store the candidate list an agent picked from. Its equal-weighted return
    is the agent's fairest benchmark (did it beat the stocks it passed over?)."""
    label = _required(label, "label")
    as_of_s = _parse_date(as_of, "as_of").isoformat()
    names = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not names:
        raise LedgerError("a pool needs at least one ticker")
    pool_id = hashlib.sha256(f"{label}|{as_of_s}|{','.join(names)}".encode()).hexdigest()[:16]
    db.execute("INSERT INTO ledger_pools(pool_id, label, as_of, tickers) VALUES(?, ?, ?, ?) "
               "ON CONFLICT DO NOTHING", (pool_id, label, as_of_s, json.dumps(names)))
    return pool_id


def record_call(*, agent_id: str, charter_version: str, model_id: str, subject: str,
                as_of: str | date, horizon_days: int, output: dict[str, Any],
                packet: dict[str, Any], source_tag: str = "", pool_id: str | None = None,
                is_trap: bool = False) -> str:
    """Seal one call. Returns its call_id. Raises LedgerError on anything invalid.

    `output["p_beat_market"]`, when present, is a probability in [0, 1] that the
    subject's total return beats the benchmark's over the horizon.
    """
    agent_id = _required(agent_id, "agent_id")
    charter_version = _required(charter_version, "charter_version")
    model_id = _required(model_id, "model_id")  # "rules" for plain-code twins
    subject = _required(subject, "subject").upper()
    as_of_d = _parse_date(as_of, "as_of")
    recorded_on = _today()
    if as_of_d > recorded_on:
        raise LedgerError(f"as_of {as_of_d} is after the recording date {recorded_on}")
    try:
        horizon = int(horizon_days)
    except (TypeError, ValueError) as exc:
        raise LedgerError("horizon_days must be an integer") from exc
    if not 1 <= horizon <= MAX_HORIZON_DAYS:
        raise LedgerError(f"horizon_days must be 1..{MAX_HORIZON_DAYS}, got {horizon}")
    if not isinstance(output, dict) or not isinstance(packet, dict):
        raise LedgerError("output and packet must be dicts")

    output = _clean(output)
    stance = output.get("stance")
    if stance is not None and stance not in STANCES:
        raise LedgerError(f"stance must be one of {STANCES}, got {stance!r}")
    p = output.get("p_beat_market")
    if p is not None:
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0.0 <= p <= 1.0:
            raise LedgerError(f"p_beat_market must be a probability in [0, 1], got {p!r}")
        p = float(p)
    if pool_id is not None and not db.query("SELECT 1 FROM ledger_pools WHERE pool_id = ?",
                                            (pool_id,)):
        raise LedgerError(f"unknown pool_id {pool_id!r}; record the pool first")

    p_hash = store_packet(packet)
    call_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO ledger_calls(call_id, agent_id, charter_version, model_id, subject, "
        "as_of, recorded_on, horizon_days, stance, p_beat_market, output, packet_hash, "
        "source_tag, pool_id, is_trap) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (call_id, agent_id, charter_version, model_id, subject, as_of_d.isoformat(),
         recorded_on.isoformat(), horizon, stance, p, json.dumps(output, sort_keys=True),
         p_hash, (source_tag or "").strip(), pool_id, 1 if is_trap else 0))
    return call_id


def set_audit_status(call_id: str, status: str, note: str = "") -> None:
    """The one mutable field. A failed audit keeps the call in the record, flagged."""
    if status not in AUDIT_STATUSES:
        raise LedgerError(f"audit status must be one of {AUDIT_STATUSES}")
    if not db.query("SELECT 1 FROM ledger_calls WHERE call_id = ?", (call_id,)):
        raise LedgerError(f"unknown call {call_id!r}")
    db.execute("UPDATE ledger_calls SET audit_status = ?, audit_note = ? WHERE call_id = ?",
               (status, note.strip(), call_id))


# --- Reading -----------------------------------------------------------------

_CALL_COLS = ("call_id", "agent_id", "charter_version", "model_id", "subject", "as_of",
              "recorded_on", "horizon_days", "stance", "p_beat_market", "output",
              "packet_hash", "source_tag", "pool_id", "is_trap", "audit_status", "audit_note")
_GRADE_COLS = ("status", "method", "entry_date", "exit_date", "total_return",
               "bench_return", "excess_return", "beat_market", "brier", "note")


def _row_to_call(row: tuple) -> dict[str, Any]:
    call = dict(zip(_CALL_COLS, row[:len(_CALL_COLS)]))
    call["output"] = json.loads(call["output"])
    call["is_trap"] = bool(call["is_trap"])
    grade = dict(zip(_GRADE_COLS, row[len(_CALL_COLS):]))
    call["grade"] = grade if grade["status"] is not None else None
    return call


def _select_calls(where: str = "", params: tuple = (), limit: int | None = None) -> list[dict]:
    cols = ", ".join(f"c.{c}" for c in _CALL_COLS) + ", " + ", ".join(f"g.{c}" for c in _GRADE_COLS)
    sql = (f"SELECT {cols} FROM ledger_calls c "
           f"LEFT JOIN ledger_grades g ON g.call_id = c.call_id {where} "
           f"ORDER BY c.created_at DESC, c.call_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [_row_to_call(r) for r in db.query(sql, params)]


def called_this_week(agent_id: str) -> set[str]:
    """Subjects this agent has already called since Monday (recording is weekly)."""
    today = _today()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    rows = db.query("SELECT DISTINCT subject FROM ledger_calls "
                    "WHERE agent_id = ? AND recorded_on >= ? AND is_trap = 0", (agent_id, monday))
    return {r[0] for r in rows}


def get_call(call_id: str, with_packet: bool = True) -> dict[str, Any] | None:
    found = _select_calls("WHERE c.call_id = ?", (call_id,))
    if not found:
        return None
    call = found[0]
    if with_packet:
        call["packet"] = get_packet(call["packet_hash"])
    return call


def list_calls(agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if agent_id:
        return _select_calls("WHERE c.agent_id = ?", (agent_id,), limit)
    return _select_calls(limit=limit)


def get_pool(pool_id: str) -> dict[str, Any] | None:
    rows = db.query("SELECT pool_id, label, as_of, tickers FROM ledger_pools WHERE pool_id = ?",
                    (pool_id,))
    if not rows:
        return None
    r = rows[0]
    return {"pool_id": r[0], "label": r[1], "as_of": r[2], "tickers": json.loads(r[3])}


# --- Daily price snapshots ---------------------------------------------------

def fetch_daily_bars(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Live unadjusted closes plus dividend and split events, one ticker at a time."""
    import yfinance as yf

    from backend.analysis import data as data_mod

    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        hist, _err = data_mod._yf_call_with_retry(
            t, "snapshot", lambda t=t: yf.Ticker(t, session=data_mod._SESSION).history(
                start=start, end=end, auto_adjust=False, actions=True))
        if hist is None or "Close" not in hist:
            continue
        frame = pd.DataFrame({
            "close": hist["Close"],
            "adj_close": hist["Adj Close"] if "Adj Close" in hist else hist["Close"],
            "dividend": hist["Dividends"] if "Dividends" in hist else 0.0,
            "split": hist["Stock Splits"] if "Stock Splits" in hist else 0.0,
        }).dropna(subset=["close"])
        frame.index = [ts.strftime("%Y-%m-%d") for ts in frame.index]
        out[t] = frame
    return out


def watched_tickers() -> list[str]:
    """Everything an open call depends on: its subject, its pool, and the benchmark."""
    rows = db.query(
        "SELECT DISTINCT c.subject, c.pool_id FROM ledger_calls c "
        "LEFT JOIN ledger_grades g ON g.call_id = c.call_id "
        "WHERE c.is_trap = 0 AND (g.call_id IS NULL OR g.status = 'needs_review')")
    names = {BENCHMARK}
    for subject, _pool in rows:
        names.add(subject)
    for pool_id in {p for _s, p in rows if p}:   # each pool once, not once per call
        pool = get_pool(pool_id)
        if pool:
            names.update(pool["tickers"])
    return sorted(names)


def snapshot_prices(tickers: list[str] | None = None, lookback_days: int = 14,
                    fetcher: BarFetcher | None = None) -> dict[str, Any]:
    """Store recent daily closes for every watched ticker. The first value seen
    for a (ticker, date) is kept; re-running is harmless."""
    names = sorted({t.strip().upper() for t in (tickers or watched_tickers()) if t.strip()})
    today = _today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    bars = (fetcher or fetch_daily_bars)(names, start, end)

    before = db.query("SELECT COUNT(*) FROM price_snapshots")[0][0]
    rows, missing = [], []
    for t in names:
        frame = bars.get(t)
        if frame is None or frame.empty:
            missing.append(t)
            continue
        for day, r in frame.iterrows():
            if str(day) > today.isoformat():
                continue
            rows.append((t, str(day), _num(r.get("close")), _num(r.get("adj_close")),
                         _num(r.get("dividend")) or 0.0, _num(r.get("split")) or 0.0))
    db.execute_many("INSERT INTO price_snapshots(ticker, date, close, adj_close, dividend, split) "
                    "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", rows)
    after = db.query("SELECT COUNT(*) FROM price_snapshots")[0][0]
    return {"tickers": len(names), "rows_added": int(after - before), "missing": missing}


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# --- Grading -----------------------------------------------------------------

def fetch_total_return_closes(tickers: list[str], start: str, end: str) -> dict[str, pd.Series]:
    """Live dividend-and-split-adjusted closes. Deliberately bypasses the app's
    stale-cache fallback: a grade computed from stale prices would be wrong."""
    import yfinance as yf

    from backend.analysis import data as data_mod

    out: dict[str, pd.Series] = {}
    for t in tickers:
        hist, _err = data_mod._yf_call_with_retry(
            t, "grading", lambda t=t: yf.Ticker(t, session=data_mod._SESSION).history(
                start=start, end=end, auto_adjust=True))
        if hist is None or "Close" not in hist:
            continue
        s = hist["Close"].dropna().astype(float)
        s.index = [ts.strftime("%Y-%m-%d") for ts in s.index]
        out[t] = s
    return out


def _first_price(series: pd.Series | None, calendar: list[str], idx: int) -> tuple[str, float] | None:
    """The close on calendar[idx], or the first one within GRACE_DAYS after it."""
    if series is None or series.empty:
        return None
    for k in range(idx, min(idx + GRACE_DAYS + 1, len(calendar))):
        day = calendar[k]
        if day in series.index:
            v = _num(series[day])
            if v is not None and v > 0:
                return day, v
    return None


def _snapshot_return(subject: str, calendar: list[str], entry_idx: int,
                     exit_idx: int) -> tuple[float, str, str] | None:
    """Fallback for stocks with no live prices: closes plus cash dividends,
    with splits applied to the share count, from the stored daily snapshots."""
    last = calendar[min(exit_idx + GRACE_DAYS, len(calendar) - 1)]
    rows = db.query("SELECT date, close, dividend, split FROM price_snapshots "
                    "WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
                    (subject, calendar[entry_idx], last))
    if not rows:
        return None
    closes = pd.Series({r[0]: r[1] for r in rows if r[1]}, dtype=float)
    entry = _first_price(closes, calendar, entry_idx)
    exit_ = _first_price(closes, calendar, exit_idx)
    if entry is None or exit_ is None:
        return None
    shares, cash = 1.0, 0.0
    for day, _close, dividend, split in rows:
        if entry[0] < day <= exit_[0]:
            if split and split > 0:
                shares *= float(split)
            if dividend:
                cash += shares * float(dividend)
    return (shares * exit_[1] + cash) / entry[1] - 1.0, entry[0], exit_[0]


def _write_grade(call_id: str, status: str, method: str | None, entry: str | None,
                 exit_: str | None, total: float | None, bench: float | None,
                 p: float | None, note: str = "") -> None:
    excess = beat = brier = None
    if total is not None and bench is not None:
        excess = total - bench
        beat = 1 if total > bench else 0
        if p is not None:
            brier = (p - beat) ** 2
    # Final grades are immutable: the update only fires over a needs_review row.
    db.execute(
        "INSERT INTO ledger_grades(call_id, status, method, entry_date, exit_date, "
        "total_return, bench_return, excess_return, beat_market, brier, note) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(call_id) DO UPDATE SET status = excluded.status, "
        "method = excluded.method, entry_date = excluded.entry_date, "
        "exit_date = excluded.exit_date, total_return = excluded.total_return, "
        "bench_return = excluded.bench_return, excess_return = excluded.excess_return, "
        "beat_market = excluded.beat_market, brier = excluded.brier, note = excluded.note, "
        "graded_at = CURRENT_TIMESTAMP WHERE ledger_grades.status = 'needs_review'",
        (call_id, status, method, entry, exit_, total, bench, excess, beat, brier, note))


def _open_calls() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT c.call_id, c.subject, c.as_of, c.recorded_on, c.horizon_days, c.p_beat_market "
        "FROM ledger_calls c LEFT JOIN ledger_grades g ON g.call_id = c.call_id "
        "WHERE c.is_trap = 0 AND (g.call_id IS NULL OR g.status = 'needs_review')")
    keys = ("call_id", "subject", "as_of", "recorded_on", "horizon_days", "p_beat_market")
    return [dict(zip(keys, r)) for r in rows]


def _window(call: dict[str, Any], calendar: list[str]) -> tuple[int, int] | None:
    """(entry_idx, exit_idx) on the calendar, or None if not due yet."""
    after = max(call["as_of"], call["recorded_on"])
    entry_idx = bisect.bisect_right(calendar, after)
    exit_idx = entry_idx + int(call["horizon_days"])
    if exit_idx >= len(calendar):
        return None
    return entry_idx, exit_idx


def grade_due(fetcher: CloseFetcher | None = None) -> dict[str, Any]:
    """Grade every open call whose horizon has passed. Never grades without the
    benchmark; never drops a stock that stopped trading."""
    fetch = fetcher or fetch_total_return_closes
    summary = {"open": 0, "graded": 0, "graded_snapshot": 0, "needs_review": 0, "not_due": 0}
    pending = _open_calls()
    summary["open"] = len(pending)
    if not pending:
        return summary

    start = min(max(c["as_of"], c["recorded_on"]) for c in pending)
    end = (_today() + timedelta(days=1)).isoformat()
    bench = fetch([BENCHMARK], start, end).get(BENCHMARK)
    if bench is None or bench.empty:
        summary["error"] = "benchmark prices unavailable; nothing was graded"
        return summary
    calendar = sorted(bench.index)

    due = []
    for call in pending:
        window = _window(call, calendar)
        if window is None:
            summary["not_due"] += 1
        else:
            due.append((call, *window))
    subjects = sorted({c["subject"] for c, _, _ in due})
    series = fetch(subjects, start, end) if subjects else {}

    def bench_return(start_day: str, end_day: str) -> float | None:
        """The benchmark over the same days the stock was actually held."""
        if start_day in bench.index and end_day in bench.index:
            return float(bench[end_day]) / float(bench[start_day]) - 1.0
        return None

    for call, entry_idx, exit_idx in due:
        s = series.get(call["subject"])
        entry = _first_price(s, calendar, entry_idx)
        exit_ = _first_price(s, calendar, exit_idx)
        bench_ret = bench_return(entry[0], exit_[0]) if entry and exit_ else None
        if entry and exit_ and bench_ret is not None:
            total = exit_[1] / entry[1] - 1.0
            note = "" if exit_[0] == calendar[exit_idx] else f"no trade on {calendar[exit_idx]}; used {exit_[0]}"
            _write_grade(call["call_id"], "graded", "live", entry[0], exit_[0],
                         total, bench_ret, call["p_beat_market"], note)
            summary["graded"] += 1
            continue
        # Prices may simply not be published yet for the last grace days: wait.
        if exit_idx + GRACE_DAYS >= len(calendar):
            summary["not_due"] += 1
            continue
        snap = _snapshot_return(call["subject"], calendar, entry_idx, exit_idx)
        snap_bench = bench_return(snap[1], snap[2]) if snap else None
        if snap and snap_bench is not None:
            total, e_day, x_day = snap
            bench_ret = snap_bench
            _write_grade(call["call_id"], "graded_snapshot", "snapshots", e_day, x_day,
                         total, bench_ret, call["p_beat_market"],
                         "no live prices; computed from stored daily snapshots "
                         "(closes plus cash dividends)")
            summary["graded_snapshot"] += 1
            continue
        _write_grade(call["call_id"], "needs_review", None, calendar[entry_idx],
                     calendar[exit_idx], None, None, None,
                     "no price at the exit date: the stock may have been delisted or "
                     "acquired. Record its final return with grade_manually().")
        summary["needs_review"] += 1
    return summary


def grade_manually(call_id: str, total_return: float, note: str,
                   fetcher: CloseFetcher | None = None) -> None:
    """Record the final return of a stock that stopped trading (a buyout price,
    or -1.0 if the shares became worthless). The note must say where it came from."""
    if len((note or "").strip()) < 10:
        raise LedgerError("explain where the final return came from (10+ characters)")
    if not -1.0 <= float(total_return) <= 100.0:
        raise LedgerError("total_return is a decimal (e.g. -0.35), at least -1.0")
    call = get_call(call_id, with_packet=False)
    if call is None:
        raise LedgerError(f"unknown call {call_id!r}")
    if call["is_trap"]:
        raise LedgerError("trap calls are never graded")
    if call["grade"] and call["grade"]["status"] in FINAL_GRADE_STATUSES:
        raise LedgerError("this call already has a final grade")
    start = max(call["as_of"], call["recorded_on"])
    end = (_today() + timedelta(days=1)).isoformat()
    bench = (fetcher or fetch_total_return_closes)([BENCHMARK], start, end).get(BENCHMARK)
    if bench is None or bench.empty:
        raise LedgerError("benchmark prices unavailable")
    calendar = sorted(bench.index)
    window = _window(call, calendar)
    if window is None:
        raise LedgerError("this call's horizon has not passed yet")
    b_entry = _first_price(bench, calendar, window[0])
    b_exit = _first_price(bench, calendar, window[1])
    _write_grade(call_id, "graded_manual", "manual", calendar[window[0]], calendar[window[1]],
                 float(total_return), b_exit[1] / b_entry[1] - 1.0, call["p_beat_market"],
                 note.strip())


# --- Summaries ---------------------------------------------------------------

def track_record(agent_id: str, charter_version: str | None = None) -> dict[str, Any]:
    """A first report card. The full scoreboard (pool, base-rate, coin-flip and
    factor-adjusted benchmarks) arrives in Roadmap Phase 5."""
    where, params = "WHERE c.agent_id = ? AND c.is_trap = 0", (agent_id,)
    if charter_version:
        where += " AND c.charter_version = ?"
        params += (charter_version,)
    calls = _select_calls(where, params)
    final = [c for c in calls if c["grade"] and c["grade"]["status"] in FINAL_GRADE_STATUSES]

    def _mean(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    by_stance: dict[str, dict[str, Any]] = {}
    for c in final:
        bucket = by_stance.setdefault(c["stance"] or "none", {"n": 0, "excess": [], "beat": []})
        bucket["n"] += 1
        bucket["excess"].append(c["grade"]["excess_return"])
        bucket["beat"].append(c["grade"]["beat_market"])
    return {
        "agent_id": agent_id,
        "charter_version": charter_version,
        "calls": len(calls),
        "graded": len(final),
        "pending": sum(1 for c in calls if c["grade"] is None),
        "needs_review": sum(1 for c in calls if c["grade"] and c["grade"]["status"] == "needs_review"),
        "failed_audit": sum(1 for c in calls if c["audit_status"] == "failed"),
        "hit_rate": _mean([c["grade"]["beat_market"] for c in final]),
        "mean_excess_return": _mean([c["grade"]["excess_return"] for c in final]),
        "mean_brier": _mean([c["grade"]["brier"] for c in final if c["grade"]["brier"] is not None]),
        "by_stance": {k: {"n": v["n"], "mean_excess_return": _mean(v["excess"]),
                          "hit_rate": _mean(v["beat"])} for k, v in by_stance.items()},
    }


def agents_summary() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT c.agent_id, c.charter_version, COUNT(*), "
        "SUM(CASE WHEN g.status IN ('graded', 'graded_snapshot', 'graded_manual') THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN g.call_id IS NULL THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN g.status = 'needs_review' THEN 1 ELSE 0 END) "
        "FROM ledger_calls c LEFT JOIN ledger_grades g ON g.call_id = c.call_id "
        "WHERE c.is_trap = 0 GROUP BY c.agent_id, c.charter_version ORDER BY c.agent_id")
    keys = ("agent_id", "charter_version", "calls", "graded", "pending", "needs_review")
    return [dict(zip(keys, (r[0], r[1], *(int(x or 0) for x in r[2:])))) for r in rows]
