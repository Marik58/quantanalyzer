"""Quant Score aggregator — the Phase 1 capstone.

Runs every Phase 1 module, maps each to a directional component score in
[-100, +100], and composes them into a single weighted score with a verdict,
risk adjustment, and conflict flags. Failures in any single module degrade
gracefully: the weight is redistributed over the valid components.

Weights (must sum to 1.0):
    technical   0.25   (signals.composite)
    regime      0.20   (regime_hmm current state × confidence)
    valuation   0.15   (peers relative_value_score)
    sentiment   0.10   (sentiment overall_score)
    statistics  0.10   (Sortino via tanh squash)
    spectral    0.05   (cycle.score)
    topology    0.05   (topological_signal × recent-return sign, inverted)
    risk        0.10   (risk_framework overall_risk_score → penalty)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis import data as data_mod
from backend.analysis import indicators as ind_mod
from backend.analysis import peers as peers_mod
from backend.analysis import regime_hmm as regime_hmm_mod
from backend.analysis import risk_framework as risk_fw_mod
from backend.analysis import sentiment as sentiment_mod
from backend.analysis import signals as signals_mod
from backend.analysis import spectral as spectral_mod
from backend.analysis import statistics as stats_mod
from backend.analysis import topology as topology_mod


WEIGHTS: dict[str, float] = {
    "technical":  0.25,
    "regime":     0.20,
    "valuation":  0.15,
    "sentiment":  0.10,
    "statistics": 0.10,
    "spectral":   0.05,
    "topology":   0.05,
    "risk":       0.10,
}


# --- Dataclasses ----------------------------------------------------------

@dataclass
class Component:
    name: str
    score: float | None            # [-100, +100] directional, None = n/a
    weight: float                  # nominal weight
    detail: str                    # one-line plain-English readout
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuantScoreResult:
    ticker: str
    directional_score: float       # [-100, +100]
    percentile_score: float        # 0..100 (=(directional + 100) / 2)
    verdict: str                   # Strong Buy | Buy | Hold | Reduce | Avoid
    confidence: float              # 0..100, based on component agreement
    components: list[Component]
    active_weight: float           # sum of weights of components that voted
    conflicts: list[str]           # flagged contradictions
    explanations: dict[str, str]
    error: str | None = None


# --- Component mappers ---------------------------------------------------

def _tech_component(history: pd.DataFrame, bench_df: pd.DataFrame | None) -> Component:
    try:
        df = ind_mod.compute_all(history)
        df_ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
        if df_ready.empty:
            df_ready = df.dropna(subset=["SMA50", "MACD_HIST"])
        if df_ready.empty:
            raise ValueError("not enough history for technical signal")
        sig = signals_mod.compute(df_ready, bench_df)
        detail = (f"action={sig.action}, composite={sig.composite:+.1f}, "
                  f"confidence={sig.confidence:.0f}")
        return Component(
            name="technical", score=float(sig.composite),
            weight=WEIGHTS["technical"], detail=detail,
            raw={"action": sig.action, "composite": sig.composite,
                 "confidence": sig.confidence},
        )
    except Exception as exc:
        return Component(name="technical", score=None,
                         weight=WEIGHTS["technical"],
                         detail=f"unavailable ({type(exc).__name__})")


def _regime_component(close: pd.Series) -> Component:
    try:
        r = regime_hmm_mod.compute(close)
        conf = float(r.current_confidence or 0.0)
        # Base: direction + intensity for each regime
        base = {
            "Bull":     +80.0,
            "Bear":     -80.0,
            "Sideways":   0.0,
            "Volatile": -40.0,
        }.get(r.current_regime, 0.0)
        score = float(np.clip(base * conf, -100.0, 100.0))
        detail = f"{r.current_regime} @ {conf*100:.0f}% confidence"
        return Component(name="regime", score=score,
                         weight=WEIGHTS["regime"], detail=detail,
                         raw={"regime": r.current_regime, "confidence": conf})
    except Exception as exc:
        return Component(name="regime", score=None, weight=WEIGHTS["regime"],
                         detail=f"unavailable ({type(exc).__name__})")


def _valuation_component(ticker: str) -> Component:
    try:
        p = peers_mod.compute(ticker)
        if p.relative_value_score is None:
            return Component(name="valuation", score=None,
                             weight=WEIGHTS["valuation"],
                             detail=p.status_note or "no peer data")
        # 0..100 → -100..+100 (50 = neutral, 100 = best-in-group = bullish)
        score = float((p.relative_value_score - 50.0) * 2.0)
        detail = (f"relative_value={p.relative_value_score:.0f}/100 → "
                  f"{p.relative_value_label}")
        return Component(name="valuation", score=score,
                         weight=WEIGHTS["valuation"], detail=detail,
                         raw={"relative_value_score": p.relative_value_score,
                              "label": p.relative_value_label})
    except Exception as exc:
        return Component(name="valuation", score=None,
                         weight=WEIGHTS["valuation"],
                         detail=f"unavailable ({type(exc).__name__})")


def _sentiment_component(ticker: str, close: pd.Series) -> Component:
    try:
        s = sentiment_mod.compute(ticker, close)
        if s.error:
            return Component(name="sentiment", score=None,
                             weight=WEIGHTS["sentiment"],
                             detail=f"unavailable ({s.error})")
        score = float(np.clip(s.overall_score, -100.0, 100.0))
        detail = (f"{s.overall_label} @ {score:+.1f} across "
                  f"{s.headline_count} headlines")
        return Component(name="sentiment", score=score,
                         weight=WEIGHTS["sentiment"], detail=detail,
                         raw={"overall_score": s.overall_score,
                              "label": s.overall_label,
                              "headline_count": s.headline_count})
    except Exception as exc:
        return Component(name="sentiment", score=None,
                         weight=WEIGHTS["sentiment"],
                         detail=f"unavailable ({type(exc).__name__})")


def _statistics_component(close: pd.Series, bench_close: pd.Series | None) -> Component:
    try:
        s = stats_mod.compute(close, bench_close)
        sortino = float(s.downside.sortino_annual)
        # Map Sortino: ~1.5+ excellent, 0 neutral, negative bad
        score = float(np.clip(np.tanh(sortino / 1.5) * 100.0, -100.0, 100.0))
        detail = (f"Sortino={sortino:.2f}, Calmar={s.downside.calmar:.2f}, "
                  f"Omega={s.downside.omega_ratio:.2f}")
        return Component(name="statistics", score=score,
                         weight=WEIGHTS["statistics"], detail=detail,
                         raw={"sortino": sortino,
                              "calmar": s.downside.calmar,
                              "omega": s.downside.omega_ratio})
    except Exception as exc:
        return Component(name="statistics", score=None,
                         weight=WEIGHTS["statistics"],
                         detail=f"unavailable ({type(exc).__name__})")


def _spectral_component(close: pd.Series) -> Component:
    try:
        s = spectral_mod.compute(close)
        score = float(np.clip(s.cycle.score * 100.0, -100.0, 100.0))
        detail = (f"{s.cycle.phase_label} (strength={s.cycle.strength:.2f}, "
                  f"period≈{s.cycle.dominant_period_days:.0f}d)")
        return Component(name="spectral", score=score,
                         weight=WEIGHTS["spectral"], detail=detail,
                         raw={"phase_label": s.cycle.phase_label,
                              "strength": s.cycle.strength,
                              "period": s.cycle.dominant_period_days})
    except Exception as exc:
        return Component(name="spectral", score=None,
                         weight=WEIGHTS["spectral"],
                         detail=f"unavailable ({type(exc).__name__})")


def _topology_component(close: pd.Series) -> Component:
    try:
        t = topology_mod.compute(close)
        if t.error:
            return Component(name="topology", score=None,
                             weight=WEIGHTS["topology"],
                             detail=f"unavailable ({t.error})")
        # Mean reversion bias: if cyclic AND recently up → bearish (expect pullback);
        #                    if cyclic AND recently down → bullish (expect bounce).
        ret20 = float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close) > 22 else 0.0
        direction_sign = -1.0 if ret20 > 0.02 else (1.0 if ret20 < -0.02 else 0.0)
        score = float(np.clip(t.topological_signal * direction_sign * 50.0,
                              -100.0, 100.0))
        detail = (f"signal={t.topological_signal:+.2f} ({t.signal_label}); "
                  f"20d={ret20:+.1%}")
        return Component(name="topology", score=score,
                         weight=WEIGHTS["topology"], detail=detail,
                         raw={"signal": t.topological_signal,
                              "label": t.signal_label,
                              "ret20": ret20})
    except Exception as exc:
        return Component(name="topology", score=None,
                         weight=WEIGHTS["topology"],
                         detail=f"unavailable ({type(exc).__name__})")


def _risk_component(ticker: str) -> Component:
    try:
        r = risk_fw_mod.compute(ticker)
        if r.error:
            return Component(name="risk", score=None, weight=WEIGHTS["risk"],
                             detail=f"unavailable ({r.error})")
        # Risk is a penalty. 0 risk → +50 quality premium; 100 risk → -50 penalty.
        # Scaled to the [-100, +100] axis by ×2.
        score = float(np.clip((50.0 - r.overall_risk_score) * 2.0, -100.0, 100.0))
        detail = f"risk={r.overall_risk_score:.0f}/100 ({r.overall_risk_label})"
        return Component(name="risk", score=score, weight=WEIGHTS["risk"],
                         detail=detail,
                         raw={"risk_score": r.overall_risk_score,
                              "label": r.overall_risk_label})
    except Exception as exc:
        return Component(name="risk", score=None, weight=WEIGHTS["risk"],
                         detail=f"unavailable ({type(exc).__name__})")


# --- Verdict / confidence / conflicts ------------------------------------

def _verdict(score: float) -> str:
    if score > 60:  return "Strong Buy"
    if score > 30:  return "Buy"
    if score >= -30: return "Hold"
    if score >= -60: return "Reduce"
    return "Avoid"


def _confidence(components: list[Component]) -> float:
    """Higher confidence when components agree on direction."""
    valid = [c.score for c in components if c.score is not None]
    if len(valid) < 3:
        return 0.0
    signs = [1 if s > 10 else (-1 if s < -10 else 0) for s in valid]
    n = len(signs)
    pos = sum(1 for s in signs if s > 0)
    neg = sum(1 for s in signs if s < 0)
    winner = max(pos, neg)
    agreement = winner / n        # fraction of components on the majority side
    mean_abs = float(np.mean([abs(s) for s in valid]))
    # 60% from agreement, 40% from average conviction
    return float(np.clip(100.0 * (0.6 * agreement + 0.4 * mean_abs / 100.0),
                         0.0, 100.0))


def _flag_conflicts(components: list[Component]) -> list[str]:
    scores = {c.name: c.score for c in components}
    raw = {c.name: c.raw for c in components}
    flags: list[str] = []

    def s(name: str) -> float | None:
        return scores.get(name)

    tech, val, sent, reg, spec, risk = (s("technical"), s("valuation"),
                                         s("sentiment"), s("regime"),
                                         s("spectral"), s("risk"))

    if tech is not None and val is not None:
        if tech > 50 and val < -50:
            flags.append("Momentum strong but valuation rich vs peers — watch "
                         "mean-reversion risk if growth disappoints.")
        if tech < -50 and val > 50:
            flags.append("Price action weak while peers view it as cheap — "
                         "value-trap risk or contrarian long setup; verify thesis.")

    if tech is not None and sent is not None:
        if tech > 50 and sent < -30:
            flags.append("Price ignoring negative news flow — tape leading press, "
                         "or short-squeeze potential.")
        if tech < -50 and sent > 30:
            flags.append("Press bullish but tape is weak — sentiment lagging or "
                         "distribution under cover of headlines.")

    if reg is not None and val is not None and val > 50 and reg < -30:
        flags.append("Cheap versus peers but sitting in a Bear/Volatile regime — "
                     "wait for regime turn before sizing up.")

    if val is not None and sent is not None and val > 50 and sent < -30:
        flags.append("Cheap AND disliked — classic deep-value setup. Thesis must "
                     "be strong; the market is betting the other way.")

    if val is not None and sent is not None and val < -50 and sent > 30:
        flags.append("Expensive AND loved — high expectation risk; small misses "
                     "get punished.")

    if spec is not None and tech is not None:
        phase_label = (raw.get("spectral") or {}).get("phase_label", "")
        if tech > 30 and "peak" in phase_label:
            flags.append("Technical strength into cycle peak — tactical caution, "
                         "tighten stops or partially trim.")
        if tech < -30 and "trough" in phase_label:
            flags.append("Tape weakness into cycle trough — mean reversion may be "
                         "closer than it looks; size into weakness cautiously.")

    if risk is not None and tech is not None and risk < -30 and tech > 30:
        flags.append("High/Extreme risk profile with positive technical — size "
                     "at half-Kelly or less, volatility can erase the edge.")

    reg_label = (raw.get("regime") or {}).get("regime", "")
    if reg_label == "Volatile" and tech is not None and abs(tech) > 30:
        flags.append("Volatile regime distorts directional signals — treat the "
                     "technical read as low-confidence until regime clarifies.")

    return flags


def _composite_explanation(ticker: str, directional: float, percentile: float,
                           verdict: str, confidence: float,
                           active_weight: float,
                           components: list[Component],
                           conflicts: list[str]) -> dict[str, str]:
    top_contrib = sorted(
        [c for c in components if c.score is not None],
        key=lambda c: abs(c.score * c.weight), reverse=True,
    )[:3]
    top_txt = "; ".join(
        f"{c.name} ({c.score:+.0f} × {c.weight:.0%})" for c in top_contrib
    ) or "(no valid components)"

    used = ", ".join(c.name for c in components if c.score is not None)
    missing = ", ".join(c.name for c in components if c.score is None)

    overview = (
        f"{ticker}: directional score {directional:+.1f} "
        f"(percentile {percentile:.0f}/100) → verdict '{verdict}', "
        f"confidence {confidence:.0f}/100. "
        f"Active weight used: {active_weight:.0%}. "
        f"Components voting: {used or '(none)'}. "
        f"{'Missing: ' + missing + '.' if missing else ''}"
    )

    why = (
        f"Top contributors (score × weight): {top_txt}. "
        f"The directional score is the weighted sum of component scores; "
        f"weights are renormalized over the components that returned data, "
        f"so a missing module does not change the sign of the score."
    )

    if conflicts:
        conflict_txt = "Flagged conflicts: " + " | ".join(conflicts)
    else:
        conflict_txt = ("No cross-signal conflicts flagged — components are "
                        "broadly aligned on direction.")

    verdict_txt = {
        "Strong Buy": ("High-conviction long: most components agree and the "
                       "weighted signal is large. Review conflicts and the risk "
                       "component before sizing."),
        "Buy":        ("Positive tilt with majority agreement. A full position "
                       "is defensible if risk profile is acceptable."),
        "Hold":       ("Score inside the neutral band. No structural edge visible "
                       "— keep existing exposure, do not add or trim on signal alone."),
        "Reduce":     ("Negative tilt with majority agreement against the name. "
                       "Trim rather than add; if already short, press modestly."),
        "Avoid":      ("High-conviction negative: most components disagree with "
                       "holding. Exit unless a specific catalyst is expected to "
                       "override the structural picture."),
    }[verdict]

    return {
        "overview": overview,
        "why_this_score": why,
        "conflicts": conflict_txt,
        "verdict_interpretation": verdict_txt,
    }


# --- Entrypoint ----------------------------------------------------------

def compute(ticker: str) -> QuantScoreResult:
    ticker = ticker.upper().strip()
    td = data_mod.load(ticker)
    if td is None:
        return QuantScoreResult(
            ticker=ticker, directional_score=0.0, percentile_score=50.0,
            verdict="Hold", confidence=0.0, components=[],
            active_weight=0.0, conflicts=[],
            explanations={"overview": f"No data for {ticker}."},
            error=f"No price history for {ticker}.",
        )
    close = td.history["Close"]
    bench_td = data_mod.load("SPY")
    bench_df = bench_td.history if bench_td else None
    bench_close = bench_df["Close"] if bench_df is not None else None

    components = [
        _tech_component(td.history, bench_df),
        _regime_component(close),
        _valuation_component(ticker),
        _sentiment_component(ticker, close),
        _statistics_component(close, bench_close),
        _spectral_component(close),
        _topology_component(close),
        _risk_component(ticker),
    ]

    valid = [c for c in components if c.score is not None]
    active_w = sum(c.weight for c in valid)
    if active_w > 0:
        directional = sum(c.score * c.weight for c in valid) / active_w
    else:
        directional = 0.0

    directional = float(np.clip(directional, -100.0, 100.0))
    percentile = float((directional + 100.0) / 2.0)
    verdict = _verdict(directional)
    confidence = _confidence(components)
    conflicts = _flag_conflicts(components)
    explanations = _composite_explanation(
        ticker, directional, percentile, verdict, confidence,
        active_w, components, conflicts,
    )

    return QuantScoreResult(
        ticker=ticker,
        directional_score=directional,
        percentile_score=percentile,
        verdict=verdict,
        confidence=confidence,
        components=components,
        active_weight=active_w,
        conflicts=conflicts,
        explanations=explanations,
    )


# --- Serialization --------------------------------------------------------

def to_dict(r: QuantScoreResult) -> dict[str, Any]:
    return {
        "ticker": r.ticker,
        "directional_score": r.directional_score,
        "percentile_score": r.percentile_score,
        "verdict": r.verdict,
        "confidence": r.confidence,
        "active_weight": r.active_weight,
        "components": [asdict(c) for c in r.components],
        "conflicts": r.conflicts,
        "explanations": r.explanations,
        "error": r.error,
        "weights": WEIGHTS,
    }
