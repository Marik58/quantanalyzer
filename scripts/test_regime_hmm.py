"""Smoke test for backend/analysis/regime_hmm.py.

Run:
    python scripts/test_regime_hmm.py          # defaults to AAPL
    python scripts/test_regime_hmm.py NVDA
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod                # noqa: E402
from backend.analysis import regime_hmm as regime_hmm_mod    # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== HMM regime smoke test: {ticker} ===\n")
    td = data_mod.load(ticker)
    if td is None:
        print(f"No data for {ticker}.")
        return 1

    result = regime_hmm_mod.compute(td.history["Close"])
    payload = regime_hmm_mod.to_dict(result)

    print(f"Model used: {payload['method']}")
    if payload["error"]:
        print(f"Note: {payload['error']}")

    print("\nStructural checks:")
    _check(payload["method"] in ("HMM", "GMM", "unavailable"),
           "method is one of HMM/GMM/unavailable")
    if payload["method"] == "unavailable":
        print("\nRegime model is unavailable. Check dep install and re-run.")
        return 1

    _check(payload["current_regime"] in ("Bull", "Bear", "Sideways", "Volatile"),
           f"current_regime is a valid label (got {payload['current_regime']!r})")
    _check(0.0 <= payload["current_confidence"] <= 1.0,
           "current_confidence in [0, 1]")
    _check(len(payload["states"]) == 4, "exactly 4 states returned")
    labels_seen = sorted(s["label"] for s in payload["states"])
    _check(labels_seen == ["Bear", "Bull", "Sideways", "Volatile"],
           f"all four labels uniquely assigned (got {labels_seen})")
    probs_sum = sum(s["current_prob"] for s in payload["states"])
    _check(abs(probs_sum - 1.0) < 1e-6, f"state probabilities sum to 1 (got {probs_sum:.6f})")

    if payload["method"] == "HMM":
        _check(len(payload["transitions"]) == 4, "4 transition rows")
        for row in payload["transitions"]:
            row_sum = sum(row["probabilities"].values())
            _check(abs(row_sum - 1.0) < 1e-6,
                   f"transition row from {row['from_regime']} sums to 1 (got {row_sum:.6f})")

    _check(len(payload["timeline"]) > 50, "timeline has more than 50 points")
    for p in payload["timeline"][:5]:
        _check(0.0 <= p["confidence"] <= 1.0,
               f"timeline confidence in [0,1] (got {p['confidence']})")

    # --- human-readable output ---
    print("\nCurrent regime:")
    print(f"  {payload['current_regime']} @ {payload['current_confidence']:.0%} confidence")

    print("\nState centers (annualized):")
    print(f"  {'regime':<10} {'ret':>8} {'vol':>8} {'P(now)':>8}")
    for s in payload["states"]:
        print(f"  {s['label']:<10} {s['mean_return_ann']:>+7.1%} "
              f"{s['mean_vol_ann']:>7.1%} {s['current_prob']:>7.1%}")

    if payload["method"] == "HMM":
        print("\nTransition matrix (rows = from, cols = to):")
        header = "          " + "".join(f"{lab:>10}" for lab in
                                        ("Bull", "Bear", "Sideways", "Volatile"))
        print(header)
        for row in payload["transitions"]:
            cells = "".join(
                f"{row['probabilities'].get(lab, 0.0):>10.1%}"
                for lab in ("Bull", "Bear", "Sideways", "Volatile")
            )
            print(f"  {row['from_regime']:<8}{cells}")

    print("\nHistorical regime distribution (last 2y):")
    counts = Counter(p["regime"] for p in payload["timeline"])
    total = sum(counts.values())
    for lab, cnt in counts.most_common():
        print(f"  {lab:<10} {cnt:>4} days   {cnt/total:>5.1%}")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
