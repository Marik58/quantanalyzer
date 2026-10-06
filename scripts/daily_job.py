r"""The daily job: everything that has to happen once a day, after the market closes.

    1. Archive today's headlines for the watchlist and the tracking list
       (they can't be fetched later).
    2. Once a week, record the Trend twin's calls on the fixed tracking list.
    3. Snapshot daily prices for every stock an open call depends on.
    4. Grade every call whose horizon has passed.

Run it by hand:

    .venv\Scripts\python.exe scripts\daily_job.py
    .venv\Scripts\python.exe scripts\daily_job.py --skip-news --skip-twin

Schedule it on Windows (once; it then runs every weekday at 6:30 pm):

    1. Press the Windows key, type "Task Scheduler", open it.
    2. Action menu > Create Basic Task. Name: QuantAnalyzer daily job.
    3. Trigger: Weekly. Tick Monday through Friday. Start time: 6:30 PM.
    4. Action: Start a program. Program/script: browse to
       scripts\run_daily_job.bat in this repository.
    5. Finish. Output is appended to data\logs\daily_job.log.

If the computer is off at 6:30 pm, nothing is lost: the weekly twin run
happens on the first run of the week, and grading catches up on the next run.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging  # noqa: E402
import warnings  # noqa: E402

warnings.filterwarnings("ignore")
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

from backend import db, ledger, twins  # noqa: E402


def _step(name: str, fn) -> None:
    print(f"\n== {name}")
    try:
        fn()
    except Exception as exc:  # one failing step must not stop the others
        print(f"   FAILED: {type(exc).__name__}: {exc}")


def run_news() -> None:
    import archive_news
    # The watchlist plus the twins' tracking list: future news and hype agents
    # will need history on the stocks that have calls, and it can't be backfilled.
    tickers = sorted(set(db.list_tickers() or db.DEFAULT_WATCHLIST)
                     | set(twins.tracking_list()["tickers"]))
    found = added = 0
    for t in tickers:
        try:
            f, a = archive_news.capture(t)
        except Exception as exc:
            print(f"   {t:<6} failed: {type(exc).__name__}")
            continue
        found, added = found + f, added + a
    stats = db.news_archive_stats()
    print(f"   {found} headlines seen, {added} new; archive holds {stats['headlines']}.")


def run_twin() -> None:
    spec = twins.tracking_list()
    s = twins.record_trend_twin(spec["tickers"])
    if "error" in s:
        print(f"   {s['error']}")
        return
    print(f"   recorded {s['recorded']} calls, {s['already_done']} already done this week, "
          f"{len(s['skipped'])} skipped")
    for skip in s["skipped"]:
        print(f"     skipped {skip['ticker']}: {skip['reason']}")


def run_snapshots() -> None:
    s = ledger.snapshot_prices()
    print(f"   {s['tickers']} tickers, {s['rows_added']} new daily rows")
    if s["missing"]:
        print(f"   no prices returned for: {', '.join(s['missing'])} "
              f"(possibly delisted; their stored snapshots are kept)")


def run_grading() -> None:
    s = ledger.grade_due()
    if "error" in s:
        print(f"   {s['error']}")
    print(f"   open {s['open']}: graded {s['graded']}, from snapshots {s['graded_snapshot']}, "
          f"needs review {s['needs_review']}, not due yet {s['not_due']}")


def report() -> None:
    rows = ledger.agents_summary()
    if not rows:
        print("   the ledger is empty")
    for r in rows:
        print(f"   {r['agent_id']:<14} {r['charter_version']:<28} calls {r['calls']:>4}  "
              f"graded {r['graded']:>4}  pending {r['pending']:>4}  review {r['needs_review']:>3}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-news", action="store_true")
    ap.add_argument("--skip-twin", action="store_true")
    args = ap.parse_args()

    db.init()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"QuantAnalyzer daily job, {stamp} (market date {ledger._today()})")
    if not args.skip_news:
        _step("Archive headlines", run_news)
    if not args.skip_twin:
        _step("Trend twin: weekly calls on the tracking list", run_twin)
    _step("Snapshot prices", run_snapshots)
    _step("Grade calls whose time is up", run_grading)
    _step("Ledger", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
