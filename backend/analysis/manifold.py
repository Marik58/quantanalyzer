"""Manifold learning: PCA for factor decomposition, UMAP for visual embedding.

Pipeline:
  1. Build an 11-column feature matrix per day from price history (returns at
     multiple horizons, vol, ATR ratio, RSI, MACD, Bollinger %B, SMA-distance).
  2. Standardize features (z-score each column).
  3. PCA -> top 3 components with signed loadings and explained variance.
     Each component is auto-named by whichever feature *category* dominates
     its top loadings (direction / volatility / momentum-mean-reversion).
  4. UMAP -> 2-D embedding of the feature matrix for frontend rendering.
     Each point = one trading day.

Answers: *what* is this stock's daily behavior really a function of — trend,
vol regime, or momentum/mean-reversion pressure? Positions the stock on its
own "behavioral manifold" so similar days sit near each other.

All functions pure. Input is close/high/low price Series.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import numpy as np
import pandas as pd

_SKLEARN_ERROR: str | None = None
try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    _HAS_SKLEARN = True
except Exception as _exc:
    _HAS_SKLEARN = False
    _SKLEARN_ERROR = f"{type(_exc).__name__}: {_exc}"

_UMAP_ERROR: str | None = None
try:
    import umap
    _HAS_UMAP = True
except Exception as _exc:
    _HAS_UMAP = False
    _UMAP_ERROR = f"{type(_exc).__name__}: {_exc}"


TRADING_DAYS = 252

# Maps each feature to a semantic category. Used for auto-naming PCs.
FEATURE_CATEGORY = {
    "log_ret":      "direction",
    "ret_5d":       "direction",
    "ret_20d":      "direction",
    "ret_60d":      "direction",
    "sma_dist_50":  "direction",
    "sma_dist_200": "direction",
    "vol_20":       "volatility",
    "atr_ratio":    "volatility",
    "rsi_norm":     "momentum_mr",
    "macd_hist":    "momentum_mr",
    "bb_pct":       "momentum_mr",
}
CATEGORY_DISPLAY = {
    "direction":   "Trend / Directional",
    "volatility":  "Volatility",
    "momentum_mr": "Momentum / Mean-Reversion",
}


@dataclass
class FactorLoading:
    feature: str
    loading: float          # signed loading in [-1, 1] direction


@dataclass
class PrincipalComponent:
    index: int              # 1-based
    name: str               # "Trend / Directional" | "Volatility" | "Momentum / Mean-Reversion" | "Mixed"
    explained_variance: float   # 0..1
    top_loadings: list[FactorLoading]


@dataclass
class UMAPPoint:
    date: str
    x: float
    y: float


@dataclass
class ManifoldAnalysis:
    n_features: int
    n_samples: int
    feature_names: list[str]
    components: list[PrincipalComponent]
    cumulative_variance_top3: float
    umap_points: list[UMAPPoint]
    umap_available: bool
    umap_error: str | None
    method_error: str | None
    explanations: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# feature engineering — self-contained so this module doesn't depend on
# indicators.py (keeps the blast radius small)
# --------------------------------------------------------------------------- #

def _build_features(close: pd.Series, high: pd.Series,
                    low: pd.Series) -> pd.DataFrame:
    log_ret = np.log(close / close.shift())

    ret_5d = close.pct_change(5)
    ret_20d = close.pct_change(20)
    ret_60d = close.pct_change(60)

    vol_20 = log_ret.rolling(20).std() * np.sqrt(TRADING_DAYS)

    prev_close = close.shift()
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_ratio = atr14 / close

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi14 = 100 - 100 / (1 + rs)
    rsi_norm = (rsi14 - 50) / 50     # -> ~[-1, 1]

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    sma_dist_50 = (close / sma50) - 1
    sma_dist_200 = (close / sma200) - 1

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_low = bb_mid - 2 * bb_std
    bb_high = bb_mid + 2 * bb_std
    bb_pct = (close - bb_low) / (bb_high - bb_low) - 0.5   # centered

    feats = pd.concat({
        "log_ret":      log_ret,
        "ret_5d":       ret_5d,
        "ret_20d":      ret_20d,
        "ret_60d":      ret_60d,
        "vol_20":       vol_20,
        "atr_ratio":    atr_ratio,
        "rsi_norm":     rsi_norm,
        "macd_hist":    macd_hist,
        "bb_pct":       bb_pct,
        "sma_dist_50":  sma_dist_50,
        "sma_dist_200": sma_dist_200,
    }, axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    return feats


# --------------------------------------------------------------------------- #
# PCA helpers
# --------------------------------------------------------------------------- #

def _name_pc(loadings: dict[str, float]) -> str:
    """Assign a category name to a PC by summing squared loadings per category."""
    scores = {cat: 0.0 for cat in CATEGORY_DISPLAY}
    for feat, w in loadings.items():
        cat = FEATURE_CATEGORY.get(feat)
        if cat:
            scores[cat] += w * w
    total = sum(scores.values())
    if total == 0:
        return "Mixed"
    top_cat, top_score = max(scores.items(), key=lambda kv: kv[1])
    # Require the winning category to own at least 45% of loading-energy,
    # otherwise call it mixed — avoids false-precise naming.
    if top_score / total < 0.45:
        return "Mixed"
    return CATEGORY_DISPLAY[top_cat]


def _run_pca(X: np.ndarray, feature_names: list[str]) -> list[PrincipalComponent]:
    Xs = StandardScaler().fit_transform(X)
    pca = PCA(n_components=min(3, Xs.shape[1]))
    pca.fit(Xs)
    comps: list[PrincipalComponent] = []
    for i, (comp, ev) in enumerate(zip(pca.components_, pca.explained_variance_ratio_), 1):
        loadings = {n: float(c) for n, c in zip(feature_names, comp)}
        top5 = sorted(loadings.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
        comps.append(PrincipalComponent(
            index=i,
            name=_name_pc(loadings),
            explained_variance=float(ev),
            top_loadings=[FactorLoading(feature=n, loading=l) for n, l in top5],
        ))
    return comps


# --------------------------------------------------------------------------- #
# UMAP
# --------------------------------------------------------------------------- #

def _run_umap(X: np.ndarray, dates: pd.DatetimeIndex) -> tuple[list[UMAPPoint], str | None]:
    if not _HAS_UMAP:
        return [], _UMAP_ERROR
    try:
        Xs = StandardScaler().fit_transform(X)
        reducer = umap.UMAP(
            n_components=2, n_neighbors=15, min_dist=0.1,
            random_state=42, n_jobs=1,
        )
        embed = reducer.fit_transform(Xs)
        points = [
            UMAPPoint(
                date=pd.Timestamp(d).strftime("%Y-%m-%d"),
                x=float(e[0]), y=float(e[1]),
            )
            for d, e in zip(dates, embed)
        ]
        return points, None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# narrative
# --------------------------------------------------------------------------- #

def _pc_description(name: str) -> str:
    if name == "Trend / Directional":
        return ("days driven by directional moves — momentum and trend-following "
                "signals are aligned with this axis")
    if name == "Volatility":
        return ("days driven by volatility regime — vol expansion and compression "
                "are the story, not the sign of the move")
    if name == "Momentum / Mean-Reversion":
        return ("days driven by oscillator state — RSI extremes, MACD crossovers, "
                "Bollinger band interactions")
    return "mixed drivers — no single clean interpretation"


def _explain(components: list[PrincipalComponent], cum_var: float,
             umap_available: bool, umap_error: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not components:
        out["overview"] = "PCA could not be computed."
        return out

    pc1 = components[0]
    out["overview"] = (
        f"The top 3 factors explain {cum_var:.0%} of the variance in this stock's "
        f"daily feature profile. PC1 alone explains {pc1.explained_variance:.0%} "
        f"and represents the {pc1.name} factor — this is the primary axis along "
        "which the stock actually moves."
    )

    for pc in components:
        loadings_str = ", ".join(
            f"{l.feature} ({l.loading:+.2f})" for l in pc.top_loadings[:3]
        )
        out[f"pc{pc.index}"] = (
            f"PC{pc.index} ({pc.name}): {pc.explained_variance:.0%} of variance. "
            f"Top loadings: {loadings_str}. These are {_pc_description(pc.name)}."
        )

    if umap_available:
        out["umap"] = (
            "UMAP 2-D embedding is available. Each point is one trading day, "
            "positioned so that days with similar feature profiles sit near each "
            "other. Reading the embedding: tight clusters = recurring behavioral "
            "states, long arcs = directional drift periods, tangled interior = "
            "chop / no structure."
        )
    else:
        err = f" ({umap_error})" if umap_error else ""
        out["umap"] = f"UMAP embedding unavailable{err}."

    # Overall interpretation keyed to PC1's category
    if pc1.name == "Trend / Directional":
        out["interpretation"] = (
            "The dominant factor driving this stock is trend/direction — daily "
            "behavior is fundamentally about 'is it going up or down'. Trend-"
            f"following strategies are structurally aligned here. PC1 at "
            f"{pc1.explained_variance:.0%} "
            + ("(above 40%) means directionality dominates — " if pc1.explained_variance > 0.4
               else "(below 40%) means direction leads but does not dominate — ")
            + "other factors still matter."
        )
    elif pc1.name == "Volatility":
        out["interpretation"] = (
            "The dominant factor is volatility regime. Daily behavior is driven by "
            "vol expansion and compression more than by direction — what matters is "
            "the size of moves, not their sign. Risk sizing discipline is critical "
            "on this name; vol-targeting strategies fit structurally."
        )
    elif pc1.name == "Momentum / Mean-Reversion":
        out["interpretation"] = (
            "The dominant factor is momentum / mean-reversion pressure. Daily "
            "behavior tracks oscillator state — RSI extremes, MACD turns, Bollinger "
            "band interactions — more than pure trend. Mean-reversion and momentum-"
            "reversal strategies have a structural basis here."
        )
    else:
        out["interpretation"] = (
            "No single factor dominates — trend, vol, and mean-reversion loadings "
            "are mixed across the top PCs. Behavior does not reduce cleanly to "
            "one axis; this name likely responds to multiple regimes simultaneously."
        )
    return out


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #

def compute(close: pd.Series, high: pd.Series, low: pd.Series,
            lookback_days: int = 504) -> ManifoldAnalysis:
    if not _HAS_SKLEARN:
        return ManifoldAnalysis(
            n_features=0, n_samples=0, feature_names=[],
            components=[], cumulative_variance_top3=0.0,
            umap_points=[], umap_available=False,
            umap_error=None, method_error=_SKLEARN_ERROR,
            explanations={"overview": f"sklearn unavailable: {_SKLEARN_ERROR}"},
        )

    feats = _build_features(close, high, low)
    if len(feats) < 60:
        raise ValueError("Not enough history for manifold analysis.")
    feats = feats.iloc[-min(len(feats), lookback_days):]

    X = feats.to_numpy()
    dates = feats.index
    feature_names = list(feats.columns)

    components = _run_pca(X, feature_names)
    cum_var = float(sum(c.explained_variance for c in components))

    umap_points, umap_err = _run_umap(X, dates)
    umap_available = len(umap_points) > 0

    explanations = _explain(components, cum_var, umap_available, umap_err)

    return ManifoldAnalysis(
        n_features=len(feature_names),
        n_samples=len(X),
        feature_names=feature_names,
        components=components,
        cumulative_variance_top3=cum_var,
        umap_points=umap_points,
        umap_available=umap_available,
        umap_error=umap_err,
        method_error=None,
        explanations=explanations,
    )


def to_dict(m: ManifoldAnalysis) -> dict[str, Any]:
    return {
        "method_error": m.method_error,
        "n_features": m.n_features,
        "n_samples": m.n_samples,
        "feature_names": m.feature_names,
        "cumulative_variance_top3": m.cumulative_variance_top3,
        "components": [
            {
                "index": c.index,
                "name": c.name,
                "explained_variance": c.explained_variance,
                "top_loadings": [asdict(l) for l in c.top_loadings],
            }
            for c in m.components
        ],
        "umap": {
            "available": m.umap_available,
            "error": m.umap_error,
            "n_points": len(m.umap_points),
            "points": [asdict(p) for p in m.umap_points],
        },
        "explanations": m.explanations,
    }
