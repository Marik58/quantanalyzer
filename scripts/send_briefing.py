r"""Build the morning briefing and email it (scheduled for weekdays at 9:45 am).

    .venv\Scripts\python.exe scripts\send_briefing.py             # build, save, send
    .venv\Scripts\python.exe scripts\send_briefing.py --dry-run   # build and save only

Every briefing is saved to data\briefings\<date>.html, whether or not it is sent.
Sending needs BRIEFING_SMTP_USER, BRIEFING_SMTP_PASSWORD (a Google app password) and
BRIEFING_TO in .env; see backend/emailer.py. Without them the briefing is saved and the
log says why it wasn't sent.

Scheduled as the Windows task "QuantAnalyzer Morning Briefing" (weekdays 9:45 am, runs
late if the computer was asleep, allowed on battery), windowless:

    Program:   <repo>\.venv\Scripts\pythonw.exe
    Arguments: scripts\send_briefing.py --log data\logs\briefing.log
    Start in:  <repo>
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build and save, don't send")
    ap.add_argument("--log", help="append output to this file (for the windowless scheduled run)")
    args = ap.parse_args(argv)
    if args.log:
        log = open(ROOT / args.log, "a", encoding="utf-8")
        sys.stdout = sys.stderr = log
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"\n=== briefing {datetime.now():%Y-%m-%d %H:%M} ===", flush=True)
    try:
        from backend import briefing, emailer
        b = briefing.gather(progress=lambda m: print("  " + m, flush=True))
        path = briefing.save(b)
        print(f"  saved {path.relative_to(ROOT)}", flush=True)
        if args.dry_run:
            print("  dry run: not sent", flush=True)
            return 0
        try:
            to = emailer.send(briefing.subject(b), briefing.to_html(b), briefing.to_text(b))
            print(f"  sent to {len(to)} recipient(s)", flush=True)
        except emailer.NotConfigured as exc:
            print(f"  NOT SENT: {exc}", flush=True)
            return 2
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
