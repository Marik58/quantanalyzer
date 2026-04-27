"""Smoke test for backend/analysis/quant_score.py (Phase 1 capstone).

This test also implicitly verifies the topology recalibration (Phase 1.9) —
if the topology signal is still pegged at ±1.00 across tickers, the topology
component will look suspicious in the breakdown.

Run:
    python scripts/test_quant_score.py          # defaults to AAPL
    python scripts/test_quant_score.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import quant_score as quant_score_mod    # noqa: E402


VALID_COMPONENTS = {
    "technical", "regime", "valuation", "sentiment",
    "statistics", "spectral", "topology", "risk",
}
VALID_VERDICTS = {"Strong Buy", "Buy", "Hold", "Reduce", "Avoid"}


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Quant Score aggregator smoke test: {ticker} ===\n")
    result = quant_score_mod.compute(ticker)
    payload = quant_score_mod.to_dict(result)

    if payload["error"]:
        print(f"Error: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(-100.0 <= payload["directional_score"] <= 100.0,
           f"directional in [-100,+100] (got {payload['directional_score']:.2f})")
    _check(0.0 <= payload["percentile_score"] <= 100.0,
           f"percentile in [0,100] (got {payload['percentile_score']:.2f})")
    _check(abs(payload["percentile_score"]
               - (payload["directional_score"] + 100.0) / 2.0) < 1e-6,
           "percentile = (directional + 100) / 2")
    _check(payload["verdict"] in VALID_VERDICTS,
           f"verdict valid (got {payload['verdict']!r})")
    _check(0.0 <= payload["confidence"] <= 100.0,
           f"confidence in [0,100] (got {payload['confidence']:.1f})")

    comp_names = {c["name"] for c in payload["components"]}
    _check(comp_names == VALID_COMPONENTS,
           f"all 8 components present (got {sorted(comp_names)})")

    active_w = payload["active_weight"]
    _check(0.0 <= active_w <= 1.0, f"active_weight in [0,1] (got {active_w:.2f})")
    _check(active_w >= 0.5,
           f"at least half the weight voted (got {active_w:.2f})")

    # Per-component checks
    for c in payload["components"]:
        if c["score"] is None:
            _check(c["detail"].startswith("unavailable") or c["detail"] != "",
                   f"missing component has detail note ({c['name']})")
            continue
        _check(-100.0 <= c["score"] <= 100.0,
               f"{c['name']} score in [-100,+100] (got {c['score']:.1f})")
        _check(0.0 <= c["weight"] <= 1.0,
               f"{c['name']} weight in [0,1] (got {c['weight']:.2f})")

    # Weights sum to 1.0
    weight_sum = sum(c["weight"] for c in payload["components"])
    _check(abs(weight_sum - 1.0) < 1e-6,
           f"weights sum to 1.0 (got {weight_sum:.4f})")

    # --- Topology recalibration sanity: signal should NOT peg at +1.00 ---
    topo = next(c for c in payload["components"] if c["name"] == "topology")
    if topo["raw"]:
        topo_signal = topo["raw"].get("signal")
        if topo_signal is not None:
            _check(abs(topo_signal) < 0.9999,
                   f"topology signal NOT pegged at ±1.0 (got {topo_signal:.3f})")

    # --- Human-readable summary ---
    print(f"\nVerdict        : {payload['verdict']}")
    print(f"Directional    : {payload['directional_score']:+7.2f}  "
          f"(percentile {payload['percentile_score']:5.1f}/100)")
    print(f"Confidence     : {payload['confidence']:5.1f}/100")
    print(f"Active weight  : {active_w:.0%}")

    print("\nComponent breakdown:")
    print(f"  {'Component':<11} {'Weight':>7} {'Score':>8} {'Contrib':>9}  Detail")
    print(f"  {'-'*11} {'-'*7} {'-'*8} {'-'*9}  {'-'*40}")
    for c in payload["components"]:
        w = c["weight"]
        s = c["score"]
        if s is None:
            print(f"  {c['name']:<11} {w:>6.0%}  {'n/a':>7}  {'n/a':>8}   {c['detail']}")
        else:
            contrib = s * w
            print(f"  {c['name']:<11} {w:>6.0%}  {s:>+7.1f}  {contrib:>+8.1f}   {c['detail']}")

    if payload["conflicts"]:
        print("\nConflict flags:")
        for f in payload["conflicts"]:
            print(f"  ⚠  {f}")
    else:
        print("\nNo cross-signal conflicts flagged.")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
