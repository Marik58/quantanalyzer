# QuantAnalyzer Roadmap

**Last updated:** 2026-10-05 · **Status:** draft, awaiting Marik's sign-off

This is the one plan for the project. It replaces the plans in `PROJECT_STATUS.md`,
`NEXT_SESSION.md`, `HANDOFF.md` §6, `FUNDING_PROPOSAL.md` §7, and the September 2026
planning pages (Literature Roadmap, Build Preview, Data Plan, and the Sep 30 Phase B–F
proposal). If another document disagrees with this one, this one wins.

The agents, their rules, and how they're judged are specified in
[`docs/AGENT_CHARTERS.md`](docs/AGENT_CHARTERS.md).

---

## 1. What QuantAnalyzer is

> **A research and learning platform built around a panel of AI agents. Each agent
> studies stocks through a different lens, under its own rules. Every call is saved with
> the exact evidence behind it and graded later against reality and fair benchmarks, so
> you can see which approaches actually find winners. Every lens comes with a lesson that
> teaches how it works.**

Think of it as part FactSet, part course, part honest experiment.

**Two goals, one engine:**
1. **Marik's research goal:** find long-term growth stocks and undervalued stocks, and
   find out honestly whether any approach can reach **25–30% a year** over several years.
2. **The public goal:** help people understand stocks and how each kind of analysis
   works, with every tool's real track record visible.

**It is not:** Fox Fund pitches, a public picks list, or personal investment advice.

---

## 2. How the pieces fit together

```
  1. DATA FOUNDATION   prices (snapshotted daily) · SEC filings as first filed ·
                       first-release economic data · news archive · attention data
            │
            ▼
  2. MODELS + TWINS    rule-based calculations, all math in code. The Growth and
                       Value "twins" are backtested on 15–20+ years of history FIRST
            │
            ▼
  3. SCREENS           thousands of stocks → ~50 candidates per agent
                       (that list doubles as the agent's "Candidate Pool" benchmark)
            │
            ▼
  4. AGENT PANEL       Team 1 analysts · Team 2 scouts      → work alone
                       Team 3 Bull/Bear · Risk Manager      → after calls lock
                       Team 4 Auditor · Source Checker      → check everyone
                       Chief Analyst                        → reads everything, runs last
            │
            ▼
  5. LEDGER            every call saved with its exact evidence packet,
                       model ID, entry date, and source tag
            │
            ▼
  6. SCOREBOARD        graded vs Index · Candidate Pool · Base-Rate Forecaster ·
                       Coin Flip · factor-adjusted · the 25% hurdle line
            │                  └──► report cards fed back to each agent
            ▼
  7. SCREENS PEOPLE SEE   Model Board per ticker (with the Full Picture card) ·
                          Scoreboard · Learn · usage insights · your private Lab
                          (This Week's 10, Long-Term 10, the 25% hurdle line)
```

**Why agents work alone and see different data.** If every agent sees the same thing,
they all say the same thing. The boundaries are what make the panel worth having.

**Connected, not fragile.** If one agent or data source fails, its card says
"unavailable" and everything else keeps working.

---

## 3. Ground rules

1. **Research and education, not advice.** The public site shows research with report
   cards, never a picks list. Your private Lab holds the weekly Top 10 and the monthly
   Long-Term 10, which are graded like any agent. Don't publicly promote a stock you're trading.
2. **No call without a track record.** Every card shows its record and sample size.
3. **AI agents are only judged forward.** An AI model has already read about the past,
   so testing it on past dates is rigged (Glasserman & Lin 2023). Historical evidence
   comes from rule-based twins.
4. **All math happens in code.** Agents cite numbers only by field name and never
   calculate their own.
5. **Every call is reproducible.** The exact evidence packet and AI model ID are saved
   with it. Delisted stocks keep their final return. Trap calls are excluded from grading.
6. **Fair benchmarks.** Each agent is compared with its own Candidate Pool, a Base-Rate
   Forecaster, Coin Flip, and the S&P 500, plus factor-adjusted results.
7. **The real-money test is decided now:** a twin with long history at t ≥ 3, a live
   agent that's honest, calibrated, and not worse than its twin, and only then small
   amounts. See `docs/AGENT_CHARTERS.md` §14.
8. **Learning within limits.** Agents write lessons from their graded calls, but only
   Marik changes a charter, and every change (including a new AI model) starts a new
   version and a fresh record.
9. **Pumps get flagged, never pitched.**
10. **Data is dated and sourced.** Licensed data never goes in the public repo. Usage
    tracking is anonymous by default.

---

## 4. What changed from the old plan

