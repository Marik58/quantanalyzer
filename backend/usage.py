"""Anonymous usage log: which tools people open, so we can see what gets used.

Privacy by design (ROADMAP ground rule 10): no names, emails, IP addresses or
browser details are stored. The browser makes up a random session id, keeps it
in localStorage, and sends it with each event; that id is all we ever see. No
third-party trackers. If this data is ever used for published research, that
needs IRB approval first.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend import db

EVENTS = ("page_view", "tab_open", "analyze", "game_round", "paper_order",
          "lesson_open", "lab_open", "literacy_check")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TARGET_RE = re.compile(r"^[A-Za-z0-9 ._:/#-]{0,64}$")
MAX_META_BYTES = 1000


class UsageError(ValueError):
    """An event was rejected; the message says why."""


def record(session_id: str, event: str, target: str = "",
           meta: dict[str, Any] | None = None) -> None:
    session_id = (session_id or "").strip()
    if not _SESSION_RE.match(session_id):
        raise UsageError("session_id must be 8-64 letters, digits, '-' or '_'")
    if event not in EVENTS:
        raise UsageError(f"event must be one of {EVENTS}")
    target = (target or "").strip()
    if not _TARGET_RE.match(target):
        raise UsageError("target must be at most 64 plain characters")
    meta_json = None
    if meta:
        if not isinstance(meta, dict):
            raise UsageError("meta must be an object")
        meta_json = json.dumps(meta, sort_keys=True)
        if len(meta_json.encode("utf-8")) > MAX_META_BYTES:
            raise UsageError(f"meta must be under {MAX_META_BYTES} bytes")
    db.execute("INSERT INTO usage_events(session_id, event, target, meta) VALUES(?, ?, ?, ?)",
               (session_id, event, target.upper() if event == "analyze" else target, meta_json))


def summary(days: int = 30) -> dict[str, Any]:
    """What was used in the last `days` days: totals, sessions, the most-used
    tools, the most-analyzed tickers, and a day-by-day count."""
    days = max(1, min(int(days), 365))
    # CURRENT_TIMESTAMP is stored in UTC on both SQLite and Postgres.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.query("SELECT ts, session_id, event, target FROM usage_events WHERE ts >= ?",
                    (cutoff,))
    by_event: dict[str, int] = {}
    literacy: dict[str, list[int]] = {"first": [], "repeat": []}
    tabs: dict[str, int] = {}
    tickers: dict[str, int] = {}
    per_day: dict[str, set[str]] = {}
    per_day_events: dict[str, int] = {}
    sessions: set[str] = set()
    for ts, session, event, target in rows:
        sessions.add(session)
        by_event[event] = by_event.get(event, 0) + 1
        if event == "tab_open" and target:
            tabs[target] = tabs.get(target, 0) + 1
        if event == "analyze" and target:
            tickers[target] = tickers.get(target, 0) + 1
        if event == "literacy_check" and ":" in (target or ""):
            attempt, _, score = target.partition(":")
            if attempt in literacy and score.isdigit() and int(score) <= 3:
                literacy[attempt].append(int(score))
        day = str(ts)[:10]
        per_day.setdefault(day, set()).add(session)
        per_day_events[day] = per_day_events.get(day, 0) + 1

    def _top(d: dict[str, int], n: int = 10) -> list[dict[str, Any]]:
        return [{"name": k, "count": v}
                for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

    return {
        "window_days": days,
        "events": len(rows),
        "sessions": len(sessions),
        "by_event": dict(sorted(by_event.items())),
        "top_tabs": _top(tabs),
        "top_tickers": _top(tickers),
        "by_day": [{"date": d, "sessions": len(per_day[d]), "events": per_day_events[d]}
                   for d in sorted(per_day)],
        # The "Big Three" literacy check (Lusardi & Mitchell): first tries vs later tries.
        # Later tries come after using the app, so a higher average hints at learning
        # (a hint only: the same people aren't tracked, and nothing is randomized).
        "literacy": {k: {"n": len(v), "avg_score_of_3": round(sum(v) / len(v), 2) if v else None}
                     for k, v in literacy.items()},
    }
