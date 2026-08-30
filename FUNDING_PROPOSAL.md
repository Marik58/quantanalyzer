# QuantAnalyzer — Funding Proposal

**Submitted by:** Marik Apol-Murphy, Fox Fund member
**Contact:** marik.j.apolmurphy@gmail.com
**Date:** June 2026
**Request:** $500 – $1,000 in one-time funding
**Repository:** https://github.com/ (private, available on request) — local path `c:\Users\marik\VSCode\quantanalyzer`

---

## 1. Executive summary

QuantAnalyzer is a working, institutional-style equity research platform I have built independently over the past several months as a Fox Fund member. A user enters a ticker and receives a multi-paradigm quantitative diagnostic — hidden-Markov regime classification, spectral cycle decomposition, topological persistence, manifold learning, GARCH-based stress framework, peer relative-value, sentiment, and a unified Quant Score — followed by a DCF triangulation, catalyst calendar, written long/short thesis, anticipated PM Q&A, a sell-side-style research note, and a pitch-deck PDF. Every quantitative output is paired with a plain-English explanation.

The MVP is complete: ~14,000 lines of Python and JavaScript, 15 production modules, and a point-in-time backtest harness for the price-derived portion of the composite signal. I want to be direct about what that harness found: on the full 14-ticker watchlist (518 ticker-month observations, 2023–2026), the composite score shows **no predictive edge** — annualized information ratio ≈ −0.38, mean cross-sectional IC ≈ −0.03 (t = −0.66), statistically indistinguishable from zero. An earlier three-ticker pilot had shown IR ≈ +0.33; the swing between the two runs is itself the finding — on a small, single-sector, survivorship-biased universe the statistic is dominated by sampling noise, so *neither* number is meaningful. That is exactly why this funding matters: a defensible backtest requires a broad, diverse, point-in-time universe, which the free data feed cannot supply. With a one-time grant of $500 – $1,000, the platform moves from "personal research tool" to "shared infrastructure that Fox Fund analysts and finance students can actually use," and crosses a clear academic threshold: a defensible backtest of every signal against a real, point-in-time fundamentals feed.

---

## 2. The problem

Student-managed investment funds operate in a structural gap between two tiers of tooling:

- **Retail tools** (Yahoo Finance, Finviz, TradingView, Seeking Alpha) give charts and basic ratios but no rigorous quantitative diagnostics — no regime detection, no stress framework, no usable DCF.
- **Institutional terminals** (Bloomberg, FactSet, S&P CapIQ) provide everything but cost roughly $20,000 – $30,000 per seat per year, and assume the user already knows what they are looking at.
- **Quant research libraries** (zipline, vectorbt, QuantConnect) are powerful research *engines* but are not research *products* — they do not produce a defendable, narratable thesis.

Student analysts therefore either pitch with shallow technicals or borrow institutional terminals during limited windows of access. Neither path teaches the underlying methods.

## 3. What I have built

All code is the product of approximately five months of incremental, test-driven development. Modules were shipped one at a time, smoke-tested, and only then integrated.

### 3.1 Quantitative modules (Phase 1 — complete)

| # | Module                              | Method                                                       |
|---|-------------------------------------|--------------------------------------------------------------|
| 1 | Advanced statistics                 | Skew, kurtosis, VaR, CVaR, z-scores                          |
| 2 | Spectral analysis                   | FFT periodogram, dominant cycles, wavelet decomposition      |
| 3 | HMM regime classification           | `hmmlearn` — bull / bear / chop with state probabilities     |
| 4 | Topological data analysis           | `ripser` persistence diagrams over price embeddings          |
| 5 | Manifold learning                   | UMAP / Isomap on the return surface                          |
| 6 | Risk and stress framework           | Historical + parametric VaR, GARCH vol forecast, fan chart   |
| 7 | Peer relative-value matrix          | Sector cohort multiples                                      |
| 8 | News sentiment                      | VADER over Yahoo headline stream                             |
| 9 | Composite Quant Score               | Weighted aggregator with conflict flags and confidence       |

### 3.2 Research tooling (Phase 2 — complete)

DCF / valuation triangulation, catalyst tracker, long/short thesis generator, anticipated PM Q&A pack, full sell-side-style research note, and a ReportLab pitch-deck PDF.

### 3.3 Infrastructure

FastAPI backend with ~25 endpoints, SQLite watchlist, 15-minute disk cache, tabbed dark-mode dashboard with Plotly across every tab, and a watchlist-scan endpoint that ranks the entire list by Quant Score.

