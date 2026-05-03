# QuantAnalyzer — Project Handoff & Funding Brief

> **Purpose of this document:** A complete, self-contained briefing on QuantAnalyzer that can be pasted into a new Claude chat (or shared with a faculty advisor, fund officer, or sponsor) so the reader has full context on what was built, why, what's next, and how a $500–$1,000 budget should be deployed to maximize impact.
>
> **Author / owner:** Fox Fund member (student-managed investment fund), building this as a personal institutional-grade research platform.
> **Repo location (local):** `c:\Users\marik\VSCode\quantanalyzer`
> **Stack:** FastAPI (async) · yfinance · pandas / numpy / scipy · scikit-learn · hmmlearn · ripser · umap-learn · arch · vaderSentiment · vanilla JS + Plotly · SQLite · ReportLab (PDF)
> **Constraints:** Windows host, no C++ toolchain, yfinance only (no paid API keys), incremental build (one module at a time, tested before moving on).

---

## 1. Elevator pitch

QuantAnalyzer is a single-developer, institutional-style equity research platform. You enter a ticker and it produces a full multi-factor diagnostic — trend, momentum, regime (HMM), spectral cycles, topological persistence, manifold structure, stress/VaR, peer relative-value, news sentiment, a unified Quant Score, a DCF/valuation triangulation, catalyst calendar, written long/short thesis, speaker-prep Q&A, a markdown research note, and a Fox-Fund-ready pitch-deck PDF.

It is built to feel like the kind of tool a junior analyst at a top hedge fund would want on their desk: every quant output is paired with a plain-English explanation that's honest about uncertainty and never oversells a signal.

---

## 2. What has actually been built (verified against the current code)

### 2.1 Backend — quant + research modules

All modules live under [backend/analysis/](backend/analysis/) and have their own FastAPI endpoint in [backend/main.py](backend/main.py). Each module also has a smoke-test script in [scripts/](scripts/).

**Phase 1 — institutional quant stack (9 modules, all shipped):**

| # | Module | File | Endpoint |
|---|--------|------|----------|
| 1 | Advanced statistics (skew/kurt/VaR/CVaR/z-scores) | [statistics.py](backend/analysis/statistics.py) | `/api/advanced-stats/{ticker}` |
| 2 | Spectral analysis (FFT periodogram, dominant cycles, wavelets) | [spectral.py](backend/analysis/spectral.py) | `/api/spectral/{ticker}` |
| 3 | HMM regime classification (hmmlearn) | [regime_hmm.py](backend/analysis/regime_hmm.py) | `/api/regime-hmm/{ticker}` |
| 4 | Topological data analysis (ripser persistence diagrams) | [topology.py](backend/analysis/topology.py) | `/api/topology/{ticker}` |
| 5 | Manifold learning (UMAP / Isomap / kmapper) | [manifold.py](backend/analysis/manifold.py) | `/api/manifold/{ticker}` |
| 6 | Risk / stress framework (historical + parametric VaR, fan charts, GARCH via `arch`) | [risk_framework.py](backend/analysis/risk_framework.py) | `/api/risk-framework/{ticker}` |
| 7 | Peer relative-value matrix | [peers.py](backend/analysis/peers.py) | `/api/peers/{ticker}` |
| 8 | News sentiment (yfinance `Ticker.news` + VADER) | [sentiment.py](backend/analysis/sentiment.py) | `/api/sentiment/{ticker}` |
| 9 | Quant Score aggregator (combines 1–8 into one composite) | [quant_score.py](backend/analysis/quant_score.py) | `/api/quant-score/{ticker}` |

**Phase 2 — research tooling (all shipped):**

| Module | File | Endpoint |
|--------|------|----------|
| DCF / valuation triangulation | [valuation.py](backend/analysis/valuation.py) | `/api/valuation/{ticker}` |
| Catalyst tracker (earnings, ex-div, analyst events) | [catalyst.py](backend/analysis/catalyst.py) | `/api/catalyst/{ticker}` |
| Long/short thesis generator | [thesis.py](backend/analysis/thesis.py) | `/api/thesis/{ticker}` |
| Speaker prep / anticipated PM Q&A pack | [speaker_prep.py](backend/analysis/speaker_prep.py) | `/api/speaker-prep/{ticker}` |
| Full sell-side-style research note | [report_writer.py](backend/analysis/report_writer.py) | `/api/report/{ticker}` |
| Pitch deck PDF (ReportLab) | [pitch_deck.py](backend/analysis/pitch_deck.py) | `/api/pitch-deck/{ticker}` |

