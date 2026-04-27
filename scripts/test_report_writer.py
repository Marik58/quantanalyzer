"""Smoke test for backend/analysis/report_writer.py (Phase 2C.5).

Run:
    python scripts/test_report_writer.py            # defaults to AAPL
    python scripts/test_report_writer.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

# Force UTF-8 on stdout so non-ASCII chars (→, ★, —) survive a `>` redirect on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import report_writer as rw_mod   # noqa: E402

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Company Overview",
    "Quantitative Analysis",
    "Valuation",
    "Catalyst Review",
    "Risk Analysis",
    "Bull / Base / Bear Scenarios",
    "Conclusion",
    "Appendix — Speaker Prep Q&A",
]


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Report writer smoke test: {ticker} ===\n")
    result = rw_mod.compute(ticker)
    payload = rw_mod.to_dict(result)

    if payload["error"]:
        print(f"ERROR: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(payload["ticker"] == ticker.upper(), "ticker echoed correctly")
    _check(payload["word_count"] >= 300,
           f"report has at least 300 words (got {payload['word_count']})")

    md = payload["report_markdown"]
    _check(md.startswith(f"# {ticker.upper()}"), "report starts with H1 ticker header")

    for section in EXPECTED_SECTIONS:
        _check(f"## {section}" in md, f"section '## {section}' present")

    _check(len(payload["sections"]) == 9,
           f"sections list has 9 entries (got {len(payload['sections'])})")

    # ----- Print the full report -----
    print(f"\nWord count: {payload['word_count']}")
    print(f"Sections found: {payload['sections']}\n")
    print("=" * 78)
    print(md)
    print("=" * 78)

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
