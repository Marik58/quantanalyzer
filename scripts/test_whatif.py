"""Smoke test for backend/analysis/whatif.py — growth-of-$10k module."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.analysis import whatif  # noqa: E402


def run(ticker: str = "AAPL") -> int:
    r = whatif.compute(ticker)
    if r.error:
        print(f"ERROR: {r.error}")
        return 1

    print(f"What-if: ${r.amount:,.0f} in {r.ticker}\n")
    print(f"{'Held':<6}{'Ends at':>14}{'CAGR':>9}{'MaxDD':>9}{'SPY ends':>14}{'vs SPY':>14}")
    for h in r.horizons:
        spy = f"${h.spy_final_value:,.0f}" if h.spy_final_value is not None else "n/a"
        vs = f"${h.vs_spy_final:+,.0f}" if h.vs_spy_final is not None else "n/a"
        print(f"{h.label:<6}{'$' + format(h.final_value, ',.0f'):>14}"
              f"{h.cagr_pct:>+8.1f}%{h.max_drawdown_pct:>8.1f}%{spy:>14}{vs:>14}")

    print(f"\nCalendar years: {len(r.calendar_years)} · "
          f"chart points: {len(r.series['dates'])}")
    print("\nExplanations:")
    for k, v in r.explanations.items():
        print(f"  [{k}] {v}")
    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else "AAPL"))
