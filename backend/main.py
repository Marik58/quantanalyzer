"""FastAPI entrypoint. Serves the dashboard and the analysis JSON endpoints."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # MUST run before importing modules that read env at import time

# Suppress hmmlearn's "Model is not converging" chatter — those deltas are 1e-3
# magnitude and the model still produces a usable converged solution. Cosmetic
# noise only.
import logging
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.analysis import data as data_mod
from backend.analysis import backtest as backtest_mod
from backend.analysis import catalyst as catalyst_mod
from backend.analysis import distribution as dist_mod
from backend.analysis import indicators as ind_mod
from backend.analysis import manifold as manifold_mod
from backend.analysis import peers as peers_mod
from backend.analysis import pitch_deck as pitch_deck_mod
from backend.analysis import quant_score as quant_score_mod
from backend.analysis import regime as regime_mod
from backend.analysis import regime_hmm as regime_hmm_mod
from backend.analysis import report as report_mod
from backend.analysis import report_writer as report_writer_mod
from backend.analysis import risk as risk_mod
from backend.analysis import risk_framework as risk_fw_mod
from backend.analysis import sentiment as sentiment_mod
from backend.analysis import signals as signals_mod
from backend.analysis import speaker_prep as speaker_prep_mod
from backend.analysis import spectral as spectral_mod
from backend.analysis import statistics as stats_mod
from backend.analysis import thesis as thesis_mod
from backend.analysis import topology as topology_mod
from backend.analysis import valuation as valuation_mod

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


def _advanced_stats_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    bench_td = data_mod.load("SPY")
    bench_close = bench_td.history["Close"] if bench_td else None
    try:
        result = stats_mod.compute(td.history["Close"], bench_close)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    payload = stats_mod.to_dict(result)
    payload["ticker"] = td.ticker
    return payload


@app.get("/api/advanced-stats/{ticker}")
async def advanced_stats(ticker: str):
    return await asyncio.to_thread(_advanced_stats_sync, ticker)


def _spectral_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    try:
        result = spectral_mod.compute(td.history["Close"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    payload = spectral_mod.to_dict(result)
    payload["ticker"] = td.ticker
    return payload


@app.get("/api/spectral/{ticker}")
async def spectral(ticker: str):
    return await asyncio.to_thread(_spectral_sync, ticker)


def _regime_hmm_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    try:
        result = regime_hmm_mod.compute(td.history["Close"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    payload = regime_hmm_mod.to_dict(result)
    payload["ticker"] = td.ticker
    return payload


@app.get("/api/regime-hmm/{ticker}")
async def regime_hmm(ticker: str):
    return await asyncio.to_thread(_regime_hmm_sync, ticker)


def _topology_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    try:
        result = topology_mod.compute(td.history["Close"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    payload = topology_mod.to_dict(result)
    payload["ticker"] = td.ticker
    return payload


@app.get("/api/topology/{ticker}")
async def topology(ticker: str):
    return await asyncio.to_thread(_topology_sync, ticker)


def _manifold_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    if td is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'.")
    h = td.history
    try:
        result = manifold_mod.compute(h["Close"], h["High"], h["Low"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    payload = manifold_mod.to_dict(result)
    payload["ticker"] = td.ticker
    return payload


@app.get("/api/manifold/{ticker}")
async def manifold(ticker: str):
    return await asyncio.to_thread(_manifold_sync, ticker)


def _sentiment_sync(ticker: str) -> dict[str, Any]:
    td = data_mod.load(ticker)
    close = td.history["Close"] if td else None
    result = sentiment_mod.compute(ticker.upper().strip(), close)
    payload = sentiment_mod.to_dict(result)
    payload["ticker"] = result.ticker
    return payload


@app.get("/api/sentiment/{ticker}")
async def sentiment(ticker: str):
    return await asyncio.to_thread(_sentiment_sync, ticker)


def _peers_sync(ticker: str) -> dict[str, Any]:
    result = peers_mod.compute(ticker)
    return peers_mod.to_dict(result)


@app.get("/api/peers/{ticker}")
async def peers(ticker: str):
    return await asyncio.to_thread(_peers_sync, ticker)


def _risk_framework_sync(ticker: str) -> dict[str, Any]:
    result = risk_fw_mod.compute(ticker)
    payload = risk_fw_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/risk-framework/{ticker}")
async def risk_framework(ticker: str):
    return await asyncio.to_thread(_risk_framework_sync, ticker)


def _quant_score_sync(ticker: str) -> dict[str, Any]:
    result = quant_score_mod.compute(ticker)
    payload = quant_score_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/quant-score/{ticker}")
async def quant_score(ticker: str):
    return await asyncio.to_thread(_quant_score_sync, ticker)


def _valuation_sync(ticker: str) -> dict[str, Any]:
    result = valuation_mod.compute(ticker)
    payload = valuation_mod.to_dict(result)
    if result.error and result.method == "unavailable":
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/valuation/{ticker}")
async def valuation(ticker: str):
    return await asyncio.to_thread(_valuation_sync, ticker)


def _catalyst_sync(ticker: str) -> dict[str, Any]:
    result = catalyst_mod.compute(ticker)
    payload = catalyst_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/catalyst/{ticker}")
async def catalyst(ticker: str):
    return await asyncio.to_thread(_catalyst_sync, ticker)


def _thesis_sync(ticker: str) -> dict[str, Any]:
    result = thesis_mod.compute(ticker)
    payload = thesis_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/thesis/{ticker}")
async def thesis(ticker: str):
    return await asyncio.to_thread(_thesis_sync, ticker)


def _speaker_prep_sync(ticker: str) -> dict[str, Any]:
    result = speaker_prep_mod.compute(ticker)
    payload = speaker_prep_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/speaker-prep/{ticker}")
async def speaker_prep(ticker: str):
    return await asyncio.to_thread(_speaker_prep_sync, ticker)


def _report_sync(ticker: str) -> dict[str, Any]:
    result = report_writer_mod.compute(ticker)
    payload = report_writer_mod.to_dict(result)
    if result.error:
        raise HTTPException(status_code=422, detail=result.error)
    return payload


@app.get("/api/report/{ticker}")
async def report_full(ticker: str):
    return await asyncio.to_thread(_report_sync, ticker)


def _pitch_deck_sync(ticker: str) -> str:
    result = pitch_deck_mod.compute(ticker)
    if result.error or not result.pdf_path:
        raise HTTPException(status_code=422,
                            detail=result.error or "pitch deck generation failed")
    return result.pdf_path


@app.get("/api/pitch-deck/{ticker}")
async def pitch_deck(ticker: str):
    pdf_path = await asyncio.to_thread(_pitch_deck_sync, ticker)
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"{ticker.upper()}_pitch_deck.pdf")


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


async def _quant_score_for_scan(ticker: str) -> dict[str, Any] | None:
    """Best-effort quant_score lookup for the scan; returns None on any failure."""
    try:
        result = await asyncio.to_thread(quant_score_mod.compute, ticker)
        if result.error:
            return None
        return {
            "directional": result.directional_score,
            "percentile": result.percentile_score,
            "verdict": result.verdict,
            "confidence": result.confidence,
        }
    except Exception:
        return None


@app.get("/api/watchlist/scan")
async def scan_watchlist():
    tickers = db.list_tickers()

    async def one(t: str) -> dict[str, Any] | None:
        try:
            legacy_task = asyncio.to_thread(_analyze_sync, t)
            quant_task = _quant_score_for_scan(t)
            res, qs = await asyncio.gather(legacy_task, quant_task)
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
                "quant_score": qs,  # may be None if quant_score module failed for this ticker
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
