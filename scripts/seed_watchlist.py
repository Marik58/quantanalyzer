"""One-time helper to ensure all 14 default-watchlist tickers are in the DB.

Adds AVGO, AMAT, SNPS, CDNS (and any others from the canonical list) if
they aren't already present. Safe to run repeatedly — uses INSERT OR IGNORE.

Run:
    python scripts/seed_watchlist.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import db   # noqa: E402

CANONICAL = ["ADBE", "NOW", "CRM", "ORCL", "MSFT", "GOOGL", "NVDA",
             "AMD", "AAPL", "META", "AVGO", "AMAT", "SNPS", "CDNS"]


def run() -> int:
    db.init()
    before = set(db.list_tickers())
    print(f"Before: {len(before)} tickers — {', '.join(sorted(before))}")

    added = []
    for t in CANONICAL:
        if t not in before:
            db.add(t)
            added.append(t)

    after = db.list_tickers()
    print(f"\nAfter:  {len(after)} tickers — {', '.join(sorted(after))}")
    if added:
        print(f"\nAdded:  {', '.join(added)}")
    else:
        print("\nNothing to add — all canonical tickers already present.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
