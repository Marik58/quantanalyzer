# Decision log

Newest first. Append-only: when a decision changes, add a new entry that says what it
replaces. Don't edit the old one. Each entry is a date, the decision, and why.

### 2026-10-07: The project's knowledge lives in the repo (`context/`)
Notes that used to live only on the development laptop moved here, so agents and people
read the same facts. **Why:** a laptop can be lost, and context that isn't written down
can't be checked.

### 2026-10-07: Growth Screen and Value Screen rules frozen before testing (v1)
The rules in `backend/analysis/screens.py` were written and committed before any result
was seen. Any change makes a new version and a new trials-ledger entry. **Why:** tuning
rules after seeing results manufactures false edges.

### 2026-10-06: Ticker-to-company map: several sources suggest, the SEC decides
Unverified rows are excluded from backtests, not guessed. A company that joined the index
the day another left counts as a rename only if the old ticker appears in its own 10-Ks.
**Why:** the first run's guesses were mostly wrong (CBS was matched to W.R. Berkley).

### 2026-10-06: Financials come from SEC filings, as first filed
**Why:** later restatements would leak information backwards into the past. The SEC
contact email stays in `.env` and is used only for sec.gov.

### 2026-10-06: No fake results
No answer is better than a false one. Speculation must be labeled as speculation and name
its source. See `honesty-rules.md`.

### 2026-10-06: The Business card's cash-flow model (DCF) doesn't vote when it's unreliable
It's skipped when its gap from the price is beyond ±50%, and for financial companies, and
its values are labeled as estimates. **Why:** it called 9 of 10 large caps overvalued and
gave JPMorgan a negative fair value.

### 2026-10-06: A Chief Analyst replaces the Moderator
It cross-references every agent's output and explains agreements and conflicts.

### 2026-10-05: The project reset (see `direction.md`)
- A research and literacy platform, not pitches or proposals.
- A panel of AI agents, each with its own lens and limits.
- 25–30% a year is a scoreboard hurdle, never an instruction to an agent.
- Hype Watch detects and warns only.
- `ROADMAP.md` is the only plan.

### 2026-10-05: How agents are judged
- Rule-based twins are backtested first.
- AI agents are graded forward-only.
- The bar is t ≥ 3.
- Real money is discussed only after a staged test (`docs/AGENT_CHARTERS.md` §14).
- Top 10 lists (weekly and monthly) stay in the private Lab and are never padded.
