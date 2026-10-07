# Decision log

Newest first. Append-only: when a decision changes, add a new entry that says what it
replaces. Don't edit the old one. Each entry is a date, the decision, and why.

### 2026-10-07: Accuracy over breadth: the S&P 500 only, for now
Marik: "I would rather the data be accurate than having more options." Smaller companies
stay out until a source with verified historical membership and delisted prices is
available (WRDS/CRSP or a paid source). **Why:** without them, a backtest on small stocks
silently drops the losers.

### 2026-10-07: A weekday 9:45 am briefing email (plain code, not an AI)
Contents:
- the market's trend
- top S&P 500 movers over the last completed day, week and month, each with its trend,
  its SEC 8-K filings and its newest headline
- a history check of what usually followed such moves
- the Growth and Value Screens' picks, labeled experimental with their failed backtests
- the scoreboard

**Why:** Marik asked for "top stocks for the day, week and month and how they are trending".
Movers are facts about the past. Predictions are labeled with their record. Official
filings come before headlines, because many headlines are clickbait.

### 2026-10-07: Decision aids from the IS research Marik shared
- **Trend-chasing warning backed by history.** The mobile-trading-app study (Liu et al. 2025)
  found that easy access raised trend-chasing.
- **A scorecard grading paper trades the way agents are graded.**
- **A trading-activity count.** The same study found an inverted U: moderate use did best.
- **An optional anonymous "Big Three" literacy check** (Lusardi & Mitchell), to see whether
  people learn here.

### 2026-10-07: Each agent's evidence follows its charter's boundaries
`backend/agent_evidence.py` routes facts:
- **No price-move history** for the Growth Hunter or Quality & Value.
- **Each agent sees only its own twin's record.** The Chief Analyst sees all of them.
- **Base rates** go to everyone.

A test enforces this.

### 2026-10-07: Company-ID links need accounting proof
- **A predecessor ID** is linked only when the new company's first annual report shows the
  old company's revenue as its own, two years matching within 0.5%. One matching year was
  a coincidence (Gardner Denver vs Allegion).
- **An ID that took over a ticker later** counts only from when its name matched (IR).

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
