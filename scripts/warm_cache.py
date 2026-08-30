r"""Pre-warm the data cache before a live demo.

Fetches price history + info for every watchlist ticker (plus SPY) so the
demo never waits on — or gets rate-limited by — Yahoo mid-presentation.
Optionally precomputes a Quant Score per name (slow: ~10-30s per ticker).

Run 10-15 minutes before the demo (the cache TTL is CACHE_TTL_SECONDS,
default 900s). For a demo day, consider setting CACHE_TTL_SECONDS=86400 in
.env first so one warm run covers the whole meeting.

    .venv\Scripts\python.exe scripts\warm_cache.py           # data only (~1 min)
    .venv\Scripts\python.exe scripts\warm_cache.py --full    # + quant scores (slow)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend import db  # noqa: E402
from backend.analysis import data as data_mod  # noqa: E402


def main() -> int:
    full = "--full" in sys.argv
    try:
        tickers = db.list_tickers()
    except Exception:
        tickers = []
    if not tickers:
        tickers = db.DEFAULT_WATCHLIST
    names = tickers + ["SPY"]

    print(f"Warming data cache for {len(names)} tickers"
          f"{' + quant scores' if full else ''}...\n")
    t0 = time.time()
    failures: list[str] = []
    for t in names:
        start = time.time()
        td = data_mod.load(t)                    # 2y — used by analyze/chart
        td10 = data_mod.load(t, period="10y")    # 10y — used by what-if
        ok = td is not None and td10 is not None
        line = f"  {t:<6} data {'OK' if ok else 'FAILED'} ({time.time()-start:.1f}s)"
        if ok and full and t != "SPY":
            qs_start = time.time()
            try:
                from backend.analysis import quant_score as qs_mod
                r = qs_mod.compute(t)
                line += f" · quant_score={r.score:+.0f} ({time.time()-qs_start:.0f}s)"
            except Exception as exc:
                line += f" · quant_score FAILED ({type(exc).__name__})"
        if not ok:
            failures.append(t)
        print(line)

    print(f"\nDone in {time.time()-t0:.0f}s. "
          f"{len(names)-len(failures)}/{len(names)} tickers cached.")
    if failures:
        print(f"FAILED: {', '.join(failures)} — retry or check network before the demo.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
