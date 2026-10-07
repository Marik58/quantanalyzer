# Context: what QuantAnalyzer knows, and what its agents are given

This folder is the project's memory. Everything a person or an AI agent needs to work on
QuantAnalyzer lives here, in the repo, not on anyone's laptop. If it isn't written here
(or in `ROADMAP.md` / `docs/AGENT_CHARTERS.md`), assume nobody knows it.

## How it's organized

| Folder | What goes in it | Who reads it |
|---|---|---|
| [`project/`](project/) | What the project is, how we work, the honesty rules, and a dated log of decisions | Everyone, first |
| [`data/`](data/) | Every data source: what it is, how far it can be trusted, its license, and its known gaps | Anyone touching data; the Auditor |
| [`research/`](research/) | Verified findings, and one folder per backtest run with its report and numbers | Anyone quoting a result; agents' base rates |
| [`agents/`](agents/) | One file per AI analyst: the evidence and lessons it starts with (its twin's backtest, base rates, pitfalls) | Each agent, through its context packet |

The plan itself stays in [`ROADMAP.md`](../ROADMAP.md), and the agents' rules stay in
[`docs/AGENT_CHARTERS.md`](../docs/AGENT_CHARTERS.md). This folder holds the **facts and
evidence** those documents rely on.

## Rules for adding to it

1. **One topic per file.** A new data source gets a section in `data/sources.md`, or its own
   file once it grows past a page. A new agent gets `agents/<agent-id>.md`.
2. **Every number names where it came from**: a file in `research/backtests/`, a script, or a
   linked source. Numbers from memory aren't allowed.
3. **Date everything.** Findings go stale. Write "as of 2026-10-07", not "currently".
4. **Never delete a finding that turned out wrong.** Mark it superseded and link the
   correction (see `research/findings.md`), so the history of mistakes stays visible.
5. **Backtest runs are folders, not edits.** Each run writes
   `research/backtests/<date>-<name>/` (report, summary, monthly data). A new run makes a
   new folder; old ones stay as the record.
6. **Agent files are machine-readable.** They start with a small header (`id`, `kind`,
   `updated`, `sources`) so the code that builds agent prompts can load them.
7. **Nothing private.** The repo is public: no emails, keys, or personal details. Those live
   in `.env` (never committed).

## What stays off GitHub, and why

Large raw downloads (SEC filings, price histories, about 1 GB) are kept in `data/cache/` and
`data/edgar/`, which are ignored by git. They are public data and every script rebuilds them,
so losing a laptop loses time, not knowledge. Some sources' licenses also don't allow
republishing their raw data (see `data/sources.md`).
