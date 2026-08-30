"""The Replay Game — a calibration trainer, not a stock-picking contest.

A round shows a real historical setup with the ticker and dates hidden:
126 trading days of price rebased to 100, plus the fast technical panel
(trend, RSI, MACD, volatility, momentum) computed strictly from data before
the cutoff. The player commits a direction (long / short / pass) AND a
confidence (50-100%). Then the next 21 trading days are revealed.

What is scored is not just whether the call was right, but whether stated
confidence matches realized hit rate — the calibration curve and Brier
score are the real report card. "Pass" is deliberately a first-class
answer: declining an unclear setup is a skill, so passes are tracked but
never penalized.

Leakage rules (enforced in _build_payload, asserted in tests):
  - no ticker, no company name, no dates in the payload
  - prices rebased to 100 at the window start (absolute level would
    fingerprint famous stocks)
  - nothing computed from data after the cutoff
"""
from __future__ import annotations

import json
import random
from typing import Any

import numpy as np

from backend import db
from backend.analysis import data as data_mod
from backend.analysis import indicators as ind_mod

CHART_BARS = 126          # ~6 months shown to the player
FWD_DAYS = 21             # reveal horizon
MIN_LOOKBACK = 260        # bars needed before the cutoff for indicators
CORRECT_THRESHOLD = 0.0   # long correct if fwd > 0, short if fwd < 0


class GameError(ValueError):
    """User-correctable game input problem."""


def _eligible_tickers() -> list[str]:
    try:
        tickers = db.list_tickers()
    except Exception:
        tickers = []
    return tickers or db.DEFAULT_WATCHLIST


def _build_payload(close, df_ind) -> dict[str, Any]:
    """Masked, point-in-time round payload. NO ticker, NO dates, NO levels."""
    window = close.iloc[-CHART_BARS:]
    rebased = (window / window.iloc[0] * 100.0).round(2)

    latest = df_ind.iloc[-1]

    def _f(key):
        v = latest.get(key)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 3)

    sma50, sma200 = _f("SMA50"), _f("SMA200")
    px = float(window.iloc[-1])
    r21 = round(float(close.iloc[-1] / close.iloc[-22] - 1.0) * 100, 1) if len(close) > 22 else None
    r63 = round(float(close.iloc[-1] / close.iloc[-64] - 1.0) * 100, 1) if len(close) > 64 else None

    return {
        # x-axis is bars-before-decision, never dates
        "bars_ago": list(range(-len(rebased) + 1, 1)),
        "prices": [float(v) for v in rebased],
        "indicators": {
            "rsi14": _f("RSI14"),
            "macd_hist": _f("MACD_HIST"),
            "vol30_ann_pct": round(_f("VOL30") * 100, 1) if _f("VOL30") is not None else None,
            "vs_sma50_pct": round((px / sma50 - 1.0) * 100, 1) if sma50 else None,
            "vs_sma200_pct": round((px / sma200 - 1.0) * 100, 1) if sma200 else None,
            "ret_1m_pct": r21,
            "ret_3m_pct": r63,
        },
    }


def new_round(seed: int | None = None) -> dict[str, Any]:
    """Sample a (ticker, cutoff), build the masked payload, persist, return it."""
    rng = random.Random(seed)
    tickers = _eligible_tickers()
    rng.shuffle(tickers)

    for ticker in tickers:
        td = data_mod.load(ticker, period="10y")
        if td is None or td.history is None:
            continue
        close = td.history["Close"].dropna()
        # need MIN_LOOKBACK before cutoff and FWD_DAYS after
        lo, hi = MIN_LOOKBACK, len(close) - FWD_DAYS - 1
        if hi <= lo:
            continue
        cut = rng.randint(lo, hi)

        hist_slice = td.history.iloc[: cut + 1]
        close_slice = close.iloc[: cut + 1]
        df_ind = ind_mod.compute_all(hist_slice)

        fwd_return = float(close.iloc[cut + FWD_DAYS] / close.iloc[cut] - 1.0)
        payload = _build_payload(close_slice, df_ind)

        # Reveal: the forward path, rebased to the same 100-scale chart end
        last_rebased = payload["prices"][-1]
        fwd_path = close.iloc[cut: cut + FWD_DAYS + 1]
        reveal = {
            "ticker": ticker,
            "cutoff_date": str(close.index[cut].date()),
            "fwd_return_pct": round(fwd_return * 100, 2),
            "fwd_bars": list(range(0, len(fwd_path))),
            "fwd_prices": [round(float(v / fwd_path.iloc[0] * last_rebased), 2)
                           for v in fwd_path],
        }

        round_id = db.game_save_round(
            ticker=ticker,
            cutoff_date=reveal["cutoff_date"],
            fwd_return=fwd_return,
            payload=json.dumps(payload),
            reveal=json.dumps(reveal),
        )
        return {"round_id": round_id, **payload, "fwd_days": FWD_DAYS}

    raise GameError("No ticker in the watchlist has enough history for a round.")