### 3.4 Backtest results (full watchlist — honest read)

A point-in-time backtest of the price-derived portion of the Quant Score (≈65% of the composite weight: technical + regime + statistics + spectral + topology) across all **14 watchlist tickers** — 518 ticker-month observations, 37 monthly rebalances, 21-trading-day forward window, 2023-05 → 2026-05 — produced:

- Annualized information ratio ≈ **−0.38**
- Mean monthly cross-sectional IC ≈ **−0.034** (t = −0.66 — indistinguishable from zero)
- Pooled IC ≈ **+0.010**; long hit rate 56%, short hit rate 46%
- Quintile forward returns are non-monotonic and inverted at the extremes: the lowest-scored quintile returned **+3.19%** per period vs **+0.88%** for the highest-scored

**The score, as currently weighted, shows no predictive edge on this universe — and I present that openly rather than quoting the earlier three-ticker pilot (IR ≈ +0.33), which the full run contradicts.** The instability between the two runs demonstrates the core statistical problem: fourteen highly-correlated mega-cap survivors are effectively one factor bet, so the true sample is closer to 37 months than 518 observations, and any IC estimate is noise-dominated. A companion per-ticker timing test tells the same story — the signal-timed strategy trails SPY on 11 of 14 names (mean alpha ≈ −22%).

Separately, the fundamentally-derived components (peers/valuation, sentiment, risk_framework) remain excluded because the free data feed cannot supply them point-in-time without lookahead bias. **Producing a defensible backtest — a broad, diverse, survivorship-free universe scored against a real point-in-time fundamentals feed — is one of the central goals of the proposed funding.** The infrastructure (walk-forward harness, per-component attribution, quintile/IC reporting) is built and tested; what it needs is data worthy of it.

---

## 4. Why this is worth funding

### 4.1 Educational value

QuantAnalyzer is unusual in that every advanced method — HMM regimes, topological persistence, manifold embeddings, GARCH stress, spectral cycles — comes with a plain-English layer written the way a senior quant would explain it to a portfolio manager. A Fox Fund analyst can both *see* the output and *understand how it was built*. Each module is a self-contained Python file under 500 lines, so the platform doubles as a reading list for students who want to learn the methods themselves.

### 4.2 Institutional capability without institutional cost

With funded data and a small LLM budget, the platform produces output that overlaps meaningfully with what a $25,000 / year Bloomberg seat delivers for a single analyst's research workflow. The cost ratio is roughly 25:1 in favour of the funded student build.

### 4.3 Reproducibility and academic auditability

Because every signal is code and every input is timestamped, any pitch produced by the platform can be replayed from any historical date and audited. This is the property that separates research from storytelling, and it is the property most retail tools lack.

### 4.4 Direct benefit to Fox Fund and to the finance program

Funded, the platform becomes a shared resource: any Fox Fund member can produce a quant-backed thesis without needing to set up a Python environment. It also produces classroom-friendly artefacts — annotated regime ribbons, persistence diagrams, fan charts — that can be used in coursework on portfolio theory, quantitative methods, or financial econometrics.

---

## 5. Use of funds

I am presenting two budget profiles. The $500 profile is the minimum needed to cross the credibility threshold; the $1,000 profile produces a platform competitive with paid commercial tools for the specific use case of single-analyst equity pitches.

### 5.1 $500 — "Make it real and shareable"

| Item                                                        | Cost     | Justification                                                                                          |
|-------------------------------------------------------------|----------|--------------------------------------------------------------------------------------------------------|
| Paid market-data feed (Polygon.io Starter or FMP), 1 yr     | $120–$180 | Replaces the unofficial `yfinance` scrape, which breaks roughly quarterly. Enables a clean backtest.   |
| LLM API credits (Anthropic or OpenAI)                       | ~$100    | Upgrades the thesis, report, and speaker-prep writers from templated text to genuinely sharp narrative. |
| Hosted deployment (Render or Railway paid tier), 1 yr       | ~$84     | Eliminates 30-second cold starts; provides a persistent URL Fox Fund members can use without setup.    |
| Domain registration, 1 yr                                   | ~$15     | Credibility and shareability.                                                                          |
| Reserve for compute spikes                                  | ~$80     | Avoids spending the entire budget on day one.                                                          |
| **Total**                                                   | **~$400–$460** | Leaves 10–20% slack.                                                                                |

**Outcome:** a hosted, branded, always-on tool with real fundamentals, LLM-grade thesis writing, and the first full-watchlist backtest on point-in-time data.

