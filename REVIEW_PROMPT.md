# Prompt for next chat — QuantAnalyzer audit + low-budget plan

> Paste everything below the line into a **new Claude chat** that has access to the
> `c:\Users\marik\VSCode\quantanalyzer` folder.

---

You are a senior quant researcher + engineering lead reviewing my project, **QuantAnalyzer**.

## Context about me and the project
I'm a member of Fox Fund (a student-managed investment fund). QuantAnalyzer started as my
personal, single-developer, institutional-style equity research platform: enter a ticker →
get a multi-paradigm quant diagnostic plus a defendable written stock pitch, every output
paired with a plain-English explanation.

## Where I want to take it (expanded scope — please plan around THIS vision)
I want to grow QuantAnalyzer into a broader stock-analysis and learning platform — think a
lightweight, approachable version of FactSet / Bloomberg / Koyfin, aimed at helping people
make their own decisions. Target capabilities:
- **Deep stock analysis & fundamentals** — the kind of company/financial data that platforms
  like FactSet, Bloomberg, Koyfin, and Morningstar surface (financials, ratios, estimates,
  ownership, etc.), presented clearly.
- **Financial news** — pull and surface relevant market and company news in one place.
- **Historical performance / "what-if" trends** — let a user see how an investment would have
  played out, e.g. "if you invested in NVDA in 2012 and held until today" — growth of $X,
  CAGR, drawdowns, vs. benchmark — plus longer-run market trend views.
- **Paper trading** — a simulated portfolio so users can practice and track hypothetical
  trades without real money.
- **All the existing quant + research functions** (below) kept and integrated.
- **An education layer** — a place where people can *learn* (plain-English explanations,
  guided context) and get the information they need to make decisions on their own, rather
  than being told what to buy.

The plan you produce should treat the current app as the foundation and lay out how to reach
this broader product — while respecting the budget and constraints below.

- **Project root:** `c:\Users\marik\VSCode\quantanalyzer`
- **Stack:** FastAPI (async) · yfinance · pandas/numpy/scipy · scikit-learn · hmmlearn ·
  ripser · umap-learn · arch · vaderSentiment · vanilla JS + Plotly · SQLite · ReportLab
- **Hard constraints (do not violate):**
  - Data vendor: **yfinance only** — no paid API keys currently
  - **Windows host, no C++ toolchain** — every dependency must ship wheels or be pure Python
  - **Build incrementally** — one module at a time, test/approve before moving on
  - Default watchlist: ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS

## What's already built (verify against the actual code — don't trust this blindly)
- **Phase 0** — requirements, folder layout, SQLite DB + 15-min disk cache, Render deploy config
- **Phase 1 (9 modules)** — advanced statistics, spectral/FFT, HMM regime, TDA/topology,
  manifold learning, risk/stress framework, peers relative-value, news sentiment (VADER),
  Quant Score aggregator (weighted composite of the 8 with conflict flags)
- **Phase 2 (6 tools)** — DCF/valuation triangulation, catalyst tracker, long/short thesis
  generator, speaker prep / PM Q&A, full sell-side report writer, pitch-deck PDF
- **Phase 3** — tabbed dark-mode Plotly frontend + `/api/watchlist/scan`
- **Extra** — Quant Score backtest (`score_backtest.py`). Full 14-ticker run
  (518 obs, 2023-05 → 2026-05): IR ≈ **−0.38**, mean IC ≈ −0.034 (t = −0.66) —
  **no edge on this universe; the earlier 3-ticker +0.33 pilot is contradicted and
  must not be quoted.** Log: `scripts/_watchlist_backtest_v2.log`
- Authoritative docs to read: `README.md`, `PROJECT_STATUS.md`, `HANDOFF.md`, `NEXT_SESSION.md`

## How to run it (do NOT use run.bat)
```
cd c:\Users\marik\VSCode\quantanalyzer
.venv\Scripts\activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
First boot is slow (~25 heavy imports + db.init() at import time). Wait for
"Application startup complete." before hitting http://127.0.0.1:8000.

---

## What I want from you in this chat

**Step 1 — Actually inspect the project.** Read the code in `backend/analysis/`,
`backend/main.py`, and the frontend. Where you can, run the app and the smoke tests in
`scripts/` (or at least the backtest) so your review is grounded in what the code actually
does, not just the docs. Call out anywhere the docs and the code disagree.

**Step 2 — Honest scorecard.** Tell me, as a senior quant analyst would tell a PM —
honest about uncertainty, never overselling:
- **What I'm doing well** — the parts that are genuinely strong, methodologically sound, or
  professionally impressive.
- **What I'm doing poorly or naively** — statistical/methodological weaknesses (lookahead
  bias, overfitting, tiny sample sizes, questionable weightings, data-quality traps in
  yfinance), engineering smells, dead/duplicated code, missing tests, brittle failure modes,
  UX gaps. Be specific and cite `file:line`.
- **Reality check on the "institutional-grade" framing** — where it truly is, and where it's
  currently a demo dressed up as one.
- **Gap analysis vs. the expanded vision** — measure the current app against the FactSet-style
  product I described (deep fundamentals, financial news, historical "what-if" performance,
  paper trading, education layer). What already exists and can be reused, what's missing, and
  which gaps are realistic on a yfinance-only / ~$100 budget vs. which genuinely need a
  paid data feed.

**Step 3 — A new plan for a $0–$100 budget toward the expanded vision.** Assume I can spend
**at most ~$100 total** (not the larger funded roadmap in HANDOFF). Give me a prioritized,
phased plan that maximizes usefulness and credibility per dollar and moves the app toward the
FactSet-style learning platform I described. For anything that costs money, list the exact
item, the price, and why it beats the free alternative. Cover at least:
- **$0 improvements** — the highest-ROI things I can do with no spend: rigor fixes (walk-forward
  / out-of-sample validation, benchmarking vs. SPY, lookahead-bias audit), data hardening,
  a single test runner, bug fixes — AND cheap-to-build new features that yfinance already
  supports: a **historical "what-if" / growth-of-$10k** tool, a **paper-trading** portfolio
  (SQLite-backed), a **news** panel from yfinance, and an **education/glossary** layer.
- **Cheap paid upgrades under ~$100** — e.g. a low-cost fundamentals/news data feed (compare
  options like Financial Modeling Prep, Alpha Vantage, Finnhub, Polygon free/starter tiers,
  Tiingo, Marketstack — with real prices), a small LLM API credit budget to power the
  thesis/report/education narrative, and cheap hosting. Rank them and tell me which single
  ~$100 spend gives the biggest lift toward the vision.
- **Data-source guidance** — be explicit about what yfinance can and cannot do for the FactSet-
  style features (deep fundamentals, estimates, news breadth), and which specific paid tier
  closes the most important gaps cheapest.
- **A concrete, ordered sprint list** — feature-by-feature / module-by-module, each item small
  enough to build, test, and approve in one sitting (that's how I work). Note which items are
  reuse vs. net-new, and sequence paper-trading, what-if, news, and the education layer sensibly.

**Step 4 — Ask me before big changes.** Don't rewrite existing modules or restructure the
repo without my approval. Adding new files is fine; modifying `main.py`, `data.py`, or
`signals.py` needs my sign-off first. Start by presenting the scorecard and the plan, then let
me pick what we tackle first.

End with a short recommendation: **if I only do three things next, what are they?**
