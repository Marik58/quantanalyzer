"""Smoke test for backend/analysis/speaker_prep.py (Phase 2B.4).

Run:
    python scripts/test_speaker_prep.py            # defaults to AAPL
    python scripts/test_speaker_prep.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import speaker_prep as sp_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Speaker prep smoke test: {ticker} ===\n")
    result = sp_mod.compute(ticker)
    payload = sp_mod.to_dict(result)

    if payload["error"]:
        print(f"ERROR: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(payload["ticker"] == ticker.upper(), "ticker echoed correctly")
    _check(len(payload["questions"]) == 5,
           f"exactly 5 questions returned (got {len(payload['questions'])})")
    for i, q in enumerate(payload["questions"], start=1):
        _check(isinstance(q.get("question"), str) and len(q["question"]) >= 30,
               f"question {i}: present and >= 30 chars")
        _check(isinstance(q.get("why_it_matters"), str) and len(q["why_it_matters"]) >= 30,
               f"question {i}: why_it_matters present and >= 30 chars")

    print(f"\nTriggers fired: {', '.join(payload['triggers_fired'])}")

    print("\n" + "=" * 78)
    print(f"SPEAKER PREP / Q&A PACK — {payload['ticker']}")
    print("=" * 78)
    for i, q in enumerate(payload["questions"], start=1):
        print(f"\nQ{i}. {q['question']}")
        print(f"    Why it matters: {q['why_it_matters']}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
