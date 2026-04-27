"""Smoke test for backend/analysis/peers.py.

Run:
    python scripts/test_peers.py          # defaults to AAPL
    python scripts/test_peers.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import peers as peers_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Peer comparison smoke test: {ticker} ===\n")
    result = peers_mod.compute(ticker)
    payload = peers_mod.to_dict(result)

    if payload["status_note"] and payload["target_row"] is None:
        print(f"Status: {payload['status_note']}")
        return 1

    print("Structural checks:")
    _check(payload["group"] is not None, f"peer group resolved (got {payload['group']!r})")
    _check(len(payload["peers_used"]) >= 2,
           f"at least 2 peers (got {len(payload['peers_used'])})")
    _check(payload["target_row"] is not None, "target row built")
    _check(payload["target_row"]["ticker"] == ticker.upper(),
           "target ticker matches input")

    expected_metric_ids = {"pe", "ps", "ev_ebitda", "rev_grow", "gross_m", "mom_6m"}
    target_metric_ids = set(payload["target_row"]["metrics"].keys())
    _check(target_metric_ids == expected_metric_ids,
           f"all 6 metrics present (got {sorted(target_metric_ids)})")

    # ranks/percentiles consistency
    all_rows = [payload["target_row"]] + payload["peer_rows"]
    for metric_id in expected_metric_ids:
        valid = [r for r in all_rows if r["metrics"][metric_id]["value"] is not None]
        if not valid:
            continue
        ranks = [r["metrics"][metric_id]["rank"] for r in valid]
        _check(sorted(ranks) == list(range(1, len(valid) + 1)),
               f"ranks dense & unique for {metric_id} ({ranks})")
        for r in valid:
            mv = r["metrics"][metric_id]
            _check(0.0 <= mv["percentile"] <= 100.0,
                   f"{r['ticker']} {metric_id} percentile in [0,100] "
                   f"(got {mv['percentile']:.1f})")
            _check(mv["status"] in ("best", "mid", "worst"),
                   f"{r['ticker']} {metric_id} status valid ({mv['status']})")

    # relative value score bounds
    s = payload["relative_value_score"]
    if s is not None:
        _check(0.0 <= s <= 100.0, f"relative_value_score in [0,100] (got {s:.1f})")
        _check(payload["relative_value_label"] in
               ("cheap / attractive", "fair", "expensive / weak", "n/a"),
               f"relative_value_label valid (got {payload['relative_value_label']!r})")

    # --- human-readable summary ---
    tgt = payload["target_row"]
    print(f"\nTarget : {tgt['ticker']}  ({tgt['name']})")
    print(f"Group  : {payload['group']}")
    print(f"Peers  : {', '.join(payload['peers_used'])}")
    print(f"Score  : {'n/a' if s is None else f'{s:.1f}/100'}  "
          f"→ {payload['relative_value_label']}")

    print("\nMetric table (best rank = 1 within peer set):")
    labels = payload["metric_labels"]
    order = payload["metric_order"]
    header = f"  {'Ticker':<7}  " + "  ".join(f"{labels[m]:<16}" for m in order)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in all_rows:
        cells = []
        for m in order:
            mv = r["metrics"][m]
            v = mv["value"]
            if v is None:
                cell = "n/a"
            elif m in ("rev_grow", "gross_m", "mom_6m"):
                cell = f"{v*100:+.1f}%"
            else:
                cell = f"{v:.2f}"
            rk = "" if mv["rank"] is None else f" (#{mv['rank']})"
            cells.append(f"{cell+rk:<16}")
        marker = "*" if r["ticker"] == tgt["ticker"] else " "
        print(f" {marker}{r['ticker']:<7}  " + "  ".join(cells))

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
