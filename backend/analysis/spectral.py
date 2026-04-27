"""Spectral analysis: wavelet decomposition, FFT cycle detection, Hilbert phase.

Answers four questions a PM cares about:
  1. Which time-scale (short / medium / long) is driving the stock?
  2. What hidden periodicities exist in price?
  3. Where in the dominant cycle is the stock right now?
  4. What does all of that imply for near-term behavior?

Design notes:
  * FFT runs on log returns (stationary-ish), not price. That removes trend leakage.
  * Wavelet decomposition also runs on returns, using Daubechies-4 — standard in finance.
  * Cycle phase uses a Butterworth bandpass around the dominant period, then a Hilbert
    transform on the detrended log-price to get instantaneous phase.
  * If `pywt` is unavailable the wavelet block degrades gracefully and the rest still works.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy.fft import rfft, rfftfreq

pywt = None
_PYWT_ERROR: str | None = None
try:
    import pywt as _pywt_mod
    pywt = _pywt_mod
    _HAS_PYWT = True
except Exception as _exc:  # ImportError, ModuleNotFoundError, OSError (DLL), ABI errs...
    _HAS_PYWT = False
    _PYWT_ERROR = f"{type(_exc).__name__}: {_exc}"


@dataclass
class WaveletBand:
    name: str            # "short" | "medium" | "long"
    period_range: str
    levels: str          # which DWT detail/approx levels compose this band
    energy_share: float  # 0..1, fraction of total variance in this band


@dataclass
class WaveletDecomposition:
    bands: list[WaveletBand]
    dominant_band: str       # "short" | "medium" | "long" | "unknown"
    available: bool
    error: str | None = None   # populated if pywt import failed


@dataclass
class DominantCycle:
    period_days: float
    power: float     # normalized 0..1 vs the strongest cycle
    label: str       # "short (<10d)" | "medium (10-40d)" | "long (>40d)"


@dataclass
class FFTResult:
    dominant_cycles: list[DominantCycle]
    noise_ratio: float   # 0..1 — higher = more random-walk-like


@dataclass
class CycleSignal:
    dominant_period_days: float
    phase_radians: float       # in [-pi, pi]
    phase_label: str           # near trough | rising | near peak | falling
    direction: str             # "up" | "down" | "flat"
    strength: float            # 0..1 — confidence the cycle actually exists
    score: float               # -1..+1 — near-term bullish (positive) / bearish (negative)


@dataclass
class SpectralAnalysis:
    wavelet: WaveletDecomposition
    fft: FFTResult
    cycle: CycleSignal
    explanations: dict[str, str]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift()).dropna()


def _wavelet_decomp(returns: pd.Series) -> WaveletDecomposition:
    if not _HAS_PYWT:
        return WaveletDecomposition(
            bands=[], dominant_band="unknown", available=False,
            error=_PYWT_ERROR,
        )
    r = returns.to_numpy()
    if len(r) < 32:
        return WaveletDecomposition(bands=[], dominant_band="unknown", available=True)
    # 4-level db4 DWT. coeffs layout: [cA4, cD4, cD3, cD2, cD1]
    # D1 ~ 2-4d, D2 ~ 4-8d, D3 ~ 8-16d, D4 ~ 16-32d, A4 ~ 32+d
    coeffs = pywt.wavedec(r, "db4", level=4)
    energies = [float(np.sum(c ** 2)) for c in coeffs]
    total = sum(energies)
    if total == 0:
        return WaveletDecomposition(bands=[], dominant_band="unknown", available=True)
    short_e = energies[4] + energies[3]    # D1 + D2
    med_e = energies[2]                    # D3
    long_e = energies[1] + energies[0]     # D4 + A4
    shares = {
        "short": short_e / total,
        "medium": med_e / total,
        "long": long_e / total,
    }
    bands = [
        WaveletBand("short",  "2-8 days",  "D1+D2", shares["short"]),
        WaveletBand("medium", "8-16 days", "D3",    shares["medium"]),
        WaveletBand("long",   "16+ days",  "D4+A4", shares["long"]),
    ]
    return WaveletDecomposition(
        bands=bands,
        dominant_band=max(shares, key=shares.get),
        available=True,
    )


def _fft_cycles(returns: pd.Series, top_n: int = 3,
                min_period: int = 4, max_period: int = 120) -> FFTResult:
    r = returns.to_numpy()
    n = len(r)
    if n < 32:
        return FFTResult(dominant_cycles=[], noise_ratio=1.0)
    r = r - r.mean()
    window = sp_signal.windows.hann(n)
    rw = r * window

    freqs = rfftfreq(n, d=1.0)          # cycles per trading day
    power = np.abs(rfft(rw)) ** 2

    valid = (freqs > 1.0 / max_period) & (freqs < 1.0 / min_period)
    valid_idx = np.where(valid)[0]
    if len(valid_idx) == 0:
        return FFTResult(dominant_cycles=[], noise_ratio=1.0)
    valid_power = power[valid_idx]

    peak_rel, _ = sp_signal.find_peaks(valid_power)
    if len(peak_rel) == 0:
        top_rel = np.argsort(valid_power)[-top_n:][::-1]
    else:
        ranked = peak_rel[np.argsort(valid_power[peak_rel])[::-1]]
        top_rel = ranked[:top_n]

    max_p = float(valid_power.max())
    cycles: list[DominantCycle] = []
    for rel in top_rel:
        abs_idx = valid_idx[rel]
        period = float(1.0 / freqs[abs_idx])
        p_norm = float(valid_power[rel] / max_p) if max_p > 0 else 0.0
        if period < 10:
            label = "short (<10d)"
        elif period < 40:
            label = "medium (10-40d)"
        else:
            label = "long (>40d)"
        cycles.append(DominantCycle(period_days=period, power=p_norm, label=label))

    # Noise ratio: how much of total (non-DC) power sits in the single strongest bin.
    # Higher share -> cleaner cycle. Invert for "noise ratio".
    nondc_total = float(power[1:].sum())
    top_share = float(valid_power.max() / nondc_total) if nondc_total > 0 else 0.0
    # Heuristic: a share of 10% is already a strong cycle for daily returns
    noise_ratio = float(max(0.0, min(1.0, 1.0 - top_share * 10)))
    return FFTResult(dominant_cycles=cycles, noise_ratio=noise_ratio)


def _cycle_signal(close: pd.Series, fft: FFTResult) -> CycleSignal:
    if not fft.dominant_cycles:
        return CycleSignal(
            dominant_period_days=0.0, phase_radians=0.0,
            phase_label="no dominant cycle", direction="flat",
            strength=0.0, score=0.0,
        )
    period = fft.dominant_cycles[0].period_days
    # Bandpass around the dominant period (±50% around it, in frequency)
    low = 1.0 / (period * 1.5)
    high = 1.0 / (period * 0.67)
    nyq = 0.5
    low_n = max(low / nyq, 1e-3)
    high_n = min(high / nyq, 0.99)
    if low_n >= high_n:
        return CycleSignal(
            dominant_period_days=period, phase_radians=0.0,
            phase_label="cycle too long to isolate", direction="flat",
            strength=0.0, score=0.0,
        )

    # Detrend log-price linearly so Hilbert phase reflects the cycle, not the trend.
    logp = np.log(close.to_numpy())
    x = np.arange(len(logp))
    slope, intercept = np.polyfit(x, logp, 1)
    detrended = logp - (slope * x + intercept)

    try:
        b, a = sp_signal.butter(4, [low_n, high_n], btype="band")
        filtered = sp_signal.filtfilt(b, a, detrended)
    except Exception:
        return CycleSignal(
            dominant_period_days=period, phase_radians=0.0,
            phase_label="filter failed", direction="flat",
            strength=0.0, score=0.0,
        )

    analytic = sp_signal.hilbert(filtered)
    phase = float(np.angle(analytic[-1]))
    amplitude = np.abs(analytic)
    amp_std = float(amplitude.std())
    strength = float(min(1.0, amplitude[-1] / (amp_std + 1e-9) / 2.0)) if amp_std > 0 else 0.0
    strength = max(0.0, min(1.0, strength))

    # phase in [-pi, pi]:
    #   ~0        rising through mean  (up)
    #   ~+pi/2    peak                 (down next)
    #   ~±pi      falling through mean (down)
    #   ~-pi/2    trough               (up next)
    pi = np.pi
    if -pi / 4 < phase < pi / 4:
        label, direction, base = "rising through mean", "up", 0.5
    elif pi / 4 <= phase < 3 * pi / 4:
        label, direction, base = "near cycle peak", "down", -0.7
    elif phase >= 3 * pi / 4 or phase <= -3 * pi / 4:
        label, direction, base = "falling through mean", "down", -0.5
    else:  # -3pi/4 < phase <= -pi/4
        label, direction, base = "near cycle trough", "up", 0.7

    score = float(np.clip(base * strength, -1.0, 1.0))
    return CycleSignal(
        dominant_period_days=float(period),
        phase_radians=phase,
        phase_label=label,
        direction=direction,
        strength=strength,
        score=score,
    )


# --------------------------------------------------------------------------- #
# explanations
# --------------------------------------------------------------------------- #

def _explain(wav: WaveletDecomposition, fft: FFTResult,
             cyc: CycleSignal) -> dict[str, str]:
    out: dict[str, str] = {}

    if not wav.available:
        suffix = f" ({wav.error})" if wav.error else ""
        out["wavelet"] = (
            "Wavelet decomposition unavailable — pywt could not be imported"
            f"{suffix}. Re-run `pip install -r requirements.txt` in the active venv."
        )
    elif not wav.bands:
        out["wavelet"] = "Not enough history for a meaningful wavelet decomposition."
    else:
        shares = {b.name: b.energy_share for b in wav.bands}
        if wav.dominant_band == "short":
            out["wavelet"] = (
                f"Short-term noise dominates — {shares['short']:.0%} of variance sits in "
                "the 2-8 day band. The stock's behavior is mostly day-to-day chop. "
                "Short-horizon swing signals will work; longer-horizon trend signals "
                "will be noisier here than on a typical large cap."
            )
        elif wav.dominant_band == "medium":
            out["wavelet"] = (
                f"Medium-term swings dominate — {shares['medium']:.0%} of variance sits "
                "in the 8-16 day band. Classic swing-cycle behavior; expect 2-3 week "
                "rhythms to drive the tape."
            )
        else:
            out["wavelet"] = (
                f"Long-term moves dominate — {shares['long']:.0%} of variance sits in "
                "the 16+ day band. Daily chop is muted relative to the broader trend. "
                "This is a trend-follower's stock, not a day-trader's."
            )

    if not fft.dominant_cycles:
        out["fft"] = "FFT found no dominant cycles — price is close to a random walk."
    else:
        top = fft.dominant_cycles[0]
        others = fft.dominant_cycles[1:]
        msg = f"Strongest detected cycle is ~{top.period_days:.0f} days ({top.label})."
        if others:
            extras = ", ".join(f"{c.period_days:.0f}d" for c in others)
            msg += f" Other notable periodicities at: {extras}."
        if fft.noise_ratio > 0.85:
            msg += " The spectrum is noisy — cycles exist but do not dominate the tape."
        elif fft.noise_ratio < 0.5:
            msg += " The dominant cycle stands out clearly above noise — worth watching."
        else:
            msg += " The dominant cycle is visible but competes with general noise."
        out["fft"] = msg

    if cyc.strength < 0.2:
        out["cycle"] = (
            "Cycle signal is weak — no clean rhythm to trade against. Do not use cycle "
            "position as a near-term timing input for this name."
        )
    else:
        period_str = f"~{cyc.dominant_period_days:.0f}-day"
        if cyc.phase_label == "near cycle trough":
            out["cycle"] = (
                f"Price sits near the trough of a {period_str} cycle. If the historical "
                "rhythm holds, the next move is upward — a mean-reversion long bias is "
                "consistent with the spectral picture."
            )
        elif cyc.phase_label == "rising through mean":
            out["cycle"] = (
                f"Price is in the rising phase of a {period_str} cycle. Momentum is "
                "building toward the peak; you are no longer early, but upside remains "
                "until the cycle tops out."
            )
        elif cyc.phase_label == "near cycle peak":
            out["cycle"] = (
                f"Price sits near the peak of a {period_str} cycle. If the rhythm holds, "
                "near-term returns are at risk of a pullback. Avoid chasing here."
            )
        else:  # falling
            out["cycle"] = (
                f"Price is in the falling phase of a {period_str} cycle. Continued "
                "near-term weakness is consistent with the phase; wait for the trough "
                "before re-engaging on cycle grounds."
            )

    return out


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #

def compute(close: pd.Series, lookback_days: int = 504) -> SpectralAnalysis:
    """Main entry. `close` is a price Series indexed by date.

    Uses up to `lookback_days` trailing observations for FFT / wavelets.
    Requires >=64 observations.
    """
    if len(close) < 64:
        raise ValueError("Need at least 64 observations for spectral analysis.")
    close_window = close.iloc[-min(len(close), lookback_days):]
    returns = _log_returns(close_window)
    wav = _wavelet_decomp(returns)
    fft = _fft_cycles(returns)
    cyc = _cycle_signal(close_window, fft)
    return SpectralAnalysis(
        wavelet=wav, fft=fft, cycle=cyc,
        explanations=_explain(wav, fft, cyc),
    )


def to_dict(s: SpectralAnalysis) -> dict[str, Any]:
    def clean(d):
        return {k: (None if isinstance(v, float) and (np.isnan(v) or np.isinf(v)) else v)
                for k, v in d.items()}
    return {
        "wavelet": {
            "available": s.wavelet.available,
            "dominant_band": s.wavelet.dominant_band,
            "error": s.wavelet.error,
            "bands": [clean(asdict(b)) for b in s.wavelet.bands],
        },
        "fft": {
            "noise_ratio": s.fft.noise_ratio,
            "dominant_cycles": [clean(asdict(c)) for c in s.fft.dominant_cycles],
        },
        "cycle": clean(asdict(s.cycle)),
        "explanations": s.explanations,
    }
