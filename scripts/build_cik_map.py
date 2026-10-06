r"""Build the ticker -> SEC company (CIK) map for every S&P 500 member since 2010.

    .venv\Scripts\python.exe scripts\build_cik_map.py

Writes data/universe/ticker_cik.csv (every row, with its evidence) and
data/universe/ticker_cik_review.md (the rows that need a human decision).
To decide a row, add it to data/universe/ticker_cik_overrides.csv
(ticker,start,cik,reason,reviewer) and run this again. See backend/cik_map.py
for how candidates are proposed and checked.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend import cik_map  # noqa: E402


def main() -> int:
    t0 = time.time()

    def progress(i: int, n: int, r: dict) -> None:
        if i % 25 == 0 or i == n:
            print(f"  {i}/{n}  ({time.time() - t0:.0f}s)  last: {r['ticker']} -> {r['status']}", flush=True)

    results = cik_map.build(progress=progress)
    counts = cik_map.write_outputs(results)
    print(f"\nDone in {time.time() - t0:.0f}s. " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print(f"Wrote {cik_map.OUT_CSV} and {cik_map.REVIEW_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
