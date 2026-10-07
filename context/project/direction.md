# What QuantAnalyzer is (as of 2026-10-07)

**A free research and financial-literacy platform: "a cross between FactSet and courses."**
Look up a ticker and see what several kinds of analysis say about it, side by side on one
**Model Board**:

- Business (financials)
- Resilience (how it held up in past crashes)
- Trend (technicals)
- News
- Crowd (public sentiment and attention)

Every concept is explained in plain language.

An **AI analyst inside each model** makes calls. Each call is sealed in a ledger and graded
later against real outcomes, so the record shows whether it helps. A panel of independent
agents, each with its own lens, rules and limits (see `docs/AGENT_CHARTERS.md`), is
cross-checked by a **Chief Analyst**. Anonymous usage analytics show which tools people use.

## What it is not

- Not stock proposals or Fox Fund pitches (dropped 2026-10-05).
- Not personal financial advice.
- Not a pump-and-dump timer. Hype Watch detects and warns; it never times entries.
  Promoted stocks fell 53% on average within 120 trading days (Leuz et al.).

## Goals and how they're used

- **Long-term growth stocks**, and a **25–30% a year** target. The target is a *scoreboard
  hurdle* that every agent's paper portfolio is plotted against over several years. It is
  never an instruction to an agent: an agent told to find 30% will find stories, not stocks.
- **Learning that's measured.** The proof that any approach works has to come from a long
  point-in-time backtest of its rule-based "twin". AI agents are judged forward-only,
  because an AI already knows how the past turned out (Glasserman & Lin 2023).

## History, briefly

The project has had three identities:
1. Apr–Jun 2026: a research platform
2. Aug–Sep 2026: an "investor decision lab"
3. Oct 2026: the current one

Its first honest finding carries over: the original technical score showed **no edge** once
it was tested properly (see `research/findings.md`). That became the Trend model's first
scoreboard entry.
