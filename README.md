# QuantAnalyzer

A single-developer, institutional-style equity research platform. Enter a ticker and get a multi-paradigm quant diagnostic plus a written, defendable stock pitch — every output paired with a plain-English explanation.

Built by a Fox Fund member. For the full project brief and funding ask, see [HANDOFF.md](HANDOFF.md). For the short status snapshot, see [PROJECT_STATUS.md](PROJECT_STATUS.md).

## What you get per ticker

**Quant diagnostics**
- **Advanced statistics** — skew, kurtosis, VaR, CVaR, current z-score
- **Spectral analysis** — FFT periodogram, dominant cycles, wavelet decomposition
- **HMM regime classification** — bull / bear / chop with state probabilities
- **Topological data analysis** — persistence diagrams over price embeddings
- **Manifold learning** — UMAP / Isomap structure of the recent return surface
- **Risk & stress framework** — historical + parametric VaR, GARCH vol forecast, fan chart
- **Peer relative-value matrix** — multiples vs. sector cohort
- **News sentiment** — VADER over yfinance news headlines
- **Quant Score** — composite of all of the above, with conflict flags and confidence

**Research tooling**
- **DCF / valuation triangulation** — multiples + DCF + implied-growth triangulated to a fair-value range
- **Catalyst tracker** — earnings, ex-div, analyst events
- **Long/short thesis generator** — written narrative built on the structured quant output
- **Speaker prep / PM Q&A** — anticipated questions with data-backed answers
- **Full sell-side-style research note** — combines every module into one report
- **Pitch deck PDF** — Fox-Fund-ready slide deck via ReportLab

**Dashboard**
- Tabbed dark-mode UI with Plotly across every tab
- 15-minute disk cache so repeat lookups are sub-second
- Editable watchlist in SQLite, plus a `/api/watchlist/scan` endpoint that ranks the whole list by Quant Score

## Tech stack

FastAPI (async) · yfinance · pandas / numpy / scipy · scikit-learn · hmmlearn · ripser · umap-learn · arch · vaderSentiment · vanilla JS + Plotly · SQLite · ReportLab (PDF)

## Run locally

```bash
cd quantanalyzer
python -m venv .venv
```

Activate the virtual environment:

- **Windows:** `.venv\Scripts\activate`
- **macOS / Linux:** `source .venv/bin/activate`

Then install dependencies and start the server:

```bash
pip install -r requirements.txt
cp .env.example .env     # Windows: copy .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000.

> First boot is slow — `backend/main.py` imports ~25 analysis modules and runs `db.init()` at import time. The dashboard returns ERR_CONNECTION_REFUSED until "Application startup complete." prints in the terminal.

## Deploy publicly (Render, free tier)

1. Push the repo to GitHub.
2. Go to **https://render.com** → sign in with GitHub.
3. Click **New +** → **Blueprint** → pick the `quantanalyzer` repo.
4. Render reads [render.yaml](render.yaml), provisions the service, and gives you a URL.
5. First request after idle takes ~30s on free tier (cold start); subsequent requests are fast.

## Constraints

- Data vendor: yfinance only (no paid API keys)
- Windows host, no C++ toolchain — all deps ship wheels or are pure Python
- Default watchlist: ADBE, NOW, CRM, ORCL, MSFT, GOOGL, NVDA, AMD, AAPL, META, AVGO, AMAT, SNPS, CDNS

## Disclaimer

This tool is for personal research and educational use only. It is **not financial advice**. Past performance does not guarantee future results. Do your own due diligence before making any investment decision.