| Old idea (Sep 2026) | Now |
|---|---|
| Fox Fund members and finance students | Marik's own research, plus anyone learning to research stocks |
| Success = better-calibrated decisions | Success = honest evidence on which lenses find growth and value winners, plus people learning how each works |
| The failed backtest is the headline | The scoreboard is the headline. The old backtest is the Trend Trader twin's first entry |
| A formal IRB research study | Dropped. Replaced by anonymous usage insights |
| One blended Quant Score | A panel of independent agents in four teams, plus a Chief Analyst who explains the full picture |
| Compare against the S&P 500 | Compare against the Candidate Pool, the base rate, Coin Flip, the S&P 500, and factor-adjusted results |
| Free data only | Mostly free. AI is roughly $10–20/month for wave 1 and $30–80 for the full panel. Small caps may need a ~$30/month price source |

---

## 5. What happens to what's already built

| Existing code | Becomes |
|---|---|
| `signals.py`, `indicators.py`, `regime_hmm.py`, `statistics.py` | Trend model, the Trend Trader's tools, and its twin |
| `valuation.py`, `peers.py` (+ SEC filings) | Business model, the Growth and Value twins, and their agents' tools |
| `crisis.py`, `risk_framework.py`, `whatif.py` | Resilience model, the Risk Manager's tools (add 2000–02, 2008, and late-2018 windows) |
| `sentiment.py`, `catalyst.py`, news archive | News model and the starting point for Crowd |
| `universe.py` | Point-in-time universe, plus index-removal events for the Value agent's "forced selling" |
| `factors.py`, `score_backtest.py`, trials ledger | The scoreboard engine: factor adjustment, backtests, and counting trials |
| `macro.py` | Upgraded to first-release data for the Macro Strategist |
| `glossary.py`, Learn tab | Learn |
| `game.py`, `paper.py` | Practice, and the "You" row on the scoreboard |
| `pitch_deck.py`, `speaker_prep.py`, `thesis.py`, `report_writer.py` | Removed from the app; the code stays in git history |
| `topology.py`, `spectral.py`, `manifold.py` | The Experimental section of Trend |
| `quant_score.py` | Replaced by the agent panel |

---

## 6. Phases

"Sessions" means Claude-assisted working sessions: one Roadmap item per session, with
tests green before every commit. Estimates are rough.

**Progress (2026-10-06):**
- **Phases 0 and 1 are done.** Phase 1 delivered:
  - the prediction ledger and daily price snapshots
  - the anonymous usage log, with browser tracking and a private Lab page at `/admin`
  - the Trend twin (49 live calls sealed on 2026-10-05; first grades due around 2026-11-03)
  - the daily job, scheduled for weekdays at 6:30 pm. It runs without a window, catches
    up if the computer was asleep, and archives news for the watchlist plus the tracking list
- **Fixes found along the way:**
  - the tests no longer wipe real data, and 10 junk test trials were removed (with a backup)
  - the news feed works again (the archive went from 30 to over 1,300 headlines)
  - the Learn tab no longer quotes backtest numbers from before the audit fixes
- **Still open, for Marik:** apply for Reddit API access (needed in Phase 8; approval is slow).

**Phase 2 is done (2026-10-06).** The Model Board replaces the Overview:
- four model cards (Business, Resilience, Trend, News), each with its evidence, reasons,
  what it's bad at, an honest track-record label, and lesson links
- no card can claim "high" strength until a model passes the real-money bar
- the pitch tools are removed
- every "How to read this" box was rewritten to teach instead of giving trading rules

Known limits to fix later:
- the Business card's DCF calls fast growers badly overvalued (Phase 3 rebuilds it on SEC filings)
- Yahoo's per-stock news feed mixes in related companies' headlines

**Next: Phase 3** (SEC financial history and the Growth/Value twin backtests).

### Phase 0: Reset (1 session) — done
- Push the unpushed commits, and commit the n=200 log the README cites.
- Make this file the only plan. Move the outdated docs into `docs/archive/`.
- Rewrite the README's first section. Mark `FUNDING_PROPOSAL.md` as superseded.

**Done when:** the repo and GitHub tell the same story as this file.

### Phase 1: Start the clocks (2–3 sessions) — done
- **Usage log**, anonymous, with an admin page.
- **The ledger**, including evidence-packet storage, model ID, entry date, source tag,
  and trap flag.
- **Daily price snapshots** for every stock that appears in the ledger.
- **Daily job:** archive headlines, record model outputs, and grade matured calls.
- **Apply for Reddit API access** now, because approval reportedly takes weeks.

**Done when:** each day's data and calls are saved and graded without you doing anything.

### Phase 2: Model Board, version 1 (3–4 sessions) — done
- Model cards for Business, Resilience, Trend and News, each with a lesson.
- Remove the pitch tools from the app.

