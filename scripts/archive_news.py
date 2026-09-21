r"""Capture today's headlines for the watchlist into the local news archive.

Why this exists: free news APIs only return recent items, which is exactly why
the sentiment component is excluded from every backtest — there is no history
to test against. Nothing can fix that retroactively. Running this daily from
today means that in a year there is a real, point-in-time archive with the
capture date recorded, and sentiment finally becomes testable.

    .venv\Scripts\python.exe scripts\archive_news.py
    .venv\Scripts\python.exe scripts\archive_news.py --tickers AAPL,MSFT

Run it once a day (Windows Task Scheduler, or the nightly GitHub Actions job
described in the Data Plan). Re-running within a day is harmless: headlines
are de-duplicated by a fingerprint of ticker + timestamp + headline.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging  # noqa: E402
import warnings  # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

from backend import db  # noqa: E402
from backend.analysis import sentiment as sent_mod  # noqa: E402


def fingerprint(ticker: str, ts: int, headline: str) -> str:
    raw = f"{ticker.upper()}|{ts}|{headline.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def capture(ticker: str) -> tuple[int, int]:
    """Returns (found, added)."""
    raw = sent_mod._fetch_raw_news(ticker)
    rows = []
    for item in raw or []:
        norm = sent_mod._normalize(item)
        if not norm or not norm.get("title"):
            continue
        ts = int(norm.get("ts") or 0)
        head = norm["title"].strip()
        rows.append({
            "ticker": ticker.upper(),
            "published_ts": ts,
            "headline": head,
            "publisher": norm.get("publisher") or "",
            "url": norm.get("link") or "",
            "fingerprint": fingerprint(ticker, ts, head),
            # store the score as it was computed today, alongside the text
            "sentiment": sent_mod._score_one(
                f"{head}. {norm.get('summary', '')}".strip()),
        })
    return len(rows), db.news_archive_add(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", default=None,
                    help="comma-separated list (default: the watchlist)")
    args = ap.parse_args()

    db.init()
    tickers = ([t.strip().upper() for t in args.tickers.split(",") if t.strip()]
               if args.tickers else db.list_tickers())
    if not tickers:
        tickers = db.DEFAULT_WATCHLIST

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Archiving headlines for {len(tickers)} tickers at {stamp}\n")
    total_found = total_added = 0
    for t in tickers:
        try:
            found, added = capture(t)
        except Exception as exc:
            print(f"  {t:<6} failed: {type(exc).__name__}: {exc}")
            continue
        total_found += found
        total_added += added
        print(f"  {t:<6} {found:>3} headlines, {added:>3} new")

    stats = db.news_archive_stats()
    print(f"\nThis run: {total_found} seen, {total_added} new.")
    print(f"Archive now holds {stats['headlines']} headlines across {stats['tickers']} tickers.")
    if stats["earliest_ts"]:
        first = datetime.fromtimestamp(stats["earliest_ts"], timezone.utc).date()
        last = datetime.fromtimestamp(stats["latest_ts"], timezone.utc).date()
        span = (last - first).days
        print(f"Coverage {first} -> {last} ({span} days). "
              f"Sentiment becomes backtestable once this spans a year or more.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
