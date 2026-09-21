# QuantAnalyzer — Project Status

**Last updated:** 2026-05-09
**Goal:** Upgrade QuantAnalyzer from a basic signals/backtest app into an institutional-grade research platform for Fox Fund.

> For the full funding brief, sponsor pitch, and 90-day roadmap, see [HANDOFF.md](HANDOFF.md).
> This file is the short status snapshot — what's done, what's next.

**Constraints:**
- Data vendor: yfinance only (no paid API keys)
- Windows, no C++ toolchain — pure-Python or wheel-only deps
- Default watchlist: ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS
- Build incrementally — one module at a time, tested before moving on

---

## DONE

### Phase 0 — Scaffolding
- [x] `requirements.txt`
- [x] Folder layout: [backend/](backend/), [backend/analysis/](backend/analysis/), [frontend/](frontend/), [scripts/](scripts/), [data/](data/)
- [x] `run.bat` / `run.sh` launchers
- [x] DB + cache layer ([backend/db.py](backend/db.py), [backend/cache.py](backend/cache.py))
- [x] Render deploy config ([render.yaml](render.yaml), [Procfile](Procfile))

### Phase 1 — Backend quant modules (all 9 shipped)
Each lives in [backend/analysis/](backend/analysis/) with its own endpoint in [backend/main.py](backend/main.py) and a smoke-test script under [scripts/](scripts/).

| # | Module | File | Endpoint | Test |
|---|--------|------|----------|------|
| 1 | Advanced statistics | [statistics.py](backend/analysis/statistics.py) | `/api/advanced-stats/{ticker}` | [test_statistics.py](scripts/test_statistics.py) |
| 2 | Spectral analysis | [spectral.py](backend/analysis/spectral.py) | `/api/spectral/{ticker}` | [test_spectral.py](scripts/test_spectral.py) |
| 3 | HMM regime | [regime_hmm.py](backend/analysis/regime_hmm.py) | `/api/regime-hmm/{ticker}` | [test_regime_hmm.py](scripts/test_regime_hmm.py) |
| 4 | Topology (TDA) | [topology.py](backend/analysis/topology.py) | `/api/topology/{ticker}` | [test_topology.py](scripts/test_topology.py) |
| 5 | Manifold learning | [manifold.py](backend/analysis/manifold.py) | `/api/manifold/{ticker}` | [test_manifold.py](scripts/test_manifold.py) |
| 6 | Risk / stress framework | [risk_framework.py](backend/analysis/risk_framework.py) | `/api/risk-framework/{ticker}` | [test_risk_framework.py](scripts/test_risk_framework.py) |
| 7 | Peers | [peers.py](backend/analysis/peers.py) | `/api/peers/{ticker}` | [test_peers.py](scripts/test_peers.py) |
| 8 | News sentiment | [sentiment.py](backend/analysis/sentiment.py) | `/api/sentiment/{ticker}` | [test_sentiment.py](scripts/test_sentiment.py) |
| 9 | Quant Score aggregator | [quant_score.py](backend/analysis/quant_score.py) | `/api/quant-score/{ticker}` | [test_quant_score.py](scripts/test_quant_score.py) |

### Phase 2 — Research tooling (all 6 shipped)

| Module | File | Endpoint | Test |
|--------|------|----------|------|
| DCF / valuation triangulation | [valuation.py](backend/analysis/valuation.py) | `/api/valuation/{ticker}` | [test_valuation.py](scripts/test_valuation.py) |
| Catalyst tracker | [catalyst.py](backend/analysis/catalyst.py) | `/api/catalyst/{ticker}` | [test_catalyst.py](scripts/test_catalyst.py) |
| Long/short thesis generator | [thesis.py](backend/analysis/thesis.py) | `/api/thesis/{ticker}` | [test_thesis.py](scripts/test_thesis.py) |
| Speaker prep / PM Q&A | [speaker_prep.py](backend/analysis/speaker_prep.py) | `/api/speaker-prep/{ticker}` | [test_speaker_prep.py](scripts/test_speaker_prep.py) |
| Full sell-side report writer | [report_writer.py](backend/analysis/report_writer.py) | `/api/report/{ticker}` | [test_report_writer.py](scripts/test_report_writer.py) |
| Pitch deck PDF (ReportLab) | [pitch_deck.py](backend/analysis/pitch_deck.py) | `/api/pitch-deck/{ticker}` | [test_pitch_deck.py](scripts/test_pitch_deck.py) |

### Sprint extras (post-MVP)

| Module | File | Endpoint | Test |
|--------|------|----------|------|
| Quant Score Backbone backtest | [score_backtest.py](backend/analysis/score_backtest.py) | `/api/score-backtest` | [test_score_backtest.py](scripts/test_score_backtest.py) |

The backtest covers the **price-derived ~65% of the Quant Score weight** (technical + regime + statistics + spectral + topology). Peer/valuation, sentiment, and risk_framework are excluded because yfinance cannot supply them point-in-time without injecting lookahead bias — those join the backtest once a paid feed (Polygon / FMP) is in place.