**Done when:** you type AAPL and see the model cards in one place.

### Phase 3: Real financial history and the twins (3–4 sessions)
- 15–20+ years of SEC financial statements, as first filed, for US companies of $300M or more.
- **Growth Screen and Value Screen backtests**, using the new yardstick: Candidate
  Pool, factor-adjusted, after costs, t ≥ 3, and checked across sub-periods.
  **This is the first evidence-based answer to "can growth or value reach 25%?"**
- A "Reading financial statements" lesson track.
- A **twin-only preview of the Top 10 lists** in the Lab, labeled "experimental."
- Decide on a price source for small caps.

**Done when:** you can see how rules-only growth and value strategies did over 15–20 years.

### Phase 4: Agent panel, wave 1 (4 sessions)
- An agent framework: it assembles each agent's context, enforces boundaries, validates
  output, and writes to the ledger.
- **A dry-run cost estimate** before anything goes live.
- **Trend Trader first**, running about 4 weeks as the test pilot to shake out the
  pipeline.
- Then the **Growth Hunter**, **Bull + Bear**, the **Chief Analyst** (Full Picture cards
  and the weekly Panel Briefing), and the **Auditor** (code checks, AI review, trap tests,
  and the independence check).
- All four benchmarks. Your private Lab: **This Week's 10** (every Monday, judged after 4
  weeks) and the **Long-Term 10** (monthly, judged after 12 months), both graded like an
  agent, plus the 25% hurdle line.

**Done when:** the wave 1 agents run weekly, and every call is audited and saved.

### Phase 5: Scoreboard (2 sessions)
- Records per agent and version against every benchmark, the Brier skill score,
  calibration, and the staged real-money checklist.
- Weekly lesson reviews and the Auditor's monthly review.

### Phase 6: Soft launch (2 sessions)
- A permanent database (Neon), deployment, the daily job in the cloud, disclaimers, a
  privacy note, and rate limiting. Share with 5–10 people.

### Phase 7: Agent panel, wave 2 (4 sessions)
- **Quality & Value** (expanded), **Risk Manager + Paper Portfolio Builder**, **Macro
  Strategist** (first-release data), and **Supply-Chain Mapper**.

### Phase 8: Agent panel, wave 3 (3–4 sessions)
- **Horizon Scout + Source Checker**, plus the attention data and the **Hype Watch** agent.

### Phase 9: Agent panel, wave 4 (1–2 sessions)
- **News Analyst**.

### Phase 10: Accounts (optional, 2–3 sessions)
- Logins, saved watchlists, and personal learning progress.

**Total:** about 30–35 sessions, roughly 5–7 months at 1–2 sessions a week. Phases 0–4
come first, in order. Later phases can be reordered.

**Timing reality:** the twin backtests (Phase 3) give answers within weeks. The Trend
Trader's live record starts meaning something within months. The 12-month agents need
about a year for a first real report card, and proving an edge statistically takes
years (`AGENT_CHARTERS.md` §14).

---

## 7. Costs

| Item | Estimate | Note |
|---|---|---|
| AI, wave 1 | ~$10–20 / month | Measured in the Phase 4 dry run |
| AI, full panel | ~$30–80 / month | The Horizon Scout's web searches and the debates are the biggest parts |
| Small-cap price data | ~$30 / month | To be confirmed in Phase 3 |
| Database and hosting | $0 to start | Neon free tier, Render free tier |

---

## 8. Open decisions (recommended default in bold)

1. Starting monthly budget: **~$15 (AI); decide on ~$30 (data) in Phase 3**.
2. Game and paper trading: **keep as Practice and the "You" row** / remove.
3. Funding proposal: **rewrite after the soft launch** / now / drop.
4. Where the daily job runs before Phase 6: **your PC** / cloud from the start.
5. Blind-mode experiment for the Growth Hunter: **yes** / no.

---

## 9. Not doing

- **Signals for getting into pump-and-dumps.** Hype Watch detects and warns.
- **Promising 25–30% a year.** It's a hurdle measured over several years. The S&P 500
  alone returned about 26% in 2023 and 25% in 2024, so one good year proves nothing.
- **Telling agents "find stocks that will return 25%."** Agents give honest
  probabilities, and the scoreboard compares them with the target.
- **One magic score.** Training our own AI models. Paid real-time data. Badges, streaks,
  or confetti.

---

## References

See `docs/AGENT_CHARTERS.md` for the full list. Evidence for the current backtest:
`scripts/_watchlist_backtest_v3.log`, `scripts/_universe_pilot_n80.log`,
`scripts/_universe_pilot_n200.log`.
