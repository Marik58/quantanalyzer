"""Smoke test for backend/game.py — the replay/calibration game.

The leakage assertions are the important part: a payload that names the
ticker, shows real dates, or ships unrebased prices would let players
recognize the stock and invalidate every scored round.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend import db, game  # noqa: E402


def run() -> int:
    db.init()
    game.reset()

    r = game.new_round(seed=7)
    print(f"round {r['round_id']}: {len(r['prices'])} bars, "
          f"indicators: {r['indicators']}")

    # --- leakage checks ---
    blob = json.dumps({k: v for k, v in r.items() if k != "round_id"})
    for tick in db.DEFAULT_WATCHLIST:
        assert f'"{tick}"' not in blob.upper(), f"LEAK: ticker {tick} in payload"
    assert r["prices"][0] == 100.0, "chart must be rebased to 100"
    assert all(isinstance(b, int) for b in r["bars_ago"]), "x-axis must be bar indices, not dates"
    assert "date" not in blob.lower(), "no date fields allowed in the masked payload"
    print("leakage checks passed")

    # --- scoring ---
    g = game.submit_guess(r["round_id"], "long", 80)
    assert g["reveal"]["ticker"], "reveal must name the ticker"
    assert g["pnl_pct"] is not None and g["correct"] in (0, 1)
    print(f"scored: pnl={g['pnl_pct']}%, correct={g['correct']}, "
          f"was {g['reveal']['ticker']} @ {g['reveal']['cutoff_date']}")

    try:
        game.submit_guess(r["round_id"], "long", 80)
        print("FAIL: double answer accepted")
        return 1
    except game.GameError:
        print("double-answer rejected")

    # pass is unscored
    r2 = game.new_round(seed=8)
    g2 = game.submit_guess(r2["round_id"], "pass", 50)
    assert g2["pnl_pct"] is None and g2["correct"] is None

    s = game.get_stats()
    assert s["rounds"] == 2 and s["passes"] == 1 and s["decisions"] == 1
    assert s["brier"] is not None and 0.0 <= s["brier"] <= 1.0
    print(f"stats: hit={s['hit_rate_pct']}%, brier={s['brier']}, "
          f"baseline={s['buyhold_mean_pnl_pct']}%")

    # bad inputs
    for args in [(999999, "long", 75), (r2["round_id"], "hold", 75),
                 (r2["round_id"], "long", 30)]:
        try:
            game.submit_guess(*args)
            print(f"FAIL: {args} accepted")
            return 1
        except game.GameError:
            pass
    print("input validation OK")

    game.reset()
    assert game.get_stats()["rounds"] == 0
    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
