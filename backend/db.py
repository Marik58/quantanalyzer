"""SQLite persistence for the user's watchlist."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "quantanalyzer.db"
DEFAULT_WATCHLIST = [
    t.strip().upper() for t in
    os.getenv("DEFAULT_WATCHLIST", "ADBE,NOW,MSFT,AAPL,GOOGL,META,NVDA,AMD,CRM,ORCL").split(",")
    if t.strip()
]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing = {r[0] for r in c.execute("SELECT ticker FROM watchlist")}
        if not existing:
            c.executemany("INSERT INTO watchlist(ticker) VALUES(?)",
                          [(t,) for t in DEFAULT_WATCHLIST])


def list_tickers() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT ticker FROM watchlist ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def add(ticker: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO watchlist(ticker) VALUES(?)", (ticker.upper().strip(),))


def remove(ticker: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper().strip(),))
