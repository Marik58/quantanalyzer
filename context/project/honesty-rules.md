# Honesty rules (as of 2026-10-07)

> "I would rather no response than a response that gives me false data." (Marik, 2026-10-06)

These apply to the app, to every AI agent, and to anyone writing reports about the project.

## No made-up data

- Never present a number, fact or result that isn't verified. Show "n/a" or nothing instead.
- **Speculation is allowed only when it's labeled as speculation and says where it comes
  from** (which model, rule, source or assumption).
- Model estimates (a DCF fair value, an untested outlook) are labeled as estimates, with the
  model named.
- Every number names its source: a field in an evidence packet, a file in
  `context/research/`, or a linked document. In agent outputs, numbers appear only as field
  references, and all math happens in code (see `docs/AGENT_CHARTERS.md`).
- When sources disagree, show the disagreement. Don't pick one quietly.

## Quoting backtest results

1. **Never quote a return or information ratio without its t-statistic** and sample size
   (months, stocks, dates).
2. **The bar is t ≥ 3**, not 2 (Harvey, Liu & Zhu 2016). Many ideas get tested here, and with
   enough tries a t of 2 turns up by luck.
3. **Every variant that's run is recorded** in the trials ledger (`backtest_trials` table),
   so a lucky variant can't be quietly kept. Rules are written down before results are seen.
4. **A raw result means nothing until it survives factor adjustment** (Fama-French 5 plus
   momentum). Otherwise it may just be a known tilt in disguise.
5. **Say what's missing.** Stocks without data (often companies that failed or were bought
   out) are counted and reported, never silently dropped and never guessed.
6. **Never quote a number from before a fix.** When a bug is fixed, every result it touched
   is re-run, and the old numbers are marked superseded.
7. **One good year proves nothing.** The S&P 500 itself returned about 26% in 2023 and 25% in
   2024.

## AI agents specifically

- AI agents are graded **forward-only**. An AI backtested on dates inside its training data
  already knows what happened (Glasserman & Lin 2023).
- An agent that can't support a call with evidence fields says so, instead of guessing.
