"""Smoke test for backend/analysis/pitch_deck.py (Phase 2C.6).

Run:
    python scripts/test_pitch_deck.py            # defaults to AAPL
    python scripts/test_pitch_deck.py NVDA
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import pitch_deck as pd_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Pitch deck PDF smoke test: {ticker} ===\n")
    result = pd_mod.compute(ticker)
    payload = pd_mod.to_dict(result)

    if payload["error"]:
        print(f"ERROR: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(payload["ticker"] == ticker.upper(), "ticker echoed correctly")
    _check(payload["pdf_path"] is not None, "pdf_path returned")

    p = Path(payload["pdf_path"])
    _check(p.exists(), f"PDF file exists at {p}")

    # Magic-header check first — proves it's a real PDF, not a truncated write
    with open(p, "rb") as f:
        header = f.read(5)
    _check(header == b"%PDF-", f"file has PDF magic header (got {header!r})")

    size = p.stat().st_size
    _check(size > 5_000, f"PDF file is > 5KB (got {size:,} bytes)")

    print(f"\nPDF written to: {p}")
    print(f"Size: {size:,} bytes")
    print(f"\nOpen it manually to confirm it looks right:")
    print(f"  Windows: start \"\" \"{p}\"")
    print(f"  or just double-click in File Explorer")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
