"""Topological Data Analysis on price return series.

Uses persistent homology (`ripser`) and the Mapper algorithm (`kmapper`) to
extract the "shape" of the return space — structure beyond what classical
statistics sees.

Pipeline:
  1. Log-returns of the price series.
  2. Takens time-delay embedding -> point cloud in R^d (default d=3, tau=1).
     Each point is a window of d consecutive returns. This turns a 1-D series
     into a geometric object where "clusters" and "loops" are well-defined.
  3. Persistent homology up to H_1:
        * B_0 = persistent connected components (regimes / clusters of behavior)
        * B_1 = persistent 1-D loops (evidence of cyclic / recurrent structure)
  4. Mapper graph (kmapper): a coarse simplicial complex visualization of the
     point cloud — nodes group similar days, edges connect nodes that overlap.

Interpretation for a PM:
  * High B_1 total persistence -> the stock's return trajectory genuinely
    re-visits similar configurations. That is what mean reversion looks like
    topologically.
  * High B_0 count -> distinct behavioral regimes (clusters) are visible,
    suggesting the stock is not a single-state process.

All functions pure. Input is a close-price Series.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist

_RIPSER_ERROR: str | None = None
try:
    from ripser import ripser as _ripser_fn
    _HAS_RIPSER = True
except Exception as _exc:
    _HAS_RIPSER = False
    _RIPSER_ERROR = f"{type(_exc).__name__}: {_exc}"

_KMAPPER_ERROR: str | None = None
try:
    import kmapper as km
    _HAS_KMAPPER = True
except Exception as _exc:
    _HAS_KMAPPER = False
    _KMAPPER_ERROR = f"{type(_exc).__name__}: {_exc}"

_SKLEARN_ERROR: str | None = None
try:
    from sklearn.cluster import DBSCAN
    from sklearn.decomposition import PCA
    _HAS_SKLEARN = True
except Exception as _exc:
    _HAS_SKLEARN = False
    _SKLEARN_ERROR = f"{type(_exc).__name__}: {_exc}"


# --------------------------------------------------------------------------- #
# dataclasses
# --------------------------------------------------------------------------- #

@dataclass
class PersistencePair:
    dim: int
    birth: float
    death: float
    persistence: float       # death - birth


@dataclass
class BettiSummary:
    b0_count: int            # persistent connected components (excluding the one at infinity)
    b1_count: int            # persistent 1-D loops
    b0_total_persistence: float
    b1_total_persistence: float
    b1_top_mean_persistence: float     # mean persistence of top-5 B_1 loops (or fewer)
    top_pairs: list[PersistencePair]   # top 5 by persistence across all dims


@dataclass
class MapperGraph:
    nodes: list[dict]        # [{id, size, members:[indices]}]
    edges: list[dict]        # [{source, target}]
    n_nodes: int
    n_edges: int
    available: bool
    error: str | None = None


@dataclass
class TopologyAnalysis:
    embedding_dim: int
    tau: int
    n_points: int
    scale: float             # median pairwise distance in the embedding
    betti: BettiSummary
    mapper: MapperGraph
    topological_signal: float      # -1..+1, positive = cyclic structure
    signal_label: str
    method: str                    # "ripser" | "unavailable"
    error: str | None
    explanations: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# building blocks
# --------------------------------------------------------------------------- #

def _takens_embedding(x: np.ndarray, dim: int, tau: int) -> np.ndarray:
    """Time-delay embedding. Output shape: (n - (dim-1)*tau, dim)."""
    n = len(x) - (dim - 1) * tau
    if n <= 0:
        return np.empty((0, dim))
    out = np.empty((n, dim))
    for i in range(n):
        out[i] = x[i : i + dim * tau : tau][:dim]
    return out


def _subsample(X: np.ndarray, max_points: int) -> np.ndarray:
    if len(X) <= max_points:
        return X
    idx = np.linspace(0, len(X) - 1, max_points).astype(int)
    return X[idx]


def _persistent_homology(X: np.ndarray) -> list[np.ndarray]:
    """Returns ripser diagrams: [H0_array, H1_array]. Each is (n_pairs, 2)."""
    result = _ripser_fn(X, maxdim=1)
    return result["dgms"]


def _summarize_betti(dgms: list[np.ndarray]) -> BettiSummary:
    pairs: list[PersistencePair] = []
    for dim, dgm in enumerate(dgms):
        if dgm.size == 0:
            continue
        for birth, death in dgm:
            if np.isinf(death):
                # The essential (infinite-persistence) feature — skip.
                continue
            pairs.append(PersistencePair(
                dim=int(dim),
                birth=float(birth),
                death=float(death),
                persistence=float(death - birth),
            ))
    b0 = [p for p in pairs if p.dim == 0]
    b1 = [p for p in pairs if p.dim == 1]
    top = sorted(pairs, key=lambda p: p.persistence, reverse=True)[:5]
    b1_sorted = sorted(b1, key=lambda p: p.persistence, reverse=True)
    b1_top_mean = (float(np.mean([p.persistence for p in b1_sorted[:5]]))
                   if b1_sorted else 0.0)
    return BettiSummary(
        b0_count=len(b0),
        b1_count=len(b1),
        b0_total_persistence=float(sum(p.persistence for p in b0)),
        b1_total_persistence=float(sum(p.persistence for p in b1)),
        b1_top_mean_persistence=b1_top_mean,
        top_pairs=top,
    )


def _topological_signal(b1_top_mean: float, scale: float,
                        b1_count: int) -> tuple[float, str]:
    """Score cyclic structure by typical top-loop depth vs point-cloud scale.

    Uses the mean persistence of the top-5 B_1 loops (not the total), so the
    score reflects *how deep* the cycles are, not how many small loops were
    picked up as topological noise. A tanh squash keeps the output in (-1, +1)
    without the saturation issues of the earlier formulation.
    """
    if scale <= 0 or b1_count == 0 or b1_top_mean <= 0:
        return 0.0, "no significant cyclic structure"
    ratio = b1_top_mean / scale
    # Center of transition at ratio ≈ 0.1 (background noise threshold on equities).
    # Gain of 8 → ratio=0.25 saturates ~+0.92, ratio=0.0 ~-0.66.
    score = float(np.clip(np.tanh((ratio - 0.1) * 8.0), -1.0, 1.0))
    if ratio > 0.25:
        label = "strong cyclic structure — mean reversion has topological support"
    elif ratio > 0.15:
        label = "moderate cyclic structure"
    elif ratio > 0.08:
        label = "weak cyclic structure"
    else:
        label = "no significant cyclic structure"
    return score, label


def _mapper_graph(X: np.ndarray) -> MapperGraph:
    if not _HAS_KMAPPER:
        return MapperGraph(nodes=[], edges=[], n_nodes=0, n_edges=0,
                           available=False, error=_KMAPPER_ERROR)
    if not _HAS_SKLEARN:
        return MapperGraph(nodes=[], edges=[], n_nodes=0, n_edges=0,
                           available=False, error=_SKLEARN_ERROR)
    try:
        mapper = km.KeplerMapper(verbose=0)
        lens = mapper.fit_transform(X, projection=PCA(n_components=1))
        # Adaptive DBSCAN eps: use the 15th percentile of pairwise distances.
        dists = pdist(X)
        eps = float(np.percentile(dists, 15)) if len(dists) > 0 else 0.5
        eps = max(eps, 1e-6)
        graph = mapper.map(
            lens, X,
            cover=km.Cover(n_cubes=10, perc_overlap=0.3),
            clusterer=DBSCAN(eps=eps, min_samples=2),
        )
        nodes: list[dict] = []
        for name, members in graph["nodes"].items():
            nodes.append({
                "id": name,
                "size": int(len(members)),
                "members": [int(m) for m in members],
            })
        edges: list[dict] = []
        for src, dsts in graph["links"].items():
            for dst in dsts:
                edges.append({"source": src, "target": dst})
        return MapperGraph(
            nodes=nodes, edges=edges,
            n_nodes=len(nodes), n_edges=len(edges),
            available=True,
        )
    except Exception as exc:
        return MapperGraph(
            nodes=[], edges=[], n_nodes=0, n_edges=0,
            available=False,
            error=f"{type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# narrative
# --------------------------------------------------------------------------- #

def _explain(betti: BettiSummary, mapper: MapperGraph,
             signal: float, signal_label: str) -> dict[str, str]:
    out: dict[str, str] = {}

    if betti.b0_count >= 6:
        out["b0"] = (
            f"B_0 = {betti.b0_count}: the return space contains {betti.b0_count} "
            "persistent clusters, meaning the stock's day-to-day behavior splits into "
            "several distinct modes rather than one continuous blob. This is a "
            "topological footprint of multi-regime behavior."
        )
    elif betti.b0_count >= 2:
        out["b0"] = (
            f"B_0 = {betti.b0_count}: a small number of persistent clusters exist — "
            "some regime separation visible, but the stock mostly lives in a single "
            "behavioral mode."
        )
    else:
        out["b0"] = (
            "B_0 shows one dominant cluster — return behavior is topologically unified. "
            "No strong regime separation visible via homology."
        )

    if betti.b1_count == 0:
        out["b1"] = (
            "B_1 = 0: no persistent loops in the return space. Topologically, the stock "
            "does not revisit similar return configurations in any robust way — no "
            "support for mean reversion from the homology."
        )
    elif betti.b1_count >= 3:
        out["b1"] = (
            f"B_1 = {betti.b1_count}: multiple persistent loops detected in the embedding. "
            "The return trajectory genuinely re-visits similar configurations — this is "
            "the topological fingerprint of cyclic / recurrent dynamics. Classical "
            "mean-reversion strategies have a structural basis here."
        )
    else:
        out["b1"] = (
            f"B_1 = {betti.b1_count}: a modest number of persistent loops. The stock "
            "shows some cyclic structure, but it is not dominant."
        )

    out["signal"] = (
        f"Topological signal = {signal:+.2f}  ({signal_label}). "
        "This score is total B_1 persistence scaled against the typical point-spacing "
        "in the embedding — it answers 'how much cyclic structure is there, relative to "
        "random noise?'. Positive scores argue for mean reversion; zero argues against."
    )

    if mapper.available:
        out["mapper"] = (
            f"Mapper graph: {mapper.n_nodes} nodes, {mapper.n_edges} edges. Each node "
            "is a cluster of days with similar return profiles. Edges connect nodes that "
            "share days — i.e. the stock transitions between those modes. Reading the "
            "graph: branches = distinct behavioral modes, loops in the graph = cyclic "
            "structure in time, chains = directional drift."
        )
    else:
        suffix = f" ({mapper.error})" if mapper.error else ""
        out["mapper"] = f"Mapper unavailable{suffix}."

    if signal > 0.3:
        out["interpretation"] = (
            "Topology is telling us this stock's recent behavior has genuine cyclic "
            "structure — return space loops back on itself, meaning the stock repeatedly "
            "revisits similar states. Mean-reversion strategies have structural support "
            "here. Combine with spectral: if FFT cycle phase is 'near trough' AND "
            "topology shows loops, that's a meaningful alignment and a real setup."
        )
    elif signal > 0:
        out["interpretation"] = (
            "Topology shows mild cyclic structure — the stock does revisit similar "
            "states, but weakly. Mean reversion is a soft tilt, not a signal to trade on "
            "alone."
        )
    else:
        out["interpretation"] = (
            "Topology shows no meaningful cyclic structure. Return space looks either "
            "random-walk-like or monotonically drifting. Do not expect mean reversion to "
            "add value here — trend-following is structurally more aligned with the shape "
            "of the data."
        )
    return out


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #

def _unavailable(reason: str) -> TopologyAnalysis:
    return TopologyAnalysis(
        embedding_dim=0, tau=0, n_points=0, scale=0.0,
        betti=BettiSummary(0, 0, 0.0, 0.0, 0.0, []),
        mapper=MapperGraph([], [], 0, 0, False, reason),
        topological_signal=0.0, signal_label="unavailable",
        method="unavailable", error=reason,
        explanations={"overview": f"Topology module unavailable: {reason}"},
    )


def compute(close: pd.Series,
            embedding_dim: int = 3,
            tau: int = 1,
            lookback_days: int = 252,
            max_points: int = 300) -> TopologyAnalysis:
    if not _HAS_RIPSER:
        return _unavailable(f"ripser unavailable ({_RIPSER_ERROR})")
    rets = np.log(close / close.shift()).dropna().to_numpy()
    if len(rets) < 50:
        raise ValueError("Need at least 50 returns for topology.")
    rets = rets[-min(len(rets), lookback_days):]

    X = _takens_embedding(rets, dim=embedding_dim, tau=tau)
    if len(X) < 20:
        raise ValueError("Time-delay embedding has too few points.")
    X = _subsample(X, max_points)

    dists = pdist(X)
    scale = float(np.median(dists)) if len(dists) > 0 else 1.0

    dgms = _persistent_homology(X)
    betti = _summarize_betti(dgms)
    signal, label = _topological_signal(
        betti.b1_top_mean_persistence, scale, betti.b1_count,
    )
    mapper = _mapper_graph(X)
    explanations = _explain(betti, mapper, signal, label)

    return TopologyAnalysis(
        embedding_dim=embedding_dim, tau=tau,
        n_points=len(X), scale=scale,
        betti=betti, mapper=mapper,
        topological_signal=signal, signal_label=label,
        method="ripser", error=None,
        explanations=explanations,
    )


def to_dict(t: TopologyAnalysis) -> dict[str, Any]:
    return {
        "method": t.method,
        "error": t.error,
        "embedding_dim": t.embedding_dim,
        "tau": t.tau,
        "n_points": t.n_points,
        "scale": t.scale,
        "topological_signal": t.topological_signal,
        "signal_label": t.signal_label,
        "betti": {
            "b0_count": t.betti.b0_count,
            "b1_count": t.betti.b1_count,
            "b0_total_persistence": t.betti.b0_total_persistence,
            "b1_total_persistence": t.betti.b1_total_persistence,
            "b1_top_mean_persistence": t.betti.b1_top_mean_persistence,
            "top_pairs": [asdict(p) for p in t.betti.top_pairs],
        },
        "mapper": {
            "available": t.mapper.available,
            "error": t.mapper.error,
            "n_nodes": t.mapper.n_nodes,
            "n_edges": t.mapper.n_edges,
            "nodes": t.mapper.nodes,
            "edges": t.mapper.edges,
        },
        "explanations": t.explanations,
    }