**Legacy modules preserved (intentionally not rewritten):** [indicators.py](backend/analysis/indicators.py), [signals.py](backend/analysis/signals.py), [regime.py](backend/analysis/regime.py), [distribution.py](backend/analysis/distribution.py), [risk.py](backend/analysis/risk.py), [backtest.py](backend/analysis/backtest.py), [report.py](backend/analysis/report.py), [data.py](backend/analysis/data.py).

**Total:** ~10,000 lines across backend + frontend.

### 2.2 Infrastructure

- **DB layer:** [backend/db.py](backend/db.py) — SQLite for the editable watchlist (default: ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS).
- **Cache layer:** [backend/cache.py](backend/cache.py) — 15-minute disk cache so repeat lookups are instant and we don't hammer Yahoo.
- **Watchlist endpoints:** `/api/watchlist`, `/api/watchlist/{ticker}`, `/api/watchlist/scan` (ranks the whole list by Quant Score).
- **Run scripts:** [run.bat](run.bat) / [run.sh](run.sh); deployable to Render free tier via [render.yaml](render.yaml) and [Procfile](Procfile).

### 2.3 Frontend

- Tabbed dark-mode UI in [frontend/index.html](frontend/index.html) (~545 lines) and [frontend/app.js](frontend/app.js) (~1,174 lines).
- Plotly charts wired across tabs (price/MA/Bollinger, regime ribbon, spectral periodogram, manifold scatter, stress fan chart, peer matrix).
- Legacy single-page UI preserved as `index.legacy.html` / `app.legacy.js` for diff/reference.

### 2.4 Design principles already baked in

- **Plain-English explanations** alongside every quant output — written the way a senior quant would explain to a PM.
- **Honest about uncertainty** — never overselling signals.
- **Pure-Python or wheel-only deps** — works on a Windows machine with no compiler.
- **Approval-gated incremental build** — modules added one at a time, smoke-tested before the next lands.

---

## 3. How to run it (verified)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& c:\Users\marik\VSCode\quantanalyzer\.venv\Scripts\Activate.ps1
cd c:\Users\marik\VSCode\quantanalyzer
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000. First boot is slow because `main.py` imports ~25 analysis modules and runs `db.init()` at import time — the dashboard returns ERR_CONNECTION_REFUSED until "Application startup complete." prints in the terminal. Once warm, repeat ticker lookups are sub-second thanks to the 15-min disk cache.

---

## 4. Why this matters / why it's different

### 4.1 The problem

Student-managed funds (and most retail-adjacent shops) live in a gap:

- **Free tools (Yahoo, Finviz, TradingView, Seeking Alpha)** give you charts and basic ratios but no rigorous quant diagnostics, no regime detection, no stress framework, no usable DCF.
- **Institutional tools (Bloomberg, FactSet, S&P CapIQ, Sentieo)** give you everything but cost $20k–$30k per seat per year and assume you already know what you're looking at.
- **Quant libraries (QuantConnect, Quantopian-era stuff, zipline, vectorbt)** are powerful but are research engines, not research *products*. They don't write the pitch.

Fox Fund analysts — and student analysts everywhere — need something in the middle: real institutional rigor, but explained, packaged, and ready to defend in a stock pitch.

### 4.2 What QuantAnalyzer does that the alternatives don't

1. **Multi-paradigm quant under one roof.** TDA + HMM regimes + spectral + manifold + GARCH stress is not something you find in one place outside of a hedge fund desk. Most retail tools stop at RSI/MACD.
2. **Every output is paired with plain-English interpretation.** This is the core differentiator. We're not selling numbers, we're selling understanding.
3. **End-to-end: data → diagnostics → thesis → speaker prep → pitch deck PDF.** The output of the platform is a *defendable stock pitch*, not a screenshot.
4. **Honest uncertainty.** Most retail-grade tools (and a worrying amount of fintwit) sell signals as if they're facts. Every module here is built to expose confidence, sample size, and regime-dependence.
5. **Reproducible & open-source-friendly stack.** No paid API keys. Anyone can fork it, every signal is auditable.

