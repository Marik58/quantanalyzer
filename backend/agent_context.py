"""Each AI analyst's context, assembled from the repo (docs/AGENT_CHARTERS.md §4).

Every agent has a memory box at context/agents/<agent-id>/:

  notes.md     yours to edit: focus, background knowledge, things to watch for
  lessons.md   written by the weekly review (at most 10 lessons, each backed by 5+
               graded calls; charters §8), not by hand
  evidence.md  written by code: its twin's backtest and base rates

plus context/agents/_shared/ (notes.md and evidence.md), which every agent gets.
Guidance for the person editing lives in <!-- comments -->, which agents never see.

`load(agent_id)` stacks the layers in a fixed order, with the locked ones (house rules,
the agent's own charter section) first and a precedence line saying they win any
conflict. Notes and lessons add context; they can never loosen a boundary.

The result carries a `version`: a fingerprint of everything the agent will read. The
ledger stores it with each call (as `charter_version`), so when you edit an agent's notes
its later calls are graded as a new version, and the scoreboard shows whether the edit
helped.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARTERS = ROOT / "docs" / "AGENT_CHARTERS.md"
BOXES = ROOT / "context" / "agents"

# agent id -> (display name, charter section number)
AGENTS: dict[str, tuple[str, str]] = {
    "trend-trader": ("Trend Trader", "9.1"),
    "growth-hunter": ("Growth Hunter", "9.2"),
    "quality-value": ("Quality & Value", "9.3"),
    "news-analyst": ("News Analyst", "9.4"),
    "hype-watch": ("Hype Watch", "9.5"),
    "macro-strategist": ("Macro Strategist", "10.1"),
    "supply-chain-mapper": ("Supply-Chain Mapper", "10.2"),
    "horizon-scout": ("Horizon Scout", "10.3"),
    "bull-advocate": ("Bull Advocate", "11.1"),
    "bear-advocate": ("Bear Advocate", "11.1"),
    "chief-analyst": ("Chief Analyst", "11.2"),
    "risk-manager": ("Risk Manager", "11.3"),
    "auditor": ("Auditor", "12.1"),
    "source-checker": ("Source Checker", "12.2"),
}
BOX_FILES = ("notes.md", "lessons.md", "evidence.md")
PRECEDENCE = ("If anything in the notes, lessons or evidence below conflicts with the house "
              "rules or your charter, the house rules and the charter win. Notes add context; "
              "they never loosen a boundary.")


class ContextError(KeyError):
    """Unknown agent, or a charter section that can't be found."""


@dataclass
class AgentContext:
    agent_id: str
    name: str
    layers: list[tuple[str, str]] = field(default_factory=list)   # (title, text), in reading order
    version: str = ""

    def text(self) -> str:
        return "\n\n".join(f"## {title}\n\n{body}" for title, body in self.layers)


def _section(markdown: str, heading_re: str) -> str:
    """The text under the first heading matching `heading_re`, up to the next heading
    at the same or a higher level."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#+)\s+" + heading_re, line)
        if m:
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                h = re.match(r"^(#+)\s", nxt)
                if h and len(h.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    raise ContextError(f"no charter heading matching {heading_re!r}")


def _clean(text: str) -> str:
    """What the agent actually reads from a box file: no `---` header, no `<!-- -->`
    guidance comments, and no headings left empty. An untouched template reads as
    nothing, so it doesn't change the agent's version."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    kept, pending = [], None
    for line in text.splitlines():
        if re.match(r"^#+\s", line):
            pending = line                      # print a heading only once it has content
            continue
        if line.strip():
            if pending is not None:
                kept.append(pending)
                pending = None
            kept.append(line)
        elif kept:
            kept.append("")
    return "\n".join(kept).strip()


def _box_text(path: Path) -> str:
    return _clean(path.read_text(encoding="utf-8")) if path.exists() else ""


def load(agent_id: str, charters: Path = CHARTERS, boxes: Path = BOXES) -> AgentContext:
    if agent_id not in AGENTS:
        raise ContextError(f"unknown agent {agent_id!r}; known: {', '.join(AGENTS)}")
    name, number = AGENTS[agent_id]
    doc = charters.read_text(encoding="utf-8")
    ctx = AgentContext(agent_id, name)
    ctx.layers.append(("House rules (locked)", _section(doc, r"5\.\s")))
    ctx.layers.append((f"Your charter: {name} (locked)", _section(doc, re.escape(number) + r"\s")))
    ctx.layers.append(("Precedence", PRECEDENCE))
    for title, path in (("Notes for every agent", boxes / "_shared" / "notes.md"),
                        ("Evidence for every agent (from code)", boxes / "_shared" / "evidence.md"),
                        ("Your notes", boxes / agent_id / "notes.md"),
                        ("Your lessons (from graded calls)", boxes / agent_id / "lessons.md"),
                        ("Your evidence (from code)", boxes / agent_id / "evidence.md")):
        body = _box_text(path)
        if body:
            ctx.layers.append((title, body))
    ctx.version = hashlib.sha256(ctx.text().encode("utf-8")).hexdigest()[:12]
    return ctx


def versions() -> dict[str, str]:
    """Every agent's current context fingerprint (for the Lab page and audits)."""
    return {a: load(a).version for a in AGENTS}
