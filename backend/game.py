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
import pandas as pd

from backend import db
from backend.analysis import data as data_mod
from backend.analysis import crisis as crisis_mod
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


def _crisis_positions(index: pd.DatetimeIndex, lo: int, hi: int) -> list[int]:
    """Index positions inside a known crisis window, within the usable range.

    Crisis rounds are kept as a separate mode rather than mixed into normal
    play: stress periods have a different base rate of up days, so blending
    them would quietly change the odds a player is being scored against.
    """
    out: list[int] = []
    for w in crisis_mod.CRISIS_WINDOWS:
        start, end = pd.Timestamp(w["start"]), pd.Timestamp(w["end"])
        hits = np.where((index >= start) & (index <= end))[0]
        out.extend(int(i) for i in hits if lo <= i <= hi)
    return sorted(set(out))


def _crisis_for_date(date: pd.Timestamp) -> dict[str, str] | None:
    for w in crisis_mod.CRISIS_WINDOWS:
        if pd.Timestamp(w["start"]) <= date <= pd.Timestamp(w["end"]):
            return w
    return None


def new_round(seed: int | None = None, mode: str = "any") -> dict[str, Any]:
    """Sample a (ticker, cutoff), build the masked payload, persist, return it.

    mode "any"    — any date with enough history on either side.
    mode "crisis" — only dates inside the four crisis windows.
    """
    mode = (mode or "any").lower().strip()
    if mode not in ("any", "crisis"):
        raise GameError("mode must be 'any' or 'crisis'")
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
        if mode == "crisis":
            options = _crisis_positions(pd.DatetimeIndex(close.index).tz_localize(None), lo, hi)
            if not options:
                continue        # this ticker was not listed during any crisis
            cut = rng.choice(options)
        else:
            cut = rng.randint(lo, hi)

        hist_slice = td.history.iloc[: cut + 1]
        close_slice = close.iloc[: cut + 1]
        df_ind = ind_mod.compute_all(hist_slice)

        fwd_return = float(close.iloc[cut + FWD_DAYS] / close.iloc[cut] - 1.0)
        payload = _build_payload(close_slice, df_ind)

        # Reveal: the forward path, rebased to the same 100-scale chart end
        last_rebased = payload["prices"][-1]
        fwd_path = close.iloc[cut: cut + FWD_DAYS + 1]
        crisis_w = _crisis_for_date(pd.Timestamp(close.index[cut]).tz_localize(None))
        reveal = {
            "ticker": ticker,
            "cutoff_date": str(close.index[cut].date()),
            "crisis": crisis_w["name"] if crisis_w else None,
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
        return {"round_id": round_id, **payload, "fwd_days": FWD_DAYS, "mode": mode}

    if mode == "crisis":
        raise GameError("No watchlist ticker has price history inside a crisis window.")
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


def _round_indicators(round_id: int) -> dict[str, Any] | None:
    """Indicator panel that was on screen for a given round."""
    rnd = db.game_get_round(round_id)
    if rnd is None:
        return None
    try:
        return json.loads(rnd["payload"]).get("indicators") or None
    except Exception:
        return None


def get_habits() -> dict[str, Any]:
    """Decision habits measured from the player's own answered rounds.

    Three measures, each reported only once enough rounds exist:

    trend_chasing  How much more often you go long on setups that have already
                   run up. Built the way Kalda et al. measure it on brokerage
                   data — compare behaviour on the strongest past performers
                   against the weakest — using terciles of the 1-month return
                   that was displayed on screen. +1 = always long the hot
                   setups and never the cold ones; 0 = no tilt; -1 = contrarian.

    overconfidence Stated confidence minus the share you actually got right.
                   Positive = more certain than accurate.

    pass_discipline How often you pass when the indicators disagree with each
                   other, versus when they point the same way. Passing the
                   genuinely unclear setups is the skill this rewards.
    """
    guesses = db.game_guesses()
    rows: list[dict[str, Any]] = []
    for g in guesses:
        ind = _round_indicators(g["round_id"]) or {}
        rows.append({**g, "ret_1m": ind.get("ret_1m_pct"), "rsi": ind.get("rsi14"),
                     "macd": ind.get("macd_hist"), "ma50": ind.get("vs_sma50_pct"),
                     "ma200": ind.get("vs_sma200_pct")})

    decided = [r for r in rows if r["direction"] in ("long", "short")]
    out: dict[str, Any] = {
        "rounds": len(rows), "decided": len(decided),
        "passes": len(rows) - len(decided),
        "trend_chasing": None, "trend_chasing_n": 0,
        "long_rate_hot": None, "long_rate_cold": None,
        "overconfidence_gap": None, "stated_confidence": None, "hit_rate": None,
        "pass_discipline": None, "pass_rate_mixed": None, "pass_rate_clear": None,
        "explanations": {},
    }

    # --- trend chasing: long rate on hot vs cold setups -------------------
    usable = [r for r in decided if r["ret_1m"] is not None]
    if len(usable) >= 9:
        usable.sort(key=lambda r: r["ret_1m"])
        k = len(usable) // 3
        cold, hot = usable[:k], usable[-k:]
        lr_cold = sum(1 for r in cold if r["direction"] == "long") / len(cold)
        lr_hot = sum(1 for r in hot if r["direction"] == "long") / len(hot)
        out["long_rate_cold"] = round(lr_cold * 100, 1)
        out["long_rate_hot"] = round(lr_hot * 100, 1)
        out["trend_chasing"] = round(lr_hot - lr_cold, 3)
        out["trend_chasing_n"] = len(usable)

    # --- overconfidence: stated confidence vs realized hit rate -----------
    scored = [r for r in decided if r["correct"] is not None]
    if len(scored) >= 5:
        conf = sum(r["confidence"] for r in scored) / len(scored)
        hit = sum(r["correct"] for r in scored) / len(scored) * 100.0
        out["stated_confidence"] = round(conf, 1)
        out["hit_rate"] = round(hit, 1)
        out["overconfidence_gap"] = round(conf - hit, 1)

    # --- pass discipline: passing when the indicators disagree ------------
    def _mixed(r: dict[str, Any]) -> bool | None:
        votes = [r["ma50"], r["macd"], r["ret_1m"], (r["rsi"] - 50.0) if r["rsi"] is not None else None]
        votes = [v for v in votes if v is not None]
        if len(votes) < 4:
            return None
        bull = sum(1 for v in votes if v > 0)
        # "mixed" = the four indicators do not agree. Requiring an exact 2-2
        # split made only ~8% of rounds count, so a player needed ~40 rounds
        # before the measure appeared; not-unanimous is ~35% of rounds.
        return 0 < bull < 4

    mixed = [r for r in rows if _mixed(r) is True]
    clear = [r for r in rows if _mixed(r) is False]
    if len(mixed) >= 3 and len(clear) >= 3:
        pm = sum(1 for r in mixed if r["direction"] == "pass") / len(mixed)
        pc = sum(1 for r in clear if r["direction"] == "pass") / len(clear)
        out["pass_rate_mixed"] = round(pm * 100, 1)
        out["pass_rate_clear"] = round(pc * 100, 1)
        out["pass_discipline"] = round(pm - pc, 3)

    out["explanations"] = _habit_explanations(out)
    return out


def _habit_explanations(h: dict[str, Any]) -> dict[str, str]:
    ex: dict[str, str] = {}
    tc = h["trend_chasing"]
    if tc is None:
        ex["trend_chasing"] = (
            f"Play at least 9 decided rounds to measure this ({h['decided']} so far). "
            "It compares how often you go long on setups that already ran up against "
            "ones that fell.")
    else:
        direction = ("You lean toward buying what has already gone up"
                     if tc > 0.15 else
                     "You lean contrarian, buying what has fallen"
                     if tc < -0.15 else
                     "You show no strong tilt either way")
        ex["trend_chasing"] = (
            f"{direction}: long on {h['long_rate_hot']:.0f}% of the strongest recent "
            f"performers vs {h['long_rate_cold']:.0f}% of the weakest, across "
            f"{h['trend_chasing_n']} rounds. Trend-chasing is the bias trading apps "
            "have been shown to amplify, and it is not rewarded at this horizon.")
    gap = h["overconfidence_gap"]
    if gap is None:
        ex["overconfidence"] = "Five decided rounds are needed before confidence can be compared with accuracy."
    else:
        verdict = ("You are more certain than accurate" if gap > 5 else
                   "You are underconfident — you are right more often than you claim"
                   if gap < -5 else "Your confidence matches your accuracy closely")
        ex["overconfidence"] = (
            f"{verdict}: average stated confidence {h['stated_confidence']:.0f}% vs "
            f"{h['hit_rate']:.0f}% actually right ({gap:+.0f} points).")
    pd_ = h["pass_discipline"]
    if pd_ is None:
        ex["pass_discipline"] = "Needs at least 3 mixed-signal and 3 clear-signal rounds."
    else:
        verdict = ("You pass more often when the signals disagree, which is the point"
                   if pd_ > 0.1 else
                   "You pass about as often either way — the unclear setups are not being filtered"
                   if pd_ > -0.1 else
                   "You pass more on clear setups than unclear ones, which is backwards")
        ex["pass_discipline"] = (
            f"{verdict}: passed {h['pass_rate_mixed']:.0f}% of mixed-signal rounds vs "
            f"{h['pass_rate_clear']:.0f}% of clear ones.")
    return ex


def reset() -> None:
    db.game_reset()
