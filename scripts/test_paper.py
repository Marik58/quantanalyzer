"""Smoke test for backend/paper.py — paper trading engine.

Exercises the full lifecycle against the local DB: reset, buy, sell,
every rejection path, reset again. Leaves the account clean.
"""
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

from backend import db, paper  # noqa: E402


WHY_T = "Regime is Bull and relative strength is top quintile"


def run() -> int:
    db.init()
    paper.reset()

    pf = paper.get_portfolio()
    assert pf.cash == db.PAPER_STARTING_CASH and not pf.positions, "reset state wrong"

    r = paper.place_trade("AAPL", "buy", 10,
                          thesis="Regime is Bull and relative strength is top quintile",
                          exit_rule="sell below the 50-day MA", source_tab="Quant")
    print(f"buy filled: {r['qty']:g} {r['ticker']} @ ${r['price']:,.2f}")
    pf = paper.get_portfolio()
    assert len(pf.positions) == 1 and abs(pf.positions[0].qty - 10) < 1e-9
    assert abs(pf.cash - (db.PAPER_STARTING_CASH - r["value"])) < 0.01

    paper.place_trade("AAPL", "sell", 4, thesis="Trimming into strength")
    pf = paper.get_portfolio()
    assert abs(pf.positions[0].qty - 6) < 1e-9
    assert pf.n_trades == 2
    print(f"after partial sell: qty={pf.positions[0].qty:g}, "
          f"equity=${pf.total_equity:,.2f}, realized=${pf.realized_pl:,.2f}")

    rejections = [
        (("AAPL", "sell", 999), {"thesis": "closing out"}, "oversell"),
        (("AAPL", "buy", 10**8), {"thesis": WHY_T, "exit_rule": "stop at -8%", "source_tab": "Quant"},
         "insufficient cash"),
        (("AAPL", "hold", 1), {}, "bad side"),
        (("AAPL", "buy", -5), {"thesis": WHY_T, "exit_rule": "stop at -8%", "source_tab": "Quant"},
         "negative qty"),
        (("AAPL", "buy", 1), {}, "missing thesis"),
        (("AAPL", "buy", 1), {"thesis": WHY_T}, "missing exit rule"),
        (("AAPL", "buy", 1), {"thesis": WHY_T, "exit_rule": "stop at -8%"}, "missing source tab"),
    ]
    for args, kw, label in rejections:
        try:
            paper.place_trade(*args, **kw)
            print(f"FAIL: {label} was not rejected")
            return 1
        except paper.TradeError as e:
            print(f"rejected ({label}): {e}")

    paper.reset()
    pf = paper.get_portfolio()
    assert pf.cash == db.PAPER_STARTING_CASH and not pf.positions and pf.n_trades == 0

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
