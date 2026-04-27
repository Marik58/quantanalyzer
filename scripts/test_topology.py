"""Smoke test for backend/analysis/topology.py.

Run:
    python scripts/test_topology.py          # defaults to AAPL
    python scripts/test_topology.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod             # noqa: E402
from backend.analysis import topology as topology_mod     # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Topology smoke test: {ticker} ===\n")
    td = data_mod.load(ticker)
    if td is None:
        print(f"No data for {ticker}.")
        return 1

    result = topology_mod.compute(td.history["Close"])
    payload = topology_mod.to_dict(result)

    print(f"Method: {payload['method']}")
    if payload["error"]:
        print(f"Error: {payload['error']}")
        return 1

    print("\nStructural checks:")
    _check(payload["method"] == "ripser", "ripser is the active method")
    _check(payload["n_points"] > 20, f"n_points > 20 (got {payload['n_points']})")
    _check(payload["embedding_dim"] == 3, "embedding_dim = 3")
    _check(payload["scale"] > 0, "pairwise-distance scale > 0")
    _check(-1.0 <= payload["topological_signal"] <= 1.0,
           "topological_signal in [-1, 1]")
    _check(payload["betti"]["b0_count"] >= 0, "B0 count >= 0")
    _check(payload["betti"]["b1_count"] >= 0, "B1 count >= 0")
    _check(payload["betti"]["b0_total_persistence"] >= 0,
           "B0 total persistence >= 0")
    _check(payload["betti"]["b1_total_persistence"] >= 0,
           "B1 total persistence >= 0")
    for p in payload["betti"]["top_pairs"]:
        _check(p["death"] >= p["birth"],
               f"persistence pair death >= birth (got birth={p['birth']}, death={p['death']})")
        _check(abs(p["persistence"] - (p["death"] - p["birth"])) < 1e-6,
               "persistence == death - birth")

    # Mapper may legitimately be unavailable — check shape regardless
    m = payload["mapper"]
    if m["available"]:
        _check(m["n_nodes"] == len(m["nodes"]),
               "mapper n_nodes matches node list length")
        _check(m["n_edges"] == len(m["edges"]),
               "mapper n_edges matches edge list length")
        node_ids = {n["id"] for n in m["nodes"]}
        for e in m["edges"][:25]:
            _check(e["source"] in node_ids and e["target"] in node_ids,
                   f"edge endpoints exist in node list ({e})")

    # --- human-readable summary ---
    print("\nEmbedding:")
    print(f"  dim = {payload['embedding_dim']}, tau = {payload['tau']}, "
          f"n_points = {payload['n_points']}, scale = {payload['scale']:.4f}")

    print("\nBetti summary:")
    b = payload["betti"]
    print(f"  B_0 count (clusters)  : {b['b0_count']}")
    print(f"  B_0 total persistence : {b['b0_total_persistence']:.4f}")
    print(f"  B_1 count (loops)     : {b['b1_count']}")
    print(f"  B_1 total persistence : {b['b1_total_persistence']:.4f}")
    print(f"  normalized B_1/scale  : "
          f"{b['b1_total_persistence']/payload['scale']:.3f}")

    print("\n  Top persistence pairs:")
    for p in b["top_pairs"]:
        print(f"    dim={p['dim']}  birth={p['birth']:.4f}  death={p['death']:.4f}  "
              f"persistence={p['persistence']:.4f}")

    print("\nTopological signal:")
    print(f"  score = {payload['topological_signal']:+.2f}   label = {payload['signal_label']}")

    print("\nMapper graph:")
    if m["available"]:
        print(f"  nodes = {m['n_nodes']}   edges = {m['n_edges']}")
        sizes = sorted((n["size"] for n in m["nodes"]), reverse=True)[:5]
        if sizes:
            print(f"  largest node sizes: {sizes}")
    else:
        print(f"  unavailable: {m['error']}")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
