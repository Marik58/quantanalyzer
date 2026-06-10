# QuantAnalyzer — Next Session Handoff

> Paste this whole file (or point Claude at it) at the start of a new chat.
> It contains everything a fresh Claude needs to be useful immediately.

**Last updated:** 2026-06-09

---

## Who I am / what this project is

I'm a Fox Fund member building **QuantAnalyzer**, a single-developer
institutional-style equity research platform. Enter a ticker → get a multi-paradigm
quant diagnostic plus a defendable written stock pitch, every output paired with
plain-English explanation.

Project root: `c:\Users\marik\VSCode\quantanalyzer`

## Read these first (authoritative)

- [`README.md`](README.md) — product overview + run instructions
- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — short DONE / TO DO snapshot
- [`HANDOFF.md`](HANDOFF.md) — full project brief and 90-day roadmap

## Constraints (do not violate)

- **Data vendor: yfinance only** — no paid API keys
- **Windows host, no C++ toolchain** — every dep must ship wheels or be pure Python
- **Build incrementally** — one module at a time, test/approve before moving on
- **Default watchlist:** ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS

## How to run (do **not** use `run.bat`)

```bash
cd quantanalyzer
.venv\Scripts\activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

First boot is slow (~25 heavy imports + `db.init()` at import time). Wait for
`Application startup complete.` in the terminal before hitting
http://127.0.0.1:8000 — the dashboard returns ERR_CONNECTION_REFUSED until then.

---

## Where things stand — DONE

### Phase 0 — Scaffolding
`requirements.txt`, folder layout, `run.bat`/`run.sh`, DB + cache layer
([backend/db.py](backend/db.py), [backend/cache.py](backend/cache.py)),
Render deploy config ([render.yaml](render.yaml), [Procfile](Procfile)).

### Phase 1 — 9 backend quant modules

| # | Module | File | Endpoint |
|---|---|---|---|
| 1 | Advanced statistics | [statistics.py](backend/analysis/statistics.py) | `/api/advanced-stats/{ticker}` |
| 2 | Spectral analysis | [spectral.py](backend/analysis/spectral.py) | `/api/spectral/{ticker}` |
| 3 | HMM regime | [regime_hmm.py](backend/analysis/regime_hmm.py) | `/api/regime-hmm/{ticker}` |
| 4 | Topology (TDA) | [topology.py](backend/analysis/topology.py) | `/api/topology/{ticker}` |
| 5 | Manifold learning | [manifold.py](backend/analysis/manifold.py) | `/api/manifold/{ticker}` |
| 6 | Risk / stress framework | [risk_framework.py](backend/analysis/risk_framework.py) | `/api/risk-framework/{ticker}` |
| 7 | Peers | [peers.py](backend/analysis/peers.py) | `/api/peers/{ticker}` |
| 8 | News sentiment | [sentiment.py](backend/analysis/sentiment.py) | `/api/sentiment/{ticker}` |
| 9 | Quant Score aggregator | [quant_score.py](backend/analysis/quant_score.py) | `/api/quant-score/{ticker}` |

### Phase 2 — 6 research tools

| Module | File | Endpoint |
|---|---|---|
| DCF / valuation triangulation | [valuation.py](backend/analysis/valuation.py) | `/api/valuation/{ticker}` |
| Catalyst tracker | [catalyst.py](backend/analysis/catalyst.py) | `/api/catalyst/{ticker}` |
| Long/short thesis generator | [thesis.py](backend/analysis/thesis.py) | `/api/thesis/{ticker}` |
| Speaker prep / PM Q&A | [speaker_prep.py](backend/analysis/speaker_prep.py) | `/api/speaker-prep/{ticker}` |
| Full sell-side report writer | [report_writer.py](backend/analysis/report_writer.py) | `/api/report/{ticker}` |
| Pitch deck PDF (ReportLab) | [pitch_deck.py](backend/analysis/pitch_deck.py) | `/api/pitch-deck/{ticker}` |

### Phase 3 — Frontend overhaul
Tabbed dark-mode UI in [frontend/index.html](frontend/index.html) (~545 lines)
and [frontend/app.js](frontend/app.js) (~1,174 lines). Plotly across every tab
(price/MA/Bollinger, regime ribbon, spectral periodogram, manifold scatter, stress
fan chart, peer matrix). Watchlist scan view at `/api/watchlist/scan`. Legacy
single-page UI preserved as `index.legacy.html` / `app.legacy.js`.

### Sprint extra — Quant Score backtest
[score_backtest.py](backend/analysis/score_backtest.py), endpoint
`/api/score-backtest`, test [test_score_backtest.py](scripts/test_score_backtest.py).
Covers the **price-derived ~65% of Quant Score weight** (technical + regime +
statistics + spectral + topology). Peer/valuation, sentiment, and risk_framework
excluded — yfinance can't supply them point-in-time without lookahead bias.

**Initial 3-ticker run (AAPL/MSFT/NVDA):** IR ≈ +0.33, pooled IC ≈ +0.19,
long hit-rate 64%.

### Legacy modules — preserved, intentionally not rewritten
[indicators.py](backend/analysis/indicators.py),
[signals.py](backend/analysis/signals.py),
[regime.py](backend/analysis/regime.py),
[distribution.py](backend/analysis/distribution.py),
[risk.py](backend/analysis/risk.py),
[backtest.py](backend/analysis/backtest.py),
[report.py](backend/analysis/report.py),
[data.py](backend/analysis/data.py).

---

## TO DO — next sprint (no funding required)

1. **Run the full-watchlist backtest** — `python scripts/test_score_backtest.py --watchlist` to get the headline IR/IC across all 14 tickers.
2. **LLM hook stubs** — wire `ANTHROPIC_API_KEY` env-var checks into [thesis.py](backend/analysis/thesis.py), [report_writer.py](backend/analysis/report_writer.py), [speaker_prep.py](backend/analysis/speaker_prep.py). Templates fall back when key is missing; LLM-grade narrative the moment a key is set.
3. **Harden [data.py](backend/analysis/data.py) against yfinance breakage** — wrap Yahoo calls in try/except with clear error surfaces; log missing fields so silent breakage stops happening.
4. **Single-command test runner** — combine the 18 separate `scripts/test_*.py` smoke tests into one `scripts/run_all_tests.py`.

Funded next steps (Polygon/FMP feed, hosted deploy, LLM credits) are in [HANDOFF.md §5](HANDOFF.md).

---

## How Quant Score works (for the new Claude's context)

Composite of 8 components, each mapped to a directional score in **[-100, +100]**, weighted sum produces verdict. Defined in [quant_score.py](backend/analysis/quant_score.py).

| Component | Weight | Source module |
|---|---|---|
| Technical | 0.25 | [signals.py](backend/analysis/signals.py) — trend + momentum + relative strength |
| Regime | 0.20 | [regime_hmm.py](backend/analysis/regime_hmm.py) — 4-state Gaussian HMM on (trend, vol) |
| Valuation | 0.15 | [peers.py](backend/analysis/peers.py) — multiples vs curated peer cohort |
| Sentiment | 0.10 | [sentiment.py](backend/analysis/sentiment.py) — VADER over yfinance headlines |
| Statistics | 0.10 | [statistics.py](backend/analysis/statistics.py) — Sortino via `tanh(s/1.5)*100` |
| Spectral | 0.05 | [spectral.py](backend/analysis/spectral.py) — FFT dominant-cycle phase |
| Topology | 0.05 | [topology.py](backend/analysis/topology.py) — TDA cyclicity × mean-reversion sign |
| Risk | 0.10 | [risk_framework.py](backend/analysis/risk_framework.py) — VaR/CVaR/Kelly → penalty |

**Verdict:** `>+60` Strong Buy · `>+30` Buy · `[-30,+30]` Hold · `[-60,-30)` Reduce · `<-60` Avoid.

**Graceful degradation:** if a module fails, its weight is dropped and the rest are renormalized — a missing module never flips the sign.

**Conflict flags** (see [quant_score.py:271-329](backend/analysis/quant_score.py#L271-L329)) catch named contradictions a PM would want surfaced — e.g. strong tech + rich valuation (mean-reversion risk), cheap + disliked (deep-value setup), strong tech in Volatile regime (discount the signal), etc.

---

## Context from previous chat

Last conversation was a strategy discussion, **not code work**:
1. Walked through how Quant Score works (the table above) and the per-module logic
2. Compared QuantAnalyzer's active-research approach to Wealthfront's passive/MPT robo-advisor model — almost opposite ends of the investing spectrum; QA is for active security selection, Wealthfront is for diversified passive allocation with tax-loss harvesting

No code changed. `PROJECT_STATUS.md` is still current.

---

## Today I want to:

<!-- Fill this in with whichever TO DO or new task you want to tackle -->
