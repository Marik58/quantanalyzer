"""Smoke test for backend/analysis/valuation.py (Phase 2.1 DCF).

Run:
    python scripts/test_valuation.py          # defaults to AAPL
    python scripts/test_valuation.py NVDA
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import valuation as valuation_mod     # noqa: E402

SCENARIOS = {"Bear", "Base", "Bull"}


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _fmt_money(v: float) -> str:
    if abs(v) >= 1e12:
        return f"${v/1e12:,.2f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:,.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:,.2f}M"
    return f"${v:,.2f}"


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== DCF valuation smoke test: {ticker} ===\n")
    result = valuation_mod.compute(ticker)
    payload = valuation_mod.to_dict(result)

    if payload["method"] == "unavailable":
        print(f"Unavailable: {payload['error']}")
        print(f"  {payload['explanations'].get('overview', '')}")
        return 1

    print("Structural checks:")
    _check(payload["method"] == "dcf_fcf", "method is dcf_fcf")
    _check(payload["current_price"] > 0, f"current price > 0 ({payload['current_price']:.2f})")
    _check(payload["history"] is not None, "FCF history present")
    _check(len(payload["history"]["fcf_values"]) >= 2,
           f"at least 2 years of FCF history "
           f"(got {len(payload['history']['fcf_values'])})")
    _check(payload["base_beta"] is not None, "beta computed")
    _check(payload["base_discount_rate"] is not None, "discount rate computed")

    # Scenarios
    scen_names = {s["name"] for s in payload["scenarios"]}
    _check(scen_names == SCENARIOS, f"all 3 scenarios present (got {sorted(scen_names)})")

    for s in payload["scenarios"]:
        _check(len(s["forecast"]) == 5, f"{s['name']}: 5-year forecast "
                                         f"(got {len(s['forecast'])})")
        _check(s["assumptions"]["discount_rate"] > 0,
               f"{s['name']}: discount rate > 0")
        _check(s["assumptions"]["discount_rate"] > s["assumptions"]["terminal_growth"],
               f"{s['name']}: discount ({s['assumptions']['discount_rate']:.3f}) > "
               f"terminal g ({s['assumptions']['terminal_growth']:.3f})")
        _check(s["terminal_value"] > 0 if payload["history"]["latest_fcf"] > 0 else True,
               f"{s['name']}: terminal value positive when FCF positive")
        _check(s["enterprise_value"] > 0 if payload["history"]["latest_fcf"] > 0 else True,
               f"{s['name']}: EV positive when FCF positive")

    # Sensitivity matrix
    _check(len(payload["sensitivity"]) == 9, f"3×3 sensitivity matrix "
                                              f"(got {len(payload['sensitivity'])})")

    # Weighted intrinsic
    _check(payload["weighted_intrinsic"] is not None, "weighted intrinsic computed")
    _check(payload["weighted_upside_pct"] is not None, "weighted upside computed")

    # Weights sum to 1.0
    w_sum = sum(payload["scenario_weights"].values())
    _check(abs(w_sum - 1.0) < 1e-6, f"scenario weights sum to 1 (got {w_sum:.4f})")

    # --- Human-readable summary ---
    h = payload["history"]
    print(f"\nFCF history ({h['fcf_method']}, reliability={h['reliability']}):")
    for yr, v in zip(h["years"], h["fcf_values"]):
        print(f"  {yr}: {_fmt_money(v)}")
    cagr_txt = f"{h['cagr']:+.2%}" if h["cagr"] is not None else "n/a (sign changes)"
    print(f"  latest={_fmt_money(h['latest_fcf'])}  avg={_fmt_money(h['avg_fcf'])}  "
          f"CAGR={cagr_txt}")

    print(f"\nInputs:")
    print(f"  current price : ${payload['current_price']:,.2f}")
    print(f"  β             : {payload['base_beta']:.2f}")
    print(f"  discount rate : {payload['base_discount_rate']:.1%}  "
          f"(CAPM: {payload['assumptions_global']['risk_free_rate']:.1%} rf + "
          f"β × {payload['assumptions_global']['equity_risk_premium']:.1%} ERP)")
    print(f"  base growth   : {payload['base_growth']:+.1%}")

    print(f"\nScenarios:")
    print(f"  {'Scenario':<8} {'g_init':>8} {'g_term':>8} {'r':>6} "
          f"{'Intrinsic':>12} {'Upside':>8} {'MoS':>8}")
    for s in payload["scenarios"]:
        a = s["assumptions"]
        print(f"  {s['name']:<8} {a['initial_growth']:>+7.1%} {a['terminal_growth']:>+7.1%} "
              f"{a['discount_rate']:>+5.1%} "
              f"{_fmt_money(s['intrinsic_per_share']):>12} "
              f"{s['upside_pct']:>+7.1%} {s['margin_of_safety']:>+7.1%}")

    print(f"\nProbability-weighted (Bear 25% / Base 50% / Bull 25%):")
    print(f"  intrinsic : {_fmt_money(payload['weighted_intrinsic'])}/share")
    print(f"  upside    : {payload['weighted_upside_pct']:+.1%}")
    print(f"  verdict   : {payload['recommendation']}")

    print(f"\nSensitivity matrix (intrinsic / share):")
    disc_axis = sorted({c["discount_rate"] for c in payload["sensitivity"]})
    term_axis = sorted({c["terminal_growth"] for c in payload["sensitivity"]})
    print(f"  {'r \\ g':<8}" + "".join(f"{g:>10.1%}" for g in term_axis))
    for r in disc_axis:
        row = [c for c in payload["sensitivity"] if abs(c["discount_rate"] - r) < 1e-9]
        row.sort(key=lambda c: c["terminal_growth"])
        print(f"  {r:<8.1%}" + "".join(f"{_fmt_money(c['intrinsic_per_share']):>10}"
                                         for c in row))

    print("\nBase-case 5-year forecast:")
    base = next(s for s in payload["scenarios"] if s["name"] == "Base")
    print(f"  {'Year':>4} {'Growth':>8} {'FCF':>15} {'PV':>15}")
    for f in base["forecast"]:
        print(f"  {f['year']:>4} {f['growth_rate']:>+7.1%} "
              f"{_fmt_money(f['fcf']):>15} {_fmt_money(f['present_value']):>15}")
    print(f"  terminal PV ........ {_fmt_money(base['terminal_pv']):>15}")
    print(f"  enterprise value ... {_fmt_money(base['enterprise_value']):>15}")
    print(f"  + cash − debt ...... {_fmt_money(base['equity_value'] - base['enterprise_value']):>15}")
    print(f"  equity value ....... {_fmt_money(base['equity_value']):>15}")
    print(f"  / shares ........... {base['assumptions']['shares_outstanding']/1e9:.3f}B")
    print(f"  intrinsic / share .. ${base['intrinsic_per_share']:,.2f}")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