### 5.2 $1,000 — "Make it competitive with paid platforms"

Everything in §5.1, plus:

| Item                                                                | Cost     | Justification                                                                                          |
|---------------------------------------------------------------------|----------|--------------------------------------------------------------------------------------------------------|
| Polygon.io Developer plan (full options chain, 5-year history)      | ~$348    | Enables an IV-rank, skew, and event-vol module — territory most retail tools never touch.              |
| Macro feed (FRED Pro or premium fundamentals such as SimFin / EOD HD) | ~$120  | Macro overlay on the regime model — turns price-only regimes into macro-conditional regimes.           |
| Expanded LLM budget                                                 | ~$200    | Nightly LLM summaries across the full watchlist; sharper thesis and Q&A generation.                    |
| Lightweight UI design pass                                          | ~$100    | First impressions matter when presenting to faculty, sponsors, or fund leadership.                     |
| Reference texts: *Active Portfolio Management* (Grinold/Kahn), *Advances in Financial ML* (López de Prado) | ~$80 | Direct inputs to v2 features (factor portfolios, meta-labeling).                                      |
| Reserve                                                             | ~$150    | Same rationale as above.                                                                               |
| **Total**                                                           | **~$1,000** | Fully allocated.                                                                                    |

### 5.3 What I would explicitly *not* spend money on

- GPU compute (nothing in the stack requires it at this scale).
- Vector database or RAG infrastructure (premature — no proprietary document corpus yet).
- Dedicated database hosting (SQLite is sufficient until there are dozens of concurrent users).
- Marketing or paid promotion (this is a research tool inside Fox Fund, not a commercial launch).

---

## 6. Project plan — next 90 days

Assumes ~5 – 8 hours per week of student time and the funding above.

**Sprint 1 (weeks 1–2) — Stabilise.** Migrate from `yfinance` to a paid feed, retaining `yfinance` as a fallback. Deploy to a paid hosted tier with a custom domain and basic shared authentication.

**Sprint 2 (weeks 3–4) — LLM upgrade.** Wire an LLM into the thesis, report, and speaker-prep modules. The quantitative modules already produce structured JSON; the LLM consumes that JSON as ground truth and produces narrative on top. This is the single highest-ROI change available.

**Sprint 3 (weeks 5–6) — Macro and options.** Add a macro module (yield curve, ISM, credit spreads) layered onto the HMM regime. Add an options module (IV rank, skew, term structure, event-vol pricing) — feasible only with a paid feed.

**Sprint 4 (weeks 7–8) — Cross-sectional research.** Turn the watchlist scan into a real factor view: exposures, peer rank tables, sector rotation snapshots. Aggregate every Fox Fund analyst's tickers into one portfolio dashboard.

**Sprint 5 (weeks 9–12) — Polish and validate.** UI refinement pass. Run the full-watchlist backtest of the composite Quant Score on point-in-time data — this is the single most important credibility deliverable, because it answers the question "does the composite actually predict forward returns?" Present results to Fox Fund leadership.

---

## 7. Risks and honest limitations

The proposal is more credible if I name the platform's current weaknesses plainly:

1. **`yfinance` is the foundation, and it is fragile.** Replacing it is the single largest item in the budget for that reason.
2. **The current thesis and report writers are templated.** They stitch sentences from structured data. The LLM upgrade fixes this.
3. **The composite Quant Score has only a preliminary, three-ticker backtest.** Every individual module has been smoke-tested, but the aggregator has not been validated on the full watchlist with point-in-time data. This is the most important credibility gap, and the funded plan closes it explicitly in Sprint 5.
4. **No options data.** The risk and stress framework is price-only.
5. **HMM and topological methods are powerful but easy to over-interpret.** The plain-English layer mitigates this; it does not eliminate it.

---

## 8. Why support this now

The MVP works. The methodology is in place. The bottlenecks are no longer technical — they are data quality, narrative quality, and validation. All three are solved by money in amounts a research grant can comfortably absorb. A grant of $500 – $1,000 converts a personal project into a piece of shared infrastructure that benefits every analyst in Fox Fund, produces a defensible backtest suitable for academic presentation, and gives finance students at the university a practical introduction to modern quantitative methods that they would otherwise only encounter inside a hedge fund.

I am happy to demonstrate the platform live, walk through any module's code, share the current backtest results in full, or revise the budget against specific constraints.

Thank you for considering the proposal.

— Marik
