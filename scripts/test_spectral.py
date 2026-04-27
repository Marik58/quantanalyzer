"""Smoke test for backend/analysis/spectral.py.

Run:

    python scripts/test_spectral.py          # defaults to AAPL
    python scripts/test_spectral.py NVDA

Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod           # noqa: E402
from backend.analysis import spectral as spectral_mod   # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== Spectral analysis smoke test: {ticker} ===\n")
    td = data_mod.load(ticker)
    if td is None:
        print(f"No data for {ticker} — is the network up?")
        return 1

    result = spectral_mod.compute(td.history["Close"])
    payload = spectral_mod.to_dict(result)

    print("Structural checks:")
    _check("wavelet" in payload, "wavelet block present")
    _check("fft" in payload, "fft block present")
    _check("cycle" in payload, "cycle block present")
    _check("explanations" in payload, "explanations block present")

    if payload["wavelet"]["available"]:
        shares = [b["energy_share"] for b in payload["wavelet"]["bands"]]
        total = sum(shares)
        _check(abs(total - 1.0) < 1e-6, f"wavelet band shares sum to 1 (got {total:.6f})")
        _check(all(0 <= s <= 1 for s in shares),
               "all wavelet band shares are in [0, 1]")
        _check(payload["wavelet"]["dominant_band"] in ("short", "medium", "long"),
               "dominant band is one of short/medium/long")

    _check(0 <= payload["fft"]["noise_ratio"] <= 1,
           "FFT noise_ratio is in [0, 1]")
    for c in payload["fft"]["dominant_cycles"]:
        _check(c["period_days"] > 0, f"cycle period > 0 (got {c['period_days']})")
        _check(0 <= c["power"] <= 1, f"cycle power in [0,1] (got {c['power']})")

    cyc = payload["cycle"]
    _check(-3.2 <= cyc["phase_radians"] <= 3.2, "cycle phase in [-pi, pi]")
    _check(0 <= cyc["strength"] <= 1, "cycle strength in [0, 1]")
    _check(-1 <= cyc["score"] <= 1, "cycle score in [-1, 1]")

    # --- human-readable summary ---
    print("\nWavelet decomposition:")
    if payload["wavelet"]["available"]:
        for b in payload["wavelet"]["bands"]:
            print(f"  {b['name']:<7} ({b['period_range']:<10} | {b['levels']:<6}): "
                  f"{b['energy_share']:.1%}")
        print(f"  dominant band -> {payload['wavelet']['dominant_band']}")
    else:
        print("  (pywt not installed)")

    print("\nFFT dominant cycles:")
    for i, c in enumerate(payload["fft"]["dominant_cycles"], 1):
        print(f"  #{i}: period = {c['period_days']:6.1f} days  "
              f"power = {c['power']:.2f}  ({c['label']})")
    print(f"  noise ratio: {payload['fft']['noise_ratio']:.2f}  "
          "(higher = more random-walk-like)")

    print("\nCycle signal:")
    print(f"  dominant period : {cyc['dominant_period_days']:.1f} days")
    print(f"  phase (rad)     : {cyc['phase_radians']:+.3f}")
    print(f"  phase label     : {cyc['phase_label']}")
    print(f"  near-term dir   : {cyc['direction']}")
    print(f"  strength        : {cyc['strength']:.2f}")
    print(f"  score           : {cyc['score']:+.2f}   (-1 bearish, +1 bullish)")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\nFull JSON payload (truncated):")
    print(json.dumps(payload, indent=2, default=str)[:1500] + "\n...\n")

    print("=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
