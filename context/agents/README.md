# Agent memory boxes

Each AI analyst has a box: `context/agents/<agent-id>/`. Everything in it is read with every
call, through `backend/agent_context.py`.

| File | Who writes it | What it's for |
|---|---|---|
| `notes.md` | **You (Marik)** | Focus, background knowledge, things to avoid. Change it whenever you like |
| `lessons.md` | The weekly review (code) | At most 10 lessons, each backed by 5+ graded calls (charters §8) |
| `evidence.md` | Code | The agent's twin backtest and its base rates (refreshed by `scripts/run_screen_backtest.py`) |

`_shared/` holds what **every** agent gets: your shared `notes.md` and the shared base rates
in `evidence.md`.

## What an agent reads, in order

1. House rules: charters §5 (locked)
2. Its own charter section (locked)
3. A precedence line: the house rules and charter win any conflict
4. Shared notes, then shared evidence
5. Its own notes, lessons, then evidence

So your notes can **add** context but can never loosen a boundary. If notes say "find
stocks that will return 30%", the charter still says the 25–30% target is a hurdle, not an
instruction, and the Auditor flags the conflict.

## How editing works

- Write anywhere outside the `<!-- -->` comment markers. The comments are guidance for you,
  and agents never see them. Empty headings are skipped.
- **Every real edit makes a new agent version.** The loader fingerprints everything the
  agent reads, and the ledger stores that fingerprint with each call. Calls made before and
  after your edit are graded separately, so the scoreboard shows whether the change helped.
  Editing only a comment doesn't change the version.
- Label anything that isn't in the agent's evidence packet as background, and say where it
  came from (house rule 3).
- Don't put private information here. The repo is public, and a test checks this folder for
  email addresses.

## Adding a new agent

1. Write its charter section in `docs/AGENT_CHARTERS.md`.
2. Add it to `AGENTS` in `backend/agent_context.py` (id, name, section number).
3. Run `python scripts/make_agent_boxes.py` to create its box. Existing files are never
   overwritten.

## Current agents

| Agent | Charter | Wave | Twin evidence |
|---|---|---|---|
| `trend-trader` | §9.1 | 1 (pilot) | yes |
| `growth-hunter` | §9.2 | 1 | yes |
| `quality-value` | §9.3 | 2 | yes |
| `news-analyst` | §9.4 | 4 | not yet |
| `hype-watch` | §9.5 | 3 | not yet |
| `macro-strategist` | §10.1 | 2 | not yet |
| `supply-chain-mapper` | §10.2 | 2 | not yet |
| `horizon-scout` | §10.3 | 3 | not yet |
| `bull-advocate`, `bear-advocate` | §11.1 | 1 | not applicable |
| `chief-analyst` | §11.2 | 1 | not applicable |
| `risk-manager` | §11.3 | 2 | not yet |
| `auditor` | §12.1 | 1 | not applicable |
| `source-checker` | §12.2 | 3 | not applicable |
