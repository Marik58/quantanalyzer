# QuantAnalyzer — Project Status

**Last updated:** 2026-04-24
**Goal:** Upgrade QuantAnalyzer from a basic signals/backtest app into an institutional-grade research platform for Fox Fund.

**Constraints:**
- Data vendor: yfinance only (no paid API keys)
- Windows, no C++ toolchain — pure-Python or wheel-only deps
- Default watchlist: ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS
- Build incrementally — one module at a time, tested before moving on

---

## ✅ DONE

### Phase 0 — Scaffolding
- [x] `requirements.txt`
- [x] Folder layout: [backend/](backend/), [backend/analysis/](backend/analysis/), [frontend/](frontend/), [scripts/](scripts/), [data/](data/)
- [x] `run.bat` / `run.sh` launchers
- [x] DB + cache layer ([backend/db.py](backend/db.py), [backend/cache.py](backend/cache.py))

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

Legacy modules preserved (not rewritten): [indicators.py](backend/analysis/indicators.py), [signals.py](backend/analysis/signals.py), [regime.py](backend/analysis/regime.py), [distribution.py](backend/analysis/distribution.py), [risk.py](backend/analysis/risk.py), [backtest.py](backend/analysis/backtest.py), [report.py](backend/analysis/report.py), [data.py](backend/analysis/data.py).

### Phase 2 — Started
- [x] DCF / valuation module: [valuation.py](backend/analysis/valuation.py) → `/api/valuation/{ticker}` ([test_valuation.py](scripts/test_valuation.py))

---

## 🚧 TO DO

### Phase 2 — Research tooling (remaining)
- [ ] **Catalyst tracker** — upcoming earnings, ex-div, analyst events; pull from `Ticker.calendar` / `earnings_dates`
- [ ] **Thesis generator** — synthesize quant score + valuation + sentiment into a written long/short thesis
- [ ] **Speaker prep / Q&A pack** — anticipated PM questions with data-backed answers
- [ ] **Full report writer** — combines every module into a sell-side-style research note
- [ ] **Pitch deck PDF** — exports a Fox-Fund-ready deck (cover, thesis, valuation, risks, catalysts)

### Phase 3 — Frontend overhaul
Current [frontend/](frontend/) is the legacy single-page UI ([index.html](frontend/index.html), [app.js](frontend/app.js), [styles.css](frontend/styles.css)) — none of the new Phase 1 modules are wired into the UI yet.

- [ ] Tabbed dark-mode layout (Overview / Quant / Risk / Peers / Sentiment / Valuation / Report)
- [ ] Plotly visuals on every tab (regime ribbon, spectral periodogram, manifold scatter, stress fan chart, peer matrix)
- [ ] Wire up all new `/api/*` endpoints
- [ ] PDF export from the browser
- [ ] Watchlist scan view consuming `/api/watchlist/scan`

---

## Suggested next step
Pick one of the Phase 2 items to build next. **Catalyst tracker** is the smallest and unblocks the thesis generator and report writer downstream — recommended starting point unless you'd rather jump to the frontend overhaul so you can *see* what's already built.
