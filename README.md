# QuantAnalyzer

A private quantitative stock research dashboard. Enter any ticker and get a full multi-factor analysis plus a plain-English research report.

## What you get per ticker

- **Buy / Hold / Sell signal** — combined from trend, momentum, and volatility regime
- **Trend analysis** — 50/200 SMA, golden cross detection
- **Momentum** — RSI, MACD, multi-horizon returns
- **Regime classification** — trending, ranging, or breakout
- **Statistical profile** — mean, stdev, skew, kurtosis, VaR, current z-score
- **Risk rating** — low / medium / high, based on annualized volatility and max drawdown
- **Backtest** — walk-forward evaluation of the signal over the last 2 years vs. buy-and-hold
- **Interactive chart** — Plotly with 50/200 MA and Bollinger band overlays
- **Plain-English report** — explains every input behind the signal

## Dashboard features

- **Live data** via yfinance with 15-minute disk caching, so re-loads are instant
- **Best Buys scan** — ranks your watchlist by opportunity score
- **Editable watchlist** stored in SQLite (defaults: ADBE, NOW, MSFT, AAPL, GOOGL, META, NVDA, AMD, CRM, ORCL)

## Tech stack

FastAPI (async) · yfinance · pandas / numpy / scipy · vanilla JS + Plotly · SQLite

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
./run.sh                 # Windows: run.bat
```

Open http://127.0.0.1:8000 in your browser.

## Deploy publicly (Render, free tier)

1. Push the repo to GitHub (public).
2. Go to **https://render.com** → sign in with GitHub.
3. Click **New +** → **Blueprint** → pick the `quantanalyzer` repo.
4. Render reads `render.yaml`, provisions the service, and gives you a URL like `https://quantanalyzer.onrender.com`.
5. First request after idle takes ~30s on free tier (cold start); subsequent requests are fast.

Anyone with the URL can use the dashboard — no install required.

## Disclaimer

This tool is for personal research and educational use only. It is **not financial advice**. Past performance does not guarantee future results. Do your own due diligence before making any investment decision.
