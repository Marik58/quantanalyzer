"""Smoke test for backend/analysis/thesis.py (Phase 2B.3).

Run:
    python scripts/test_thesis.py            # defaults to AAPL
    python scripts/test_thesis.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import thesis as thesis_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Thesis generator smoke test: {ticker} ===\n")
    result = thesis_mod.compute(ticker)
    payload = thesis_mod.to_dict(result)

    if payload["error"]:
        print(f"ERROR: {payload['error']}")
        print(f"Input status: {payload['inputs_status']}")
        return 1

    print("Input modules used:")
    for k, v in payload["inputs_status"].items():
        marker = "OK " if v == "ok" else "skip"
        print(f"  [{marker}] {k}: {v}")

    print("\nStructural checks:")
    _check(payload["ticker"] == ticker.upper(), "ticker echoed correctly")
    for section in ("company_overview", "edge", "catalysts", "valuation_summary", "risks"):
        _check(isinstance(payload[section], str) and len(payload[section]) >= 50,
               f"section '{section}' is non-empty (>= 50 chars), got {len(payload[section])}")

    _check(isinstance(payload["scenarios"], dict), "scenarios is a dict")
    for name in ("bull", "base", "bear"):
        _check(name in payload["scenarios"] and len(payload["scenarios"][name]) >= 30,
               f"scenario '{name}' present and non-empty")

    rec = payload["recommendation"]
    _check(rec.get("action") in ("Buy", "Hold", "Sell"),
           f"recommendation action is Buy/Hold/Sell (got '{rec.get('action')}')")
    _check(rec.get("conviction") in ("High", "Medium", "Low"),
           f"recommendation conviction is High/Medium/Low (got '{rec.get('conviction')}')")
    _check(isinstance(rec.get("rationale"), str) and len(rec["rationale"]) >= 30,
           "recommendation rationale present")

    # ----- Human-readable thesis dump -----
    print("\n" + "=" * 78)
    print(f"INVESTMENT THESIS — {payload['ticker']}")
    print("=" * 78)

    print("\n## Company Overview")
    print(payload["company_overview"])

    print("\n## The Edge")
    print(payload["edge"])

    print("\n## Catalysts")
    print(payload["catalysts"])

    print("\n## Valuation")
    print(payload["valuation_summary"])

    print("\n## Scenarios")
    for name in ("bull", "base", "bear"):
        print(f"\n  [{name.upper()}]")
        print(f"  {payload['scenarios'][name]}")

    print("\n## Risks")
    print(payload["risks"])

    print("\n## Recommendation")
    print(f"  Action     : {rec['action']}")
    print(f"  Conviction : {rec['conviction']}")
    print(f"  Rationale  : {rec['rationale']}")

    drv = payload.get("drivers", {})
    print("\n## Drivers — what's pulling the score up vs down")
    if not drv.get("available"):
        print(f"  {drv.get('summary', 'unavailable')}")
    else:
        print(f"\n  {drv['summary']}\n")
        print(f"  {'Component':<12} {'Score':>7} {'Weight':>7} {'Contribution':>13}  Detail")
        print("  " + "-" * 92)
        for r in drv["positive"]:
            print(f"  {r['name']:<12} {r['score']:>+7.1f} {r['weight']:>7.2f} "
                  f"{r['contribution']:>+13.1f}  {r['detail'][:48]}")
        for r in drv["negative"]:
            print(f"  {r['name']:<12} {r['score']:>+7.1f} {r['weight']:>7.2f} "
                  f"{r['contribution']:>+13.1f}  {r['detail'][:48]}")
        for r in drv["neutral_or_missing"]:
            score_txt = f"{r['score']:>+7.1f}" if r["score"] is not None else "    n/a"
            print(f"  {r['name']:<12} {score_txt} {r['weight']:>7.2f} "
                  f"{r['contribution']:>+13.1f}  {r['detail'][:48]}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
