"""Smoke test for backend/analysis/sentiment.py.

Run:
    python scripts/test_sentiment.py          # defaults to AAPL
    python scripts/test_sentiment.py NVDA

Note: this test hits live yfinance news. If yfinance returns zero headlines
(which does happen — the news endpoint is flaky), the structural checks
will confirm that and the script will exit 0 with a "no news" message
rather than failing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis import data as data_mod              # noqa: E402
from backend.analysis import sentiment as sentiment_mod    # noqa: E402


def _check(cond: bool, msg: str) -> None:
    marker = "OK " if cond else "FAIL"
    print(f"  [{marker}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run(ticker: str = "AAPL") -> int:
    print(f"\n=== News sentiment smoke test: {ticker} ===\n")
    td = data_mod.load(ticker)
    close = td.history["Close"] if td else None

    result = sentiment_mod.compute(ticker.upper(), close)
    payload = sentiment_mod.to_dict(result)

    print(f"Method: {payload['method']}")
    if payload["error"]:
        print(f"Error : {payload['error']}")
        return 1

    print("\nStructural checks:")
    _check(payload["method"] == "vader", "VADER is active")
    _check(payload["overall_label"] in ("bullish", "bearish", "neutral"),
           f"overall_label valid (got {payload['overall_label']!r})")
    _check(-100.0 <= payload["overall_score"] <= 100.0,
           f"overall_score in [-100, 100] (got {payload['overall_score']:.2f})")
    _check(payload["alignment_with_price"] in ("aligned", "conflicted", "neutral", "n/a"),
           f"alignment value valid (got {payload['alignment_with_price']!r})")
    _check(len(payload["headlines"]) == payload["headline_count"],
           "headline_count matches list length")

    if payload["headline_count"] == 0:
        print("\nyfinance returned zero headlines for this ticker right now.")
        print("That's a real-world case the module handles — structure is still correct.")
        print("\nPlain-English explanations:")
        for k, v in payload["explanations"].items():
            print(f"\n  [{k}]")
            print(f"    {v}")
        print("\n=== Structural checks passed (no headlines returned) ===")
        return 0

    # per-headline sanity
    for h in payload["headlines"][:5]:
        _check(-1.0 <= h["compound"] <= 1.0,
               f"compound in [-1,1] (got {h['compound']:.3f})")
        _check(h["label"] in ("positive", "negative", "neutral"),
               f"label valid (got {h['label']!r})")
        _check(h["age_hours"] >= 0, f"age_hours >= 0 (got {h['age_hours']})")

    # trend sanity
    for t in payload["trend"]:
        _check(-1.0 <= t["avg_sentiment"] <= 1.0,
               f"trend avg_sentiment in [-1,1] (got {t['avg_sentiment']:.3f})")
        _check(t["headline_count"] >= 1,
               f"trend count >= 1 (got {t['headline_count']})")

    # --- human-readable summary ---
    print("\nOverall:")
    print(f"  score : {payload['overall_score']:+.1f}   label: {payload['overall_label']}")
    print(f"  headline count     : {payload['headline_count']}")
    print(f"  20-day price return: {payload['price_return_20d']:+.2%}")
    print(f"  alignment          : {payload['alignment_with_price']}")

    print("\nRecent headlines (top 10 by freshness):")
    sorted_hl = sorted(payload["headlines"], key=lambda h: h["age_hours"])[:10]
    for h in sorted_hl:
        title = (h["title"][:70] + "...") if len(h["title"]) > 70 else h["title"]
        print(f"  [{h['label']:<8} {h['compound']:+.2f}]  "
              f"({h['age_hours']:>5.1f}h)  {title}")

    print("\n30-day daily trend:")
    if payload["trend"]:
        for t in payload["trend"][-14:]:   # last 2 weeks
            bar = "+" * max(0, int(round(t["avg_sentiment"] * 10))) \
                  or "-" * max(0, int(round(-t["avg_sentiment"] * 10))) \
                  or "."
            print(f"  {t['date']}  n={t['headline_count']:>2}  "
                  f"avg={t['avg_sentiment']:+.2f}  {bar}")
    else:
        print("  (no trend — all headlines outside 30d window)")

    print("\nPlain-English explanations:")
    for k, v in payload["explanations"].items():
        print(f"\n  [{k}]")
        print(f"    {v}")

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    sys.exit(run(ticker))