### 4.3 Why this matters for research

- **Educational leverage:** every Fox Fund analyst can see *how* a regime model or a persistence diagram is built, not just consume the output.
- **Cross-sectional research:** the watchlist scan is a starting point for systematic studies (factor premia, regime-conditioning, sector rotation).
- **Reproducibility:** because it's code, you can replay any pitch from any date range and audit it.

---

## 5. The funding ask & how to spend $500–$1,000

The current build is the MVP. The funds turn it from "personal research tool" into "a thing other Fox Fund members can actually use, that holds up against commercial alternatives." Here are two budget profiles depending on how the money lands.

### 5.1 $500 budget — "Make it real and shareable"

Goal: Get it deployed reliably, fix the data ceiling, and make it usable by other Fox Fund members without setup.

| Item | Cost | Why |
|------|------|-----|
| Render (or Railway / Fly.io) — paid tier, 1 yr | ~$84 | Eliminate 30s cold starts on free tier; run with persistent disk for cache and SQLite. |
| Domain (`foxfundresearch.com` or similar), 1 yr | ~$15 | Credibility — easier to share, looks like a product. |
| **Polygon.io Starter or Financial Modeling Prep**, 1 yr | ~$120–$180 | yfinance is the **single biggest risk factor** in the stack — it's an unofficial scrape that breaks ~quarterly. Paid feed = real fundamentals, real intraday, real options data. |
| **Anthropic / OpenAI API credits** | ~$100 | Plug an LLM into `thesis.py` and `report_writer.py` to upgrade the templated text into genuinely sharp narrative. This is a *huge* qualitative jump for very little money. |
| Reserve for compute spikes / 2026 surprises | ~$80 | Don't spend the whole budget on day one. |
| **Total** | **~$400–$460** | Leaves 10–20% slack. |

Outcome: a hosted, branded, always-on tool with real fundamentals and LLM-quality thesis writing.

### 5.2 $1,000 budget — "Make it competitive with paid platforms"

Everything in the $500 plan, plus:

| Item | Cost | Why |
|------|------|-----|
| **Polygon.io Developer plan** (full options, 5yr history, real-time) | ~$348 | Real options surface lets us add IV-rank, skew, and event-vol modules — territory most retail tools never touch. |
| **FRED Pro / Macro data** (or premium fundamentals like SimFin, EOD HD) | ~$120 | Macro overlays for the regime and stress modules. Currently we only have price-derived regimes — adding macro factors is a huge step up. |
| LLM API credits — bigger budget | ~$200 | Enough headroom to LLM-power thesis, report, *and* speaker-prep — and to run nightly summaries across the whole watchlist. |
| Lightweight UI polish (Figma + freelancer or Tailwind redesign) | ~$100 | First impressions when pitching to faculty / sponsors. |
| One-time: 2 books — *Active Portfolio Management* (Grinold/Kahn), *Advances in Financial ML* (López de Prado) | ~$80 | Direct inputs to v2 features (factor portfolios, meta-labeling). |
| Reserve | ~$150 | Same as above, don't burn it on day one. |
| **Total** | **~$1,000** | Fully allocated. |

Outcome: real institutional data feeds, LLM-grade narrative, polished UI, hosted permanently — the gap between QuantAnalyzer and a paid platform shrinks dramatically.

### 5.3 What I would *not* spend money on

- **A vector database / RAG infra.** Premature; we don't have enough proprietary documents yet.
- **GPU compute.** Nothing in the stack needs it at this scale.
- **A dedicated DB host.** SQLite is fine until we have dozens of users.
- **Marketing / paid promotion.** This is a research tool inside Fox Fund, not a SaaS launch.

---

## 6. Project plan — next 90 days

Assumes ~5–8 hours/week of student time and the funding above.

### Sprint 1 (weeks 1–2) — Stabilize

- Move from yfinance to a paid feed (Polygon or FMP). Keep yfinance as a fallback layer in [data.py](backend/analysis/data.py).
- Deploy to Render paid tier; set up domain + HTTPS.
- Add basic auth (single shared password) so it can be linked from a Fox Fund Slack/Discord.

