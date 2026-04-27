"""Smoke test for backend/analysis/catalyst.py (Phase 2A.1).

Run:
    python scripts/test_catalyst.py            # defaults to AAPL
    python scripts/test_catalyst.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import catalyst as catalyst_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Catalyst tracker smoke test: {ticker} ===\n")
    result = catalyst_mod.compute(ticker)
    payload = catalyst_mod.to_dict(result)

    if payload["error"]:
        print(f"ERROR: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(payload["ticker"] == ticker.upper(), f"ticker echoed correctly")
    _check("explanations" in payload, "explanations dict present")
    _check(isinstance(payload["rating_changes_30d"], list), "rating_changes is a list")

    # At least 3 of the 6 fields should be populated for a major name like AAPL
    fields = [
        payload["earnings"],
        payload["dividend"],
        payload["analyst_targets"],
        payload["rating_changes_30d"] or None,  # empty list counts as missing
        payload["short_interest_pct_float"],
        payload["insider_ownership_pct"],
    ]
    populated = sum(1 for f in fields if f is not None)
    _check(populated >= 3, f"at least 3 of 6 catalyst fields populated (got {populated}/6)")

    # Explanations should exist for every key
    for k in ("earnings", "dividend", "analyst_targets", "rating_changes_30d",
              "short_interest", "insider_ownership"):
        _check(k in payload["explanations"] and len(payload["explanations"][k]) > 0,
               f"explanation '{k}' present and non-empty")

    # ----- Human-readable dump -----
    print("\nEarnings:")
    if payload["earnings"]:
        e = payload["earnings"]
        print(f"  next_date    : {e.get('next_date')}")
        print(f"  eps_estimate : {e.get('eps_estimate')}")
        print(f"  days_until   : {e.get('days_until')}")
    else:
        print("  (none)")

    print("\nDividend:")
    if payload["dividend"]:
        d = payload["dividend"]
        print(f"  ex_date    : {d.get('ex_date')}")
        print(f"  amount     : {d.get('amount')}")
        print(f"  yield_pct  : {d.get('yield_pct')}")
        print(f"  days_until : {d.get('days_until')}")
    else:
        print("  (none)")

    print("\nAnalyst targets:")
    if payload["analyst_targets"]:
        a = payload["analyst_targets"]
        print(f"  current : {a.get('current')}")
        print(f"  low     : {a.get('low')}")
        print(f"  median  : {a.get('median')}")
        print(f"  high    : {a.get('high')}")
        ups = a.get("upside_to_median_pct")
        print(f"  upside  : {ups * 100:+.1f}%" if ups is not None else "  upside  : n/a")
        print(f"  n       : {a.get('n_analysts')}")
    else:
        print("  (none)")

    print(f"\nRating changes (last 30 days): {len(payload['rating_changes_30d'])}")
    for r in payload["rating_changes_30d"][:5]:
        print(f"  {r['date']}  {r['firm']:<25} {r['from']:>10} -> {r['to']:<10}  ({r['action']})")

    print(f"\nShort interest % float : {payload['short_interest_pct_float']}")
    print(f"Insider ownership %    : {payload['insider_ownership_pct']}")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
