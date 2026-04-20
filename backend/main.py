"""FastAPI entrypoint. Serves the dashboard and the analysis JSON endpoints."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # MUST run before importing modules that read env at import time

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.analysis import data as data_mod
from backend.analysis import backtest as backtest_mod
from backend.analysis import distribution as dist_mod
from backend.analysis import indicators as ind_mod
from backend.analysis import regime as regime_mod
from backend.analysis import report as report_mod
from backend.analysis import risk as risk_mod
from backend.analysis import signals as signals_mod

db.init()

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="QuantAnalyzer", version="1.0")


def _analyze_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    df = ind_mod.compute_all(td.history)
    df_ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
    if df_ready.empty:
        # Not enough history for full signal — fall back to whatever we have
        df_ready = df.dropna(subset=["SMA50", "MACD_HIST"])
        if df_ready.empty:
            raise HTTPException(status_code=422, detail="Not enough price history to analyze.")

    bench_td = data_mod.load("SPY")
    bench_df = bench_td.history if bench_td else None

    sig = signals_mod.compute(df_ready, bench_df)
    reg = regime_mod.classify(df_ready)
    rsk = risk_mod.rate(td.history["Close"])
    dist = dist_mod.compute(td.history["Close"])
    bt = backtest_mod.run(td.history)
    narrative = report_mod.build(td.ticker, td.last_price, td.info, sig, reg, rsk, dist, bt)

    return {
        "ticker": td.ticker,
        "info": td.info,
        "last_price": td.last_price,
        "signal": {
            "action": sig.action,
            "composite": sig.composite,
            "confidence": sig.confidence,
            "opportunity": sig.opportunity,
            "factors": [
                {"name": f.name, "score": f.score, "value": f.value, "explanation": f.explanation}
                for f in sig.factors
            ],
        },
        "regime": {
            "label": reg.label, "strength": reg.strength, "description": reg.description,
        },
        "risk": {
            "rating": rsk.rating,
            "annualized_vol": rsk.annualized_vol,
            "max_drawdown_1y": rsk.max_drawdown_1y,
            "notes": rsk.notes,
        },
        "distribution": {
            "mean_daily": dist.mean_daily,
            "stdev_daily": dist.stdev_daily,
            "skew": dist.skew,
            "kurtosis": dist.kurtosis,
            "var_95": dist.var_95,
            "var_99": dist.var_99,
            "sharpe_annual": dist.sharpe_annual,
            "last_return_z": dist.last_return_z,
        },
        "backtest": {
            "signal_return": bt.signal_return,
            "buyhold_return": bt.buyhold_return,
            "hit_rate": bt.hit_rate,
            "n_trades": bt.n_trades,
            "sharpe_signal": bt.sharpe_signal,
        },
        "report": narrative,
    }


def _nan_to_none(series: pd.Series, decimals: int = 4) -> list:
    """JSON doesn't permit NaN; convert to None and round."""
    return [None if pd.isna(v) else round(float(v), decimals) for v in series]


def _chart_payload_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    df = ind_mod.compute_all(td.history).iloc[-365:]  # ~1y for the chart
    return {
        "ticker": td.ticker,
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": _nan_to_none(df["Open"]),
        "high": _nan_to_none(df["High"]),
        "low": _nan_to_none(df["Low"]),
        "close": _nan_to_none(df["Close"]),
        "volume": [0 if pd.isna(v) else int(v) for v in df["Volume"]],
        "sma50": _nan_to_none(df["SMA50"]),
        "sma200": _nan_to_none(df["SMA200"]),
        "bb_low": _nan_to_none(df["BB_LOW"]),
        "bb_high": _nan_to_none(df["BB_HIGH"]),
        "rsi": _nan_to_none(df["RSI14"], 2),
    }


@app.get("/api/analyze/{ticker}")
async def analyze(ticker: str):
    return await asyncio.to_thread(_analyze_sync, ticker)


@app.get("/api/chart/{ticker}")
async def chart(ticker: str):
    return await asyncio.to_thread(_chart_payload_sync, ticker)


@app.get("/api/watchlist")
async def get_watchlist():
    return {"tickers": db.list_tickers()}


@app.post("/api/watchlist/{ticker}")
async def add_watchlist(ticker: str):
    db.add(ticker)
    return {"tickers": db.list_tickers()}


@app.delete("/api/watchlist/{ticker}")
async def del_watchlist(ticker: str):
    db.remove(ticker)
    return {"tickers": db.list_tickers()}


@app.get("/api/watchlist/scan")
async def scan_watchlist():
    tickers = db.list_tickers()

    async def one(t: str) -> dict[str, Any] | None:
        try:
            res = await asyncio.to_thread(_analyze_sync, t)
            return {
                "ticker": res["ticker"],
                "name": res["info"].get("shortName") or res["ticker"],
                "last_price": res["last_price"],
                "action": res["signal"]["action"],
                "composite": res["signal"]["composite"],
                "confidence": res["signal"]["confidence"],
                "opportunity": res["signal"]["opportunity"],
                "risk": res["risk"]["rating"],
                "regime": res["regime"]["label"],
            }
        except HTTPException:
            return None
        except Exception:
            return None

    results = await asyncio.gather(*(one(t) for t in tickers))
    rows = [r for r in results if r is not None]
    rows.sort(key=lambda r: r["opportunity"], reverse=True)
    return {"results": rows}


# Static frontend
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.exception_handler(Exception)
async def unhandled(_, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
