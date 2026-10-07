"""Find verified predecessor company IDs and late ticker takeovers (backend/cik_links.py).

    python scripts/build_cik_links.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend import cik_links  # noqa: E402

links = cik_links.build(progress=lambda m: print("  " + m, flush=True))
cik_links.write(links)
print(f"{len(links)} rows checked; {sum(1 for l in links if l.predecessor)} predecessors linked; "
      f"{sum(1 for l in links if l.valid_from)} with a later start. Wrote {cik_links.OUT_CSV}")
