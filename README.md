# QuantAnalyzer

A private quantitative stock research dashboard. Enter any ticker and get a full
multi-factor analysis: trend, momentum, regime, statistical distribution,
backtested Buy/Hold/Sell signal, risk rating, and a plain-English research report.

## Features

- **Live data** via yfinance with disk caching (15-min TTL) so re-loads are instant
- **Multi-factor signal**: combines trend (50/200 SMA, golden cross), momentum
  (RSI, MACD, multi-horizon returns), and volatility regime
- **Regime detection**: trending / ranging / breakout classification
- **Statistical distribution**: mean, stdev, skew, kurtosis, VaR, current z-score
- **Risk rating**: low / medium / high based on annualized vol + max drawdown
- **Backtest**: walk-forward signal evaluation over the last 2 years vs buy-and-hold
- **Best Buys scan**: ranks the watchlist by an opportunity score
- **Interactive Plotly chart** with overlays (50/200 MA, Bollinger bands)
- **Plain-English report** explaining every input behind the signal
- **Editable watchlist** stored in SQLite (default: ADBE, NOW, MSFT, AAPL, GOOGL,
  META, NVDA, AMD, CRM, ORCL)

## Tech stack

FastAPI (async) · yfinance · pandas/numpy/scipy · vanilla JS + Plotly · SQLite

## Run locally (Windows)

```bash
cd quantanalyzer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
run.bat
```

Then open http://127.0.0.1:8000 in your browser.

## Run locally (macOS/Linux)

```bash
cd quantanalyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

## Sharing access

This repository is **private**. To give someone access, add them as a
collaborator on GitHub:

`Settings → Collaborators → Add people → <github-username>`

They'll get an email invite. Nobody outside that list can see the repo.

## Disclaimer

This tool is for personal research and educational use only. It is **not
financial advice**. Past performance does not guarantee future results.
Do your own due diligence before making any investment decision.
