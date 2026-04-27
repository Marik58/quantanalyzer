"""Smoke test for backend/analysis/statistics.py.

Run from the project root:

    python -m scripts.test_statistics

or

    python scripts/test_statistics.py

Pulls AAPL + SPY via the existing data module, runs the full advanced stats
pipeline, and prints a readable summary. Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/test_statistics.py)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod      # noqa: E402
from backend.analysis import statistics as stats_mod  # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL", bench: str = "SPY") -> int:
    print(f"\n=== Advanced statistics smoke test: {ticker} vs {bench} ===\n")

    td = data_mod.load(ticker)
    if td is None:
        print(f"No data for {ticker} — is the network up?")
        return 1
    bench_td = data_mod.load(bench)
    bench_close = bench_td.history["Close"] if bench_td else None

    result = stats_mod.compute(td.history["Close"], bench_close)
    payload = stats_mod.to_dict(result)

    # --- structural checks ---
    print("Structural checks:")
    _check("student_t" in payload, "student_t block present")
    _check("downside" in payload, "downside block present")
    _check("copula" in payload, "copula block present (may be None)")
    _check("explanations" in payload, "explanations block present")
    _check(isinstance(payload["student_t"]["df"], (int, float)),
           "Student-t df is numeric")
    _check(payload["student_t"]["df"] > 0, "Student-t df is positive")
    _check(payload["downside"]["cvar_95"] <= 0,
           "CVaR 95% is non-positive (it's a loss)")
    _check(payload["downside"]["cvar_99"] <= payload["downside"]["cvar_95"],
           "CVaR 99% is at least as bad as CVaR 95%")
    if payload["copula"]:
        _check(-1 <= payload["copula"]["pearson"] <= 1,
               "Pearson correlation in [-1, 1]")
        _check(-1 <= payload["copula"]["kendall_tau"] <= 1,
               "Kendall tau in [-1, 1]")
        _check(0 <= payload["copula"]["lower_tail_dep"] <= 1,
               "Lower tail dependence in [0, 1]")
        _check(0 <= payload["copula"]["upper_tail_dep"] <= 1,
               "Upper tail dependence in [0, 1]")

    # --- human-readable summary ---
    print("\nStudent-t fit:")
    t = payload["student_t"]
    print(f"  df = {t['df']:.2f}   (tail severity: {t['tail_severity']})")

    print("\nDownside metrics:")
    d = payload["downside"]
    print(f"  CVaR 95%     : {d['cvar_95']:.4f}    "
          f"(~{d['cvar_95']*100:.2f}% avg loss on worst 5% of days)")
    print(f"  CVaR 99%     : {d['cvar_99']:.4f}    "
          f"(~{d['cvar_99']*100:.2f}% avg loss on worst 1% of days)")
    print(f"  Sortino (ann): {d['sortino_annual']:.2f}")
    print(f"  Calmar       : {d['calmar']}")
    print(f"  Omega (>0)   : {d['omega_ratio']}")

    if payload["copula"]:
        c = payload["copula"]
        print("\nCopula vs SPY:")
        print(f"  Pearson         : {c['pearson']:+.3f}")
        print(f"  Kendall tau     : {c['kendall_tau']:+.3f}")
        print(f"  Lower tail dep  : {c['lower_tail_dep']:.3f}   (joint-crash probability)")
        print(f"  Upper tail dep  : {c['upper_tail_dep']:.3f}   (joint-rally probability)")
        print(f"  Overlap days    : {c['overlap_days']}")
    else:
        print("\nCopula vs SPY: (not computed — insufficient overlap)")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\nFull JSON payload (for API shape reference):")
    print(json.dumps(payload, indent=2, default=str)[:1500] + "\n...\n")

    print("=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