def submit_guess(round_id: int, direction: str, confidence: float) -> dict[str, Any]:
    direction = direction.lower().strip()
    if direction not in ("long", "short", "pass"):
        raise GameError("direction must be 'long', 'short', or 'pass'")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise GameError("confidence must be a number")
    if not (50.0 <= confidence <= 100.0):
        raise GameError("confidence must be between 50 and 100")

    rnd = db.game_get_round(round_id)
    if rnd is None:
        raise GameError(f"Round {round_id} not found.")
    if db.game_round_answered(round_id):
        raise GameError("This round was already answered — deal a new one.")

    fwd = rnd["fwd_return"]
    if direction == "pass":
        pnl = None
        correct = None
        brier = None
    else:
        pnl = fwd if direction == "long" else -fwd
        correct = 1 if pnl > CORRECT_THRESHOLD else 0
        p = confidence / 100.0
        brier = (p - correct) ** 2

    db.game_save_guess(round_id, direction, confidence,
                       None if pnl is None else round(pnl * 100, 2),
                       correct, brier)

    reveal = json.loads(rnd["reveal"])
    return {
        "direction": direction,
        "confidence": confidence,
        "pnl_pct": None if pnl is None else round(pnl * 100, 2),
        "correct": correct,
        "reveal": reveal,
        "stats": get_stats(),
    }


def get_stats() -> dict[str, Any]:
    """Running scorecard: hit rate, P&L, Brier, calibration bins, baselines."""
    guesses = db.game_guesses()
    played = [g for g in guesses if g["direction"] != "pass"]
    passes = len(guesses) - len(played)

    stats: dict[str, Any] = {
        "rounds": len(guesses),
        "decisions": len(played),
        "passes": passes,
        "hit_rate_pct": None,
        "mean_pnl_pct": None,
        "sum_pnl_pct": None,
        "brier": None,
        "buyhold_mean_pnl_pct": None,   # always-long baseline on the same rounds
        "calibration": [],
    }
    if not played:
        return stats

    hits = [g["correct"] for g in played]
    pnls = [g["pnl_pct"] for g in played]
    briers = [g["brier"] for g in played if g["brier"] is not None]
    stats["hit_rate_pct"] = round(100.0 * sum(hits) / len(hits), 1)
    stats["mean_pnl_pct"] = round(float(np.mean(pnls)), 2)
    stats["sum_pnl_pct"] = round(float(np.sum(pnls)), 2)
    stats["brier"] = round(float(np.mean(briers)), 3) if briers else None

    # Always-long baseline: what buying every played round would have done
    bh = []
    for g in played:
        rnd = db.game_get_round(g["round_id"])
        if rnd:
            bh.append(rnd["fwd_return"] * 100)
    if bh:
        stats["buyhold_mean_pnl_pct"] = round(float(np.mean(bh)), 2)

    # Calibration: stated confidence vs realized hit rate, 10-point bins
    bins = [(50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
    for lo, hi in bins:
        in_bin = [g for g in played if lo <= g["confidence"] < hi]
        if not in_bin:
            continue
        stats["calibration"].append({
            "bin": f"{lo}-{min(hi - 1, 100)}%",
            "stated_mid": (lo + min(hi, 100)) / 2,
            "n": len(in_bin),
            "realized_pct": round(100.0 * sum(g["correct"] for g in in_bin) / len(in_bin), 1),
        })
    return stats


def reset() -> None:
    db.game_reset()
