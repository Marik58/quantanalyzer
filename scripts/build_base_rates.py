"""Rebuild context/research/base_rates.json from the saved panel (backend/analysis/base_rates.py).

    python scripts/build_base_rates.py      # after scripts/run_screen_backtest.py build
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.analysis import base_rates  # noqa: E402

r = base_rates.build()
from backend import agent_evidence  # noqa: E402
agent_evidence.refresh()
print(f"base rates rebuilt (and agents' evidence refreshed) from {r['all_stocks']['n']:,} stock-months ({r['period']})")
