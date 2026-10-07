"""Rewrite every agent's evidence file from the latest research (backend/agent_evidence.py).

    python scripts/refresh_agent_evidence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import agent_evidence  # noqa: E402

run = agent_evidence.latest_run()
for agent_id, path in agent_evidence.refresh(run).items():
    print(f"  {agent_id:16s} {path.relative_to(agent_evidence.ROOT).as_posix()}")
print(f"from {run.relative_to(agent_evidence.ROOT).as_posix() if run else 'no backtest run'} and the base rates")
