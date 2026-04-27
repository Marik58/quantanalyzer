"""Smoke test for backend/analysis/manifold.py.

Run:
    python scripts/test_manifold.py          # defaults to AAPL
    python scripts/test_manifold.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod               # noqa: E402
from backend.analysis import manifold as manifold_mod       # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Manifold smoke test: {ticker} ===\n")
    td = data_mod.load(ticker)
    if td is None:
        print(f"No data for {ticker}.")
        return 1
    h = td.history
    result = manifold_mod.compute(h["Close"], h["High"], h["Low"])
    payload = manifold_mod.to_dict(result)

    if payload["method_error"]:
        print(f"Method error: {payload['method_error']}")
        return 1

    print("Structural checks:")
    _check(payload["n_features"] == 11, f"11 features built (got {payload['n_features']})")
    _check(payload["n_samples"] > 60, f"n_samples > 60 (got {payload['n_samples']})")
    _check(len(payload["components"]) == 3, "3 PCA components returned")

    cum = payload["cumulative_variance_top3"]
    _check(0 < cum <= 1.0, f"cumulative_variance_top3 in (0, 1] (got {cum:.4f})")

    ev_sum_check = sum(c["explained_variance"] for c in payload["components"])
    _check(abs(ev_sum_check - cum) < 1e-6, "component variances sum to cumulative")

    # explained variance should be monotonically non-increasing by PCA convention
    evs = [c["explained_variance"] for c in payload["components"]]
    _check(evs == sorted(evs, reverse=True),
           "PCA components sorted by descending explained variance")

    for c in payload["components"]:
        _check(c["index"] in (1, 2, 3), "component index is 1/2/3")
        _check(c["name"] in
               ("Trend / Directional", "Volatility",
                "Momentum / Mean-Reversion", "Mixed"),
               f"component name valid ({c['name']})")
        _check(len(c["top_loadings"]) == 5, "5 top loadings per component")
        for l in c["top_loadings"]:
            _check(l["feature"] in payload["feature_names"],
                   f"loading feature exists in feature_names ({l['feature']})")
            _check(-1.0 <= l["loading"] <= 1.0,
                   f"loading in [-1, 1] (got {l['loading']})")

    u = payload["umap"]
    if u["available"]:
        _check(u["n_points"] == payload["n_samples"],
               f"UMAP n_points matches n_samples ({u['n_points']} vs {payload['n_samples']})")
        for p in u["points"][:5]:
            _check(isinstance(p["x"], float) and isinstance(p["y"], float),
                   "UMAP point coords are floats")

    # --- human-readable summary ---
    print("\nFeature matrix:")
    print(f"  features: {payload['n_features']}  samples: {payload['n_samples']}")
    print(f"  columns : {payload['feature_names']}")

    print("\nPCA components:")
    print(f"  cumulative variance (top 3): {cum:.1%}")
    for c in payload["components"]:
        print(f"\n  PC{c['index']} -> {c['name']}   "
              f"(explains {c['explained_variance']:.1%})")
        for l in c["top_loadings"]:
            print(f"      {l['feature']:<14} {l['loading']:+.3f}")

    print("\nUMAP:")
    if u["available"]:
        xs = [p["x"] for p in u["points"]]
        ys = [p["y"] for p in u["points"]]
        print(f"  n_points = {u['n_points']}")
        print(f"  x-range  = [{min(xs):.2f}, {max(xs):.2f}]")
        print(f"  y-range  = [{min(ys):.2f}, {max(ys):.2f}]")
        print(f"  first 3  = {[(p['date'], round(p['x'],2), round(p['y'],2)) for p in u['points'][:3]]}")
    else:
        print(f"  unavailable: {u['error']}")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
