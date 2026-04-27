"""Smoke test for backend/analysis/risk_framework.py.

Run:
    python scripts/test_risk_framework.py          # defaults to AAPL
    python scripts/test_risk_framework.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import risk_framework as risk_fw_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Risk framework smoke test: {ticker} ===\n")
    result = risk_fw_mod.compute(ticker)
    payload = risk_fw_mod.to_dict(result)

    if payload["error"]:
        print(f"Error: {payload['error']}")
        return 1

    print("Structural checks:")
    _check(payload["n_observations"] > 500,
           f"n_observations > 500 (got {payload['n_observations']})")
    _check(payload["beta_vs_spy"] is not None, "beta vs SPY computed")
    _check(len(payload["stress_scenarios"]) == 5, "5 stress scenarios")
    _check(len(payload["macro_correlations"]) == 5, "5 macro correlations")

    # per-scenario checks
    for s in payload["stress_scenarios"]:
        _check(s["method"] in ("historical", "beta_estimated", "na"),
               f"scenario method valid ({s['name']}: {s['method']})")
        if s["estimated_impact"] is not None:
            _check(-1.0 <= s["estimated_impact"] <= 0.5,
                   f"impact in reasonable range ({s['name']}: {s['estimated_impact']:.2%})")

    # macro correlations
    for m in payload["macro_correlations"]:
        if m["correlation_1y"] is not None:
            _check(-1.0 <= m["correlation_1y"] <= 1.0,
                   f"{m['asset']} corr in [-1,1] (got {m['correlation_1y']:.3f})")

    # drawdown
    dd = payload["drawdown"]
    _check(dd["max_drawdown"] <= 0, f"max_drawdown <= 0 (got {dd['max_drawdown']:.2%})")
    _check(dd["current_drawdown"] <= 0,
           f"current_drawdown <= 0 (got {dd['current_drawdown']:.2%})")
    _check(dd["max_drawdown_duration_days"] >= 0, "max DD duration non-negative")

    # tail risk
    tr = payload["tail_risk"]
    _check(tr["var_99_historical"] <= tr["var_95_historical"] <= 0,
           "VaR 99 ≤ VaR 95 ≤ 0")
    _check(tr["cvar_99"] <= tr["var_99_historical"],
           f"CVaR 99 ≤ VaR 99 (got {tr['cvar_99']:.3%} vs {tr['var_99_historical']:.3%})")
    _check(tr["student_t_df"] >= 0, f"student-t df >= 0 (got {tr['student_t_df']:.1f})")

    # kelly
    k = payload["kelly"]
    _check(0.0 <= k["win_rate"] <= 1.0, f"win_rate in [0,1] (got {k['win_rate']:.3f})")
    _check(-1.0 <= k["kelly_fraction"] <= 1.0,
           f"kelly in [-1,1] (got {k['kelly_fraction']:.3f})")
    _check(abs(k["half_kelly"] - k["kelly_fraction"] / 2.0) < 1e-9,
           "half_kelly = kelly / 2")

    # composite score
    s = payload["overall_risk_score"]
    _check(0.0 <= s <= 100.0, f"overall_risk_score in [0,100] (got {s:.1f})")
    _check(payload["overall_risk_label"] in ("Low", "Moderate", "High", "Extreme", "n/a"),
           f"risk label valid (got {payload['overall_risk_label']!r})")

    # --- human-readable summary ---
    print(f"\nObservations: {payload['n_observations']}   "
          f"β vs SPY: {payload['beta_vs_spy']:+.2f}")
    print(f"Overall risk: {payload['overall_risk_score']:.1f}/100   "
          f"→ {payload['overall_risk_label']}")

    print("\nStress scenarios:")
    print(f"  {'Scenario':<26} {'Period':<28} {'Market':>10} {'Impact':>10}  Method")
    for sc in payload["stress_scenarios"]:
        mkt = f"{sc['market_drawdown']:.1%}" if sc["market_drawdown"] is not None else "n/a"
        imp = f"{sc['estimated_impact']:.1%}" if sc["estimated_impact"] is not None else "n/a"
        print(f"  {sc['name']:<26} {sc['period']:<28} {mkt:>10} {imp:>10}  {sc['method']}")

    print("\nMacro correlations (1-year):")
    for m in payload["macro_correlations"]:
        c = f"{m['correlation_1y']:+.2f}" if m["correlation_1y"] is not None else "n/a "
        print(f"  {m['asset']:<4} {m['label']:<26} {c}   {m['interpretation']}")

    print("\nDrawdown profile:")
    print(f"  max DD       : {dd['max_drawdown']:+.1%}   "
          f"({dd['max_drawdown_start']} → {dd['max_drawdown_trough']})")
    print(f"  current DD   : {dd['current_drawdown']:+.1%}   (from 1-year high)")
    print(f"  worst 3-month: {dd['worst_3m']:+.1%}")
    print(f"  worst 6-month: {dd['worst_6m']:+.1%}")
    print(f"  longest DD   : {dd['max_drawdown_duration_days']} trading days below prior peak")

    print("\nTail risk:")
    print(f"  VaR 95%  (historical): {tr['var_95_historical']:+.2%}")
    print(f"  VaR 99%  (historical): {tr['var_99_historical']:+.2%}")
    print(f"  CVaR 95%             : {tr['cvar_95']:+.2%}")
    print(f"  CVaR 99%             : {tr['cvar_99']:+.2%}")
    print(f"  VaR 95%  (Student-t) : {tr['var_95_student_t']:+.2%}")
    print(f"  VaR 99%  (Student-t) : {tr['var_99_student_t']:+.2%}")
    print(f"  Student-t df         : {tr['student_t_df']:.1f}")

    print("\nKelly Criterion:")
    print(f"  win rate        : {k['win_rate']:.1%}")
    print(f"  avg win         : {k['avg_win']:+.3%}")
    print(f"  avg loss        : {k['avg_loss']:+.3%}")
    if k["win_loss_ratio"] is not None:
        print(f"  win/loss ratio  : {k['win_loss_ratio']:.2f}")
    print(f"  full Kelly      : {k['kelly_fraction']:+.1%}")
    print(f"  half Kelly      : {k['half_kelly']:+.1%}")

    print("\nPlain-English explanations:")
    for kname, v in payload["explanations"].items():
        print(f"\n  [{kname}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
