"""Smoke test for the existing /api/watchlist/scan endpoint (Phase 2A.2).

Calls the scan_watchlist FastAPI handler directly (in-process, no HTTP) so it
works without the server running.

Run:
    python scripts/test_watchlist_scan.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import db                               # noqa: E402
from backend.main import scan_watchlist              # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run() -> int:
    print("\n=== Watchlist scan smoke test ===\n")

    db.init()
    tickers = db.list_tickers()
    print(f"Watchlist has {len(tickers)} tickers: {', '.join(tickers)}\n")

    t0 = time.time()
    payload = asyncio.run(scan_watchlist())
    elapsed = time.time() - t0
    print(f"Scan completed in {elapsed:.1f}s\n")

    print("Structural checks:")
    _check("results" in payload, "payload has 'results' key")
    _check(isinstance(payload["results"], list), "results is a list")
    _check(len(payload["results"]) >= max(1, len(tickers) - 4),
           f"got at least {max(1, len(tickers) - 4)} results "
           f"(allowing up to 4 yfinance failures); got {len(payload['results'])}")

    # Verify required fields per row
    required_fields = {"ticker", "name", "last_price", "action",
                       "composite", "confidence", "opportunity", "risk", "regime",
                       "quant_score"}
    for row in payload["results"]:
        missing = required_fields - row.keys()
        _check(not missing, f"{row.get('ticker', '?')}: all required fields present "
                            f"(missing: {missing})")

    # At least half the rows should have a non-None quant_score (allows yfinance failures)
    qs_present = sum(1 for r in payload["results"] if r.get("quant_score") is not None)
    _check(qs_present >= max(1, len(payload["results"]) // 2),
           f"quant_score populated for at least half of rows "
           f"({qs_present}/{len(payload['results'])})")

    # Verify sorted by opportunity descending
    opps = [r["opportunity"] for r in payload["results"]]
    _check(opps == sorted(opps, reverse=True),
           "results sorted by opportunity descending")

    # ----- Human-readable ranked table -----
    print("\nRanked scan results:\n")
    print(f"  {'Rank':>4}  {'Ticker':<6}  {'Price':>10}  {'Action':<12}  "
          f"{'Opp':>5}  {'Risk':<8}  {'Regime':<14}  {'QS%':>5}  {'QS verdict':<14}  Name")
    print("  " + "-" * 130)
    for i, r in enumerate(payload["results"], start=1):
        name = (r.get("name") or "")[:24]
        price = r.get("last_price")
        price_txt = f"${price:,.2f}" if isinstance(price, (int, float)) else "—"
        qs = r.get("quant_score")
        qs_pct = f"{qs['percentile']:>5.0f}" if qs and qs.get("percentile") is not None else "  —  "
        qs_verdict = (qs.get("verdict") or "—") if qs else "—"
        print(f"  {i:>4}  {r['ticker']:<6}  {price_txt:>10}  "
              f"{r['action']:<12}  {r['opportunity']:>5.0f}  "
              f"{r['risk']:<8}  {r['regime']:<14}  {qs_pct}  {qs_verdict:<14}  {name}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(run())
