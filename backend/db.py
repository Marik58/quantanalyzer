"""Persistence layer — SQLite by default, Postgres when DATABASE_URL is set.

Local dev needs zero setup: no DATABASE_URL → the same SQLite file as always.
A deployed instance (Render) sets DATABASE_URL and gets a real Postgres, so
watchlists, paper trades, and (later) game state survive restarts — the free
tier wipes local disk on every redeploy, which silently destroyed SQLite.

The two dialects are close enough that one query text works for both if we:
  - write placeholders as ? and translate to %s for Postgres
  - keep DDL dialect-specific (AUTOINCREMENT vs SERIAL) in init()
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "quantanalyzer.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

DEFAULT_WATCHLIST = [
    t.strip().upper() for t in
    os.getenv("DEFAULT_WATCHLIST", "ADBE,NOW,MSFT,AAPL,GOOGL,META,NVDA,AMD,CRM,ORCL").split(",")
    if t.strip()
]

PAPER_STARTING_CASH = float(os.getenv("PAPER_STARTING_CASH", "100000"))


def _conn():
    if IS_PG:
        import psycopg  # deferred: not installed (or needed) for local SQLite dev
        # Render's postgres:// URLs work with psycopg3 directly.
        return psycopg.connect(DATABASE_URL)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _sql(q: str) -> str:
    """Translate ?-style placeholders for the active backend."""
    return q.replace("?", "%s") if IS_PG else q


def execute(q: str, params: tuple = ()) -> None:
    with _conn() as c:
        c.execute(_sql(q), params)


def query(q: str, params: tuple = ()) -> list[tuple]:
    with _conn() as c:
        cur = c.execute(_sql(q), params)
        return cur.fetchall()


def init() -> None:
    serial_pk = ("id SERIAL PRIMARY KEY" if IS_PG
                 else "id INTEGER PRIMARY KEY AUTOINCREMENT")
    ts_default = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"

    with _conn() as c:
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                added_at {ts_default}
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY,
                cash DOUBLE PRECISION NOT NULL,
                created_at {ts_default}
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS paper_trades (
                {serial_pk},
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                ts {ts_default}
            )
        """)

        existing = {r[0] for r in c.execute(_sql("SELECT ticker FROM watchlist"))}
        if not existing:
            for t in DEFAULT_WATCHLIST:
                c.execute(_sql("INSERT INTO watchlist(ticker) VALUES(?)"), (t,))

        c.execute(f"""
            CREATE TABLE IF NOT EXISTS game_rounds (
                {serial_pk},
                ticker TEXT NOT NULL,
                cutoff_date TEXT NOT NULL,
                fwd_return DOUBLE PRECISION NOT NULL,
                payload TEXT NOT NULL,
                reveal TEXT NOT NULL,
                created_at {ts_default}
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS game_guesses (
                {serial_pk},
                round_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL,
                pnl_pct DOUBLE PRECISION,
                correct INTEGER,
                brier DOUBLE PRECISION,
                ts {ts_default}
            )
        """)

        acct = c.execute(_sql("SELECT id FROM paper_account WHERE id = 1")).fetchone()
        if acct is None:
            c.execute(_sql("INSERT INTO paper_account(id, cash) VALUES(1, ?)"),
                      (PAPER_STARTING_CASH,))


# --- Watchlist (unchanged public API) --------------------------------------

def list_tickers() -> list[str]:
    return [r[0] for r in query("SELECT ticker FROM watchlist ORDER BY ticker")]


def add(ticker: str) -> None:
    t = ticker.upper().strip()
    if IS_PG:
        execute("INSERT INTO watchlist(ticker) VALUES(?) ON CONFLICT DO NOTHING", (t,))
    else:
        execute("INSERT OR IGNORE INTO watchlist(ticker) VALUES(?)", (t,))


def remove(ticker: str) -> None:
    execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper().strip(),))


# --- Paper-trading storage (logic lives in backend/paper.py) ----------------

def paper_cash() -> float:
    rows = query("SELECT cash FROM paper_account WHERE id = 1")
    return float(rows[0][0]) if rows else PAPER_STARTING_CASH


def paper_set_cash(cash: float) -> None:
    execute("UPDATE paper_account SET cash = ? WHERE id = 1", (float(cash),))


def paper_record_trade(ticker: str, side: str, qty: float, price: float) -> None:
    execute("INSERT INTO paper_trades(ticker, side, qty, price) VALUES(?, ?, ?, ?)",
            (ticker.upper().strip(), side, float(qty), float(price)))


def paper_trades() -> list[dict[str, Any]]:
    rows = query("SELECT id, ticker, side, qty, price, ts FROM paper_trades ORDER BY id")
    return [{"id": r[0], "ticker": r[1], "side": r[2],
             "qty": float(r[3]), "price": float(r[4]), "ts": str(r[5])}
            for r in rows]


def paper_reset() -> None:
    execute("DELETE FROM paper_trades")
    paper_set_cash(PAPER_STARTING_CASH)


# --- Game storage (logic lives in backend/game.py) --------------------------

def game_save_round(ticker: str, cutoff_date: str, fwd_return: float,
                    payload: str, reveal: str) -> int:
    with _conn() as c:
        if IS_PG:
            cur = c.execute(_sql(
                "INSERT INTO game_rounds(ticker, cutoff_date, fwd_return, payload, reveal) "
                "VALUES(?, ?, ?, ?, ?) RETURNING id"),
                (ticker, cutoff_date, float(fwd_return), payload, reveal))
            return int(cur.fetchone()[0])
        cur = c.execute(
            "INSERT INTO game_rounds(ticker, cutoff_date, fwd_return, payload, reveal) "
            "VALUES(?, ?, ?, ?, ?)",
            (ticker, cutoff_date, float(fwd_return), payload, reveal))
        return int(cur.lastrowid)


def game_get_round(round_id: int) -> dict | None:
    rows = query("SELECT id, ticker, cutoff_date, fwd_return, payload, reveal "
                 "FROM game_rounds WHERE id = ?", (int(round_id),))
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "ticker": r[1], "cutoff_date": r[2],
            "fwd_return": float(r[3]), "payload": r[4], "reveal": r[5]}


def game_round_answered(round_id: int) -> bool:
    return bool(query("SELECT 1 FROM game_guesses WHERE round_id = ?", (int(round_id),)))


def game_save_guess(round_id: int, direction: str, confidence: float,
                    pnl_pct: float | None, correct: int | None,
                    brier: float | None) -> None:
    execute("INSERT INTO game_guesses(round_id, direction, confidence, pnl_pct, correct, brier) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (int(round_id), direction, float(confidence), pnl_pct, correct, brier))


def game_guesses() -> list[dict]:
    rows = query("SELECT round_id, direction, confidence, pnl_pct, correct, brier "
                 "FROM game_guesses ORDER BY id")
    return [{"round_id": r[0], "direction": r[1], "confidence": float(r[2]),
             "pnl_pct": None if r[3] is None else float(r[3]),
             "correct": None if r[4] is None else int(r[4]),
             "brier": None if r[5] is None else float(r[5])}
            for r in rows]


def game_reset() -> None:
    execute("DELETE FROM game_guesses")
    execute("DELETE FROM game_rounds")
