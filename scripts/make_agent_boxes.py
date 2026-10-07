"""Create a memory box for every agent in backend/agent_context.py that doesn't have one.

    python scripts/make_agent_boxes.py

Never overwrites an existing file. To add a new agent: add it to AGENTS in
backend/agent_context.py (and give it a charter section), then run this.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agent_context import AGENTS, BOXES  # noqa: E402

NOTES = """---
id: {id}
kind: agent-notes
editable_by: Marik
created: {today}
---

# Notes for the {name}

<!--
This is your box: write anything you want the {name} to know or focus on.
- It's read with every call, after the house rules and the agent's charter
  (docs/AGENT_CHARTERS.md §{section}), which win if anything here conflicts with them.
- Only text outside these comment markers reaches the agent; empty headings are skipped.
- Editing this file makes a new agent version: later calls are graded separately, so the
  scoreboard shows whether your change helped.
- Label anything that isn't from the evidence packet as background, and say where it's from.
-->

## Focus
<!-- e.g. "Pay extra attention to whether R&D is growing faster than revenue." -->

## Background knowledge
<!-- e.g. "Background (from the company's 2025 10-K): most revenue is from one customer." -->

## Things to avoid
<!-- e.g. "Don't treat a one-time asset sale as growth." -->
"""

LESSONS = """---
id: {id}
kind: agent-lessons
editable_by: the weekly review (code)
created: {today}
---

# Lessons for the {name}

<!--
Written by the weekly review, not by hand (docs/AGENT_CHARTERS.md §8):
- at most 10 lessons, and only after 20+ graded calls
- each lesson cites at least 5 graded calls (by call_id) as support
- lessons never override the charter
Empty until the agent has 20 graded calls.
-->
"""

EVIDENCE = """---
id: {id}
kind: agent-evidence
editable_by: code
created: {today}
---

# Evidence for the {name}

<!--
Written by code from backtests and the ledger; don't edit by hand.
Empty until this agent's rule-based twin has been backtested or it has graded calls.
-->
"""

SHARED_NOTES = """---
id: _shared
kind: agent-notes
editable_by: Marik
created: {today}
---

# Notes for every agent

<!--
Anything written here (outside comment markers) is given to EVERY agent, after the house
rules and each agent's charter, which win any conflict. Editing it makes a new version of
every agent. Use it sparingly, for things that are true for the whole panel.
-->

## Background knowledge
<!-- e.g. "Background: the Federal Reserve meets 8 times a year; dates at federalreserve.gov." -->
"""


def main() -> None:
    today = date.today().isoformat()
    made = []
    files = {BOXES / "_shared" / "notes.md": SHARED_NOTES.format(today=today)}
    for agent_id, (name, section) in AGENTS.items():
        fields = {"id": agent_id, "name": name, "section": section, "today": today}
        for fname, tmpl in (("notes.md", NOTES), ("lessons.md", LESSONS), ("evidence.md", EVIDENCE)):
            files[BOXES / agent_id / fname] = tmpl.format(**fields)
    for path, text in files.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        made.append(path.relative_to(ROOT).as_posix())
    print(f"created {len(made)} files" + "".join(f"\n  {m}" for m in made))


if __name__ == "__main__":
    main()