### Phase 3 — Frontend overhaul (shipped)
- [x] Tabbed dark-mode UI in [frontend/index.html](frontend/index.html) (~545 lines) and [frontend/app.js](frontend/app.js) (~1,174 lines)
- [x] Plotly visuals across tabs (price/MA/Bollinger, regime ribbon, spectral periodogram, manifold scatter, stress fan chart, peer matrix)
- [x] All new `/api/*` endpoints wired into the UI
- [x] Watchlist scan view (`/api/watchlist/scan`)
- [x] Legacy single-page UI preserved as `index.legacy.html` / `app.legacy.js` for diff/reference

### Legacy modules preserved (intentionally not rewritten)
[indicators.py](backend/analysis/indicators.py), [signals.py](backend/analysis/signals.py), [regime.py](backend/analysis/regime.py), [distribution.py](backend/analysis/distribution.py), [risk.py](backend/analysis/risk.py), [backtest.py](backend/analysis/backtest.py), [report.py](backend/analysis/report.py), [data.py](backend/analysis/data.py).

---

## Broad-universe backtest (first run, 2026-09-21)

Point-in-time S&P 500 membership is now wired into the backtest
(, ), so a name is
only scored on dates it was actually in the index.

**First run, 80 sampled members, 2,612 ticker-months, 37 months:** IR **+0.66**,
mean cross-sectional IC **+0.032**, long-short +0.93%/rebalance gross, +0.68% net
of 10bps. That is positive — and **it must not be quoted as evidence of skill**:

- **t = +1.16 (p ≈ 0.25).** Not statistically distinguishable from zero. The
  backtest text now says so automatically instead of calling 0.66 strong.
- **Pooled IC is −0.013**, the opposite sign to the monthly average.
- **No component survives the Benjamini-Hochberg correction** (topology comes
  closest, at q = 0.17, and with a *negative* IC).
- **7 of 80 sampled names had no usable history — all 7 are index leavers.**
  The missing names are exactly the ones that would drag returns down, so the
  positive result is biased upward. Only CRSP closes that gap.

Next: a 200-name run to shrink the error bars, then the full ~500.
Log: .

## TO DO — next sprint

> **2026-08-30 fix session (10 commits):** docs honesty pass (14-ticker IR −0.38 now the
> headline everywhere), component-failure logging in quant_score, UTF-8 test output,
> peer-cohort guards, 3-yr DCF base + 3-point CAGR minimum, cache eviction, legacy
> frontend deleted, generic 500 responses, and **momentum split out of the valuation
> component** (peers.py — Quant Scores shift as a result).
>
> **Same-day feature sprint:** What-If tab (growth of $10k vs SPY, `whatif.py`),
> Learn tab (34-term glossary in three registers, `glossary.py`), Paper Trading tab
> (`paper.py` — $100k simulated account, avg-cost accounting), dual-backend DB layer
> (`db.py` — SQLite locally, Postgres via `DATABASE_URL` on Render, so deployed state
> survives restarts), `warm_cache.py` demo-prep script, and **the Replay Game**
> (`game.py` — blind historical setups, ticker/dates masked, direction + confidence
> scored as a calibration curve with Brier score; passing is a first-class answer).
> Full suite **21/21 green**.

The MVP is complete. Highest-ROI next steps (no funding required):

1. ~~**Quant Score backtest**~~ — done, **and the corrected full-watchlist result is still negative.** After the 2026-09 audit fixes (the statistics component had been silently dropped from every earlier run, and the spectral phase labels were shifted a quarter cycle), the 14-ticker walk-forward gives IR ≈ **−0.25**, mean cross-sectional IC ≈ −0.025 (t = −0.44), pooled IC −0.032, over 518 ticker-months (2023-08 → 2026-08). Earlier runs: −0.38 (pre-fix, 2023-05 → 2026-05), +0.05 on 10 names, +0.33 on the 3-ticker pilot. The window also rolls forward as new data arrives, so these are not strictly like-for-like — but every version says the same thing: **no measurable edge on this universe.** Full output: `scripts/_watchlist_backtest_v3.log`. Companion timing test (`scripts/watchlist_alpha_check.py`): the signal-timed strategy trails SPY on 11/14 names, mean alpha ≈ −22%.
2. **LLM hook stubs** — wire `ANTHROPIC_API_KEY` env-var checks into [thesis.py](backend/analysis/thesis.py), [report_writer.py](backend/analysis/report_writer.py), [speaker_prep.py](backend/analysis/speaker_prep.py). Templates fall back if the key is missing; LLM-grade narrative the moment a key is set.
3. **Harden [data.py](backend/analysis/data.py) against yfinance breakage** — wrap Yahoo calls in try/except with clear error surfaces; log missing fields so silent breakage stops happening.
4. **Single-command test runner** — combine the 18 separate `scripts/test_*.py` smoke tests into one `scripts/run_all_tests.py`.

Funded next steps (require the $500–$1,000 budget): see [HANDOFF.md §5](HANDOFF.md) — Polygon/FMP feed, hosted deploy, LLM credits.
