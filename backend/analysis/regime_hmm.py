"""Hidden Markov Model regime detection.

Separate module from the legacy `regime.py` (which is a simple trend-rule classifier).
This one fits a Gaussian HMM with 4 hidden states on a (trend, vol) feature pair and
maps those states to Bull / Bear / Sideways / Volatile using their fitted means.

Design choices
--------------
Features (2-D, per day):
    * 5-day mean of log returns, annualized  -> captures short-term trend
    * 20-day stdev of log returns, annualized -> captures vol level

Why 4 regimes and not 2? PMs think in 4 buckets (directional up / directional down /
chop / crisis). Two-state HMMs collapse bull-and-chop together; four gives the
interpretability the user asked for at the cost of slightly noisier fits, which
we mitigate with multi-start EM.

Robustness:
    * 5 random inits, keep the one with the highest log-likelihood.
    * Diagonal covariance to reduce overfitting.
    * If hmmlearn is unavailable, fall back to a GaussianMixture-based classifier
      (sklearn). This gives probabilistic regimes without the Markov transition
      structure, but all other outputs still populate so the frontend does not break.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import numpy as np
import pandas as pd

_HMM_ERROR: str | None = None
try:
    from hmmlearn.hmm import GaussianHMM  # noqa: F401  (used inside function)
    _HAS_HMM = True
except Exception as _exc:
    _HAS_HMM = False
    _HMM_ERROR = f"{type(_exc).__name__}: {_exc}"

_SKLEARN_ERROR: str | None = None
try:
    from sklearn.mixture import GaussianMixture  # noqa: F401
    _HAS_SKLEARN = True
except Exception as _exc:
    _HAS_SKLEARN = False
    _SKLEARN_ERROR = f"{type(_exc).__name__}: {_exc}"


TRADING_DAYS = 252
N_STATES = 4
REGIME_LABELS = ("Bull", "Bear", "Sideways", "Volatile")


@dataclass
class RegimeState:
    label: str                # "Bull" | "Bear" | "Sideways" | "Volatile"
    mean_return_ann: float    # center of this state in annualized-return space
    mean_vol_ann: float       # center in annualized-vol space
    current_prob: float       # posterior probability at the last observation


@dataclass
class TransitionRow:
    from_regime: str
    probabilities: dict[str, float]   # {"Bull": 0.92, "Bear": 0.01, ...}


@dataclass
class TimelinePoint:
    date: str
    regime: str
    confidence: float


@dataclass
class RegimeAnalysis:
    current_regime: str
    current_confidence: float
    states: list[RegimeState]
    transitions: list[TransitionRow]
    timeline: list[TimelinePoint]
    method: str               # "HMM" | "GMM" | "unavailable"
    error: str | None
    explanations: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# feature engineering
# --------------------------------------------------------------------------- #

def _build_features(close: pd.Series) -> pd.DataFrame:
    log_ret = np.log(close / close.shift()).rename("log_ret")
    trend = log_ret.rolling(5).mean() * TRADING_DAYS           # annualized trend
    vol = log_ret.rolling(20).std() * np.sqrt(TRADING_DAYS)    # annualized vol
    feats = pd.concat([trend.rename("trend"), vol.rename("vol")], axis=1).dropna()
    return feats


# --------------------------------------------------------------------------- #
# label assignment — deterministic mapping from fitted state indices to regimes
# --------------------------------------------------------------------------- #

def _assign_labels(state_means: np.ndarray) -> dict[int, str]:
    """Given K (return, vol) centroids, assign one of the 4 regime labels to each.

    Rule (works for any 4-state fit):
      * Highest-vol state -> Volatile
      * Of the remaining 3: highest mean return -> Bull,
                            lowest mean return  -> Bear,
                            middle              -> Sideways
    """
    K = state_means.shape[0]
    idx_by_vol = sorted(range(K), key=lambda i: state_means[i, 1], reverse=True)
    volatile_idx = idx_by_vol[0]
    rest = [i for i in range(K) if i != volatile_idx]
    rest_sorted_by_ret = sorted(rest, key=lambda i: state_means[i, 0], reverse=True)
    labels = {
        volatile_idx: "Volatile",
        rest_sorted_by_ret[0]: "Bull",
        rest_sorted_by_ret[-1]: "Bear",
    }
    if len(rest_sorted_by_ret) == 3:
        labels[rest_sorted_by_ret[1]] = "Sideways"
    return labels


# --------------------------------------------------------------------------- #
# fitters
# --------------------------------------------------------------------------- #

def _fit_hmm(X: np.ndarray, random_state_seeds=(0, 7, 13, 42, 123)):
    """Fit a GaussianHMM multiple times, keep the best (highest score)."""
    from hmmlearn.hmm import GaussianHMM
    best = None
    best_score = -np.inf
    for seed in random_state_seeds:
        try:
            m = GaussianHMM(
                n_components=N_STATES,
                covariance_type="diag",
                n_iter=200,
                tol=1e-3,
                random_state=seed,
                init_params="stmc",
            )
            m.fit(X)
            s = m.score(X)
            if s > best_score:
                best_score = s
                best = m
        except Exception:
            continue
    return best


def _fit_gmm(X: np.ndarray):
    """Fallback when hmmlearn is absent — GMM gives posteriors but no transitions."""
    from sklearn.mixture import GaussianMixture
    m = GaussianMixture(
        n_components=N_STATES, covariance_type="diag",
        n_init=5, random_state=0, max_iter=500,
    )
    m.fit(X)
    return m


# --------------------------------------------------------------------------- #
# main entrypoint
# --------------------------------------------------------------------------- #

def compute(close: pd.Series, timeline_days: int = 504) -> RegimeAnalysis:
    if len(close) < 80:
        raise ValueError("Need at least 80 observations for regime detection.")
    feats = _build_features(close)
    if len(feats) < 60:
        raise ValueError("Not enough clean feature rows to fit the regime model.")

    X = feats[["trend", "vol"]].to_numpy()
    dates = feats.index

    # ---- Try HMM first, fall back to GMM if unavailable ----
    method: str
    error: str | None = None
    transitions_mat: np.ndarray | None = None

    if _HAS_HMM:
        model = _fit_hmm(X)
        if model is None:
            if _HAS_SKLEARN:
                model = _fit_gmm(X)
                method = "GMM"
                error = "HMM fit failed on all seeds; fell back to GMM."
                state_means = model.means_
                posteriors = model.predict_proba(X)
            else:
                return _unavailable("HMM fit failed and sklearn missing.")
        else:
            method = "HMM"
            state_means = model.means_
            posteriors = model.predict_proba(X)
            transitions_mat = model.transmat_
    elif _HAS_SKLEARN:
        model = _fit_gmm(X)
        method = "GMM"
        error = f"hmmlearn unavailable ({_HMM_ERROR}); using GMM fallback."
        state_means = model.means_
        posteriors = model.predict_proba(X)
    else:
        return _unavailable(
            f"Neither hmmlearn nor sklearn available. "
            f"hmmlearn: {_HMM_ERROR}. sklearn: {_SKLEARN_ERROR}."
        )

    # ---- Map fitted state indices to regime labels ----
    label_of = _assign_labels(state_means)

    # ---- Build states block with current posterior per label ----
    current = posteriors[-1]
    states: list[RegimeState] = []
    # regime index in sort order Bull / Bear / Sideways / Volatile for consistent display
    label_to_idx = {v: k for k, v in label_of.items()}
    for lab in REGIME_LABELS:
        if lab not in label_to_idx:
            continue
        idx = label_to_idx[lab]
        states.append(RegimeState(
            label=lab,
            mean_return_ann=float(state_means[idx, 0]),
            mean_vol_ann=float(state_means[idx, 1]),
            current_prob=float(current[idx]),
        ))

    # ---- Current regime = argmax of current posterior ----
    cur_idx = int(np.argmax(current))
    current_regime = label_of.get(cur_idx, "Unknown")
    current_conf = float(current[cur_idx])

    # ---- Transition matrix ----
    transitions: list[TransitionRow] = []
    if transitions_mat is not None:
        for i in range(transitions_mat.shape[0]):
            from_lab = label_of.get(i, f"State{i}")
            probs = {
                label_of.get(j, f"State{j}"): float(transitions_mat[i, j])
                for j in range(transitions_mat.shape[1])
            }
            transitions.append(TransitionRow(from_regime=from_lab, probabilities=probs))
    else:
        # GMM has no transitions — emit a diagonal placeholder so the shape is stable
        for lab in REGIME_LABELS:
            transitions.append(TransitionRow(
                from_regime=lab,
                probabilities={l: (1.0 if l == lab else 0.0) for l in REGIME_LABELS},
            ))

    # ---- Timeline (last `timeline_days` rows) ----
    tail = slice(-min(timeline_days, len(posteriors)), None)
    tail_dates = dates[tail]
    tail_post = posteriors[tail]
    timeline: list[TimelinePoint] = []
    for d, p in zip(tail_dates, tail_post):
        best_idx = int(np.argmax(p))
        timeline.append(TimelinePoint(
            date=pd.Timestamp(d).strftime("%Y-%m-%d"),
            regime=label_of.get(best_idx, "Unknown"),
            confidence=float(p[best_idx]),
        ))

    explanations = _explain(
        current_regime, current_conf, states, transitions, timeline, method,
    )
    return RegimeAnalysis(
        current_regime=current_regime,
        current_confidence=current_conf,
        states=states,
        transitions=transitions,
        timeline=timeline,
        method=method,
        error=error,
        explanations=explanations,
    )


def _unavailable(reason: str) -> RegimeAnalysis:
    return RegimeAnalysis(
        current_regime="Unknown",
        current_confidence=0.0,
        states=[],
        transitions=[],
        timeline=[],
        method="unavailable",
        error=reason,
        explanations={"overview": f"Regime model unavailable: {reason}"},
    )


# --------------------------------------------------------------------------- #
# narrative
# --------------------------------------------------------------------------- #

def _regime_blurb(label: str) -> str:
    return {
        "Bull": (
            "Trending up with contained volatility. Expected returns positive, "
            "drawdowns shallow and short; momentum strategies work well here."
        ),
        "Bear": (
            "Trending down with elevated but not extreme vol. Expected returns "
            "negative, rallies get sold; risk of further downside dominates."
        ),
        "Sideways": (
            "No clear direction, compressed vol. Mean-reversion signals work; "
            "trend signals under-perform. Position small."
        ),
        "Volatile": (
            "High-variance regime — direction uncertain, magnitude large. This is "
            "the crisis / earnings-shock bucket. Tail risk is live; size down."
        ),
    }.get(label, "Undetermined regime.")


def _explain(current_regime: str, current_conf: float,
             states: list[RegimeState],
             transitions: list[TransitionRow],
             timeline: list[TimelinePoint],
             method: str) -> dict[str, str]:
    out: dict[str, str] = {}

    # overview
    out["overview"] = (
        f"The {method} regime model says the stock is currently in a {current_regime} "
        f"regime with {current_conf:.0%} confidence. "
        f"{_regime_blurb(current_regime)}"
    )

    # quantitative description of current state
    cur = next((s for s in states if s.label == current_regime), None)
    if cur is not None:
        out["current_state"] = (
            f"The Bull/Bear/Sideways/Volatile assignment is data-driven: this regime's "
            f"fitted center sits at {cur.mean_return_ann:+.0%} annualized return and "
            f"{cur.mean_vol_ann:.0%} annualized vol — that is the typical day's "
            "risk/return profile when the stock is in this state."
        )

    # persistence — how sticky is the current regime
    if transitions:
        cur_row = next((r for r in transitions if r.from_regime == current_regime), None)
        if cur_row is not None and current_regime in cur_row.probabilities:
            stay = cur_row.probabilities[current_regime]
            most_likely_next = max(
                (l for l in cur_row.probabilities if l != current_regime),
                key=lambda l: cur_row.probabilities[l],
                default=None,
            )
            next_prob = cur_row.probabilities.get(most_likely_next, 0.0) if most_likely_next else 0.0
            if stay > 0.95:
                stick = "extremely sticky — regime changes are rare"
            elif stay > 0.85:
                stick = "sticky — regime usually persists day-to-day"
            elif stay > 0.7:
                stick = "moderately persistent"
            else:
                stick = "unstable — frequent regime flips"
            if method == "HMM" and most_likely_next:
                out["persistence"] = (
                    f"Transition matrix: {stay:.0%} probability of staying in {current_regime} "
                    f"tomorrow; if it flips, the most likely next regime is "
                    f"{most_likely_next} ({next_prob:.0%}). The regime is {stick}."
                )

    # historical pattern
    if timeline:
        from collections import Counter
        counts = Counter(p.regime for p in timeline)
        total = sum(counts.values())
        top = counts.most_common()
        parts = [f"{lab} {cnt/total:.0%}" for lab, cnt in top]
        out["history"] = (
            f"Over the last {total} trading days the time-split across regimes was: "
            + ", ".join(parts) + "."
        )

    return out


# --------------------------------------------------------------------------- #
# JSON serialization
# --------------------------------------------------------------------------- #

def to_dict(r: RegimeAnalysis) -> dict[str, Any]:
    return {
        "method": r.method,
        "error": r.error,
        "current_regime": r.current_regime,
        "current_confidence": r.current_confidence,
        "states": [asdict(s) for s in r.states],
        "transitions": [
            {"from_regime": t.from_regime, "probabilities": t.probabilities}
            for t in r.transitions
        ],
        "timeline": [asdict(p) for p in r.timeline],
        "explanations": r.explanations,
    }