### Sprint 2 (weeks 3–4) — LLM upgrade

- Wire Claude (or GPT) into [thesis.py](backend/analysis/thesis.py), [report_writer.py](backend/analysis/report_writer.py), and [speaker_prep.py](backend/analysis/speaker_prep.py).
- The quant modules already produce structured JSON — feed that JSON in as the "source of truth" and use the LLM purely for narrative.
- This is the single highest-ROI change available. Templates currently feel like Mad Libs; LLM-written narrative built on real numbers reads like a junior analyst's first draft.

### Sprint 3 (weeks 5–6) — Macro & options

- Add a macro module (FRED / fundamentals): yield curve, ISM, credit spreads — overlay onto the HMM regime to produce a "macro-conditional regime."
- Add an options module (IV rank, skew, term structure, event-vol pricing) — possible only with the paid feed.

### Sprint 4 (weeks 7–8) — Cross-sectional & factor

- Watchlist-level scans become real: factor exposures, peer rank tables, sector rotation snapshots.
- Build a "Fox Fund book" view that aggregates everyone's tickers into one portfolio dashboard.

### Sprint 5 (weeks 9–12) — Polish & defend

- UI redesign pass.
- Backtest harness for the Quant Score itself — does the composite actually predict forward returns over the watchlist? This is what makes the platform *defensible*: not "we have features," but "here's the IR."
- Demo session for Fox Fund leadership.

---

## 7. Risks & honest weaknesses

I want a future Claude (and any reader of this brief) to know what's *not* great yet:

1. **yfinance is fragile.** It's the foundation, and it's also the single biggest risk. Funded version replaces this.
2. **Templated narrative.** Current thesis / report writers stitch sentences from data — they don't *write*. LLM upgrade fixes this.
3. **No proper backtest of the composite Quant Score.** Each module has been tested individually, but the aggregator hasn't been validated on forward returns. This is the most important *credibility* gap.
4. **No options data.** The risk and stress framework is price-only.
5. **Single-user tool.** No accounts, no per-user state, no audit trail.
6. **HMM and TDA are powerful but easy to over-interpret.** The plain-English layer helps, but the interpretation guardrails could be tighter.
7. **No live integration tests in CI.** Smoke test scripts exist under [scripts/](scripts/) but they're run manually.

---

## 8. How to brief a new Claude chat with this project

If you paste this document into a new Claude chat, also tell it:

1. **Project lives at** `c:\Users\marik\VSCode\quantanalyzer` on Windows.
2. **Build style:** one module at a time, smoke-test it, ask for approval before modifying [main.py](backend/main.py) / [data.py](backend/analysis/data.py) / [signals.py](backend/analysis/signals.py).
3. **Constraints:** yfinance only (until funded), no C++ toolchain, pure-Python or wheel-only.
4. **Voice:** plain-English, senior-quant-talking-to-a-PM, never oversell a signal.
5. **Default watchlist:** ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS.
6. **Run command:** activate `.venv`, then `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload`. Startup is slow (~25 modules import).

The current state file is [PROJECT_STATUS.md](PROJECT_STATUS.md) (note: that file is from 2026-04-24 and slightly out of date — Phase 2 modules and the frontend overhaul are now complete; this HANDOFF supersedes it).

---

## 9. One-paragraph summary for a sponsor / faculty advisor

QuantAnalyzer is a working institutional-style equity research platform built by a Fox Fund member as a personal project. It already produces multi-paradigm quant diagnostics (HMM regimes, topological persistence, spectral cycles, manifold learning, GARCH stress, peer relative-value, news sentiment) plus a unified Quant Score, DCF triangulation, catalyst calendar, written thesis, anticipated PM Q&A, sell-side-style research note, and a pitch-deck PDF — every output paired with plain-English interpretation. With $500–$1,000, the next step is to replace the unofficial yfinance feed with a paid market-data subscription, plug an LLM into the thesis / report / speaker-prep layer, deploy it as a hosted tool the rest of the fund can use, and build a backtest of the composite signal so the platform's predictions can be validated on forward returns. The bet is simple: every Fox Fund analyst should walk into a pitch with a defendable, quant-backed thesis — and the only place to get that today costs $25,000 a year.
