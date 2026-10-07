"""Company-ID links the ticker map can't express (Roadmap Phase 3, data fix 2026-10-07).

The ticker map (backend/cik_map.py) gives each S&P 500 membership one SEC company ID.
Two things break that, and both are fixed here, only with checkable evidence:

1. **A company ID that took over a ticker partway through.** The ticker IR belonged to
   Ingersoll-Rand plc (today's Trane) until 2020; today's IR company ID was Gardner Denver
   until 2020-02-26. Using today's ID for 2018-2020 would give the backtest the wrong
   company. Rule: for an ID that began filing long after the membership began, a month
   counts only if the name that ID used at the time matches the company's name
   (Cigna Corp -> Cigna Group passes; Gardner Denver -> Ingersoll Rand doesn't).

2. **A holding-company reorganization** (Google -> Alphabet 2015, Disney 2019, Medtronic
   2015, BlackRock 2024, Exxon 2026). The history before the change lives under the old ID.
   Rule: an old ID is linked only when the new company's FIRST annual report shows the old
   company's revenue as its own history, matching to within 0.5% for at least one year.
   That is an accounting fact, not a name guess: Fox Corp (2019) shares a name with 21st
   Century Fox but reports different revenue, so it is not linked.

Output: data/universe/cik_links.csv (read by pit_data) and cik_links_review.md.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from backend import cik_map, edgar

ROOT = Path(__file__).resolve().parent.parent
MAP_CSV = ROOT / "data" / "universe" / "ticker_cik.csv"
OUT_CSV = ROOT / "data" / "universe" / "cik_links.csv"
OUT_MD = ROOT / "data" / "universe" / "cik_links_review.md"
LATE_DAYS = 480          # an ID whose first annual report came this long after the membership began
MATCH_TOL = 0.005        # revenue must agree to within 0.5%
MIN_YEARS = 2            # ...in at least two years: one year can match by coincidence
                         # (Gardner Denver's 2017 revenue was within 0.5% of an Allegion figure)
NAME_OK = 0.6


@dataclass
class Link:
    ticker: str
    start: str
    cik: int
    valid_from: str = ""            # months before this use another ID (or none)
    predecessor: int | None = None
    switch: str = ""                # before this date, the predecessor's filings are used
    evidence: str = ""


def first_report(facts: dict[str, Any]) -> tuple[str, str] | None:
    """(accession, filed date) of a company's earliest annual report with revenue."""
    rows = [r for c in edgar.METRICS["revenue"][3] + edgar.FALLBACKS.get("revenue", [])
            for r in facts.get("facts", {}).get("us-gaap", {}).get(c, {}).get("units", {}).get("USD", [])
            if r.get("form") in edgar._ANNUAL_FORMS]
    if not rows:
        return None
    first = min(rows, key=lambda r: r["filed"])
    return first.get("accn", ""), first["filed"]


def revenue_rows(facts: dict[str, Any], accn: str | None = None) -> dict[str, float]:
    """Year-long revenue values by period end; only one filing's if `accn` is given."""
    out: dict[str, float] = {}
    for c in edgar.METRICS["revenue"][3] + edgar.FALLBACKS.get("revenue", []):
        for r in facts.get("facts", {}).get("us-gaap", {}).get(c, {}).get("units", {}).get("USD", []):
            if r.get("form") not in edgar._ANNUAL_FORMS or not r.get("start"):
                continue
            if not 350 <= edgar._days(r["start"], r["end"]) <= 380:
                continue
            if accn is None or r.get("accn") == accn:
                out.setdefault(r["end"], float(r["val"]))
    return out


def continuity(successor: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Years where the successor's first annual report shows the candidate's revenue as
    its own comparative history. Empty means no accounting link."""
    fr = first_report(successor)
    if fr is None:
        return []
    own = revenue_rows(successor, accn=fr[0])
    theirs: dict[str, list[float]] = {}
    for c in edgar.METRICS["revenue"][3] + edgar.FALLBACKS.get("revenue", []):
        for r in candidate.get("facts", {}).get("us-gaap", {}).get(c, {}).get("units", {}).get("USD", []):
            if (r.get("form") in edgar._ANNUAL_FORMS and r.get("start")
                    and 350 <= edgar._days(r["start"], r["end"]) <= 380):
                theirs.setdefault(r["end"], []).append(float(r["val"]))
    matches = []
    for end, v in sorted(own.items()):
        for end2, vals in theirs.items():
            if abs((date.fromisoformat(end) - date.fromisoformat(end2)).days) <= 10 and v > 0 and \
                    any(abs(x - v) / v <= MATCH_TOL for x in vals):
                matches.append(f"{end[:4]} revenue {v / 1e9:,.2f}B")
                break
    return matches if len(matches) >= MIN_YEARS else []


def name_valid_from(sub: dict[str, Any], known_name: str, today: str) -> str:
    """The date from which every name the ID has used matches `known_name` ('' = always)."""
    periods = sorted(((f.get("from", "")[:10], f.get("to", "")[:10], f.get("name", ""))
                      for f in sub.get("formerNames", [])), key=lambda p: p[1])
    bad_until = ""
    for _frm, to, name in periods:
        if cik_map.name_similarity(known_name, name) < NAME_OK and cik_map.name_similarity(name, known_name) < NAME_OK:
            bad_until = max(bad_until, to)
    return bad_until


def build(progress: Callable[[str], None] | None = None,
          facts_for: Callable[[int], dict[str, Any]] = edgar.compact_facts) -> list[Link]:
    say = progress or (lambda _m: None)
    today = date.today().isoformat()
    rows = list(csv.DictReader(open(MAP_CSV, encoding="utf-8")))
    links: list[Link] = []
    for r in rows:
        current = not r["end"]
        late = (r["status"] == "verified" and r["first_10k"] and
                (date.fromisoformat(r["first_10k"]) - date.fromisoformat(max(r["start"], "2010-01-01"))).days > LATE_DAYS)
        split = r["status"] == "split" and current
        if not (late or split):
            continue
        known = r.get("known_name") or ""
        if split:      # the map left the ID blank; today's ID is the SEC ticker list's
            hit = edgar.ticker_map().get(r["ticker"].replace(".", "-")) or edgar.ticker_map().get(r["ticker"])
            if not hit:
                continue
            cik = int(hit["cik"])
        else:
            cik = int(r["cik"])
        link = Link(r["ticker"], r["start"], cik)
        sub = edgar.submissions(cik)
        if known:
            link.valid_from = name_valid_from(sub, known, today)
        succ = facts_for(cik)
        fr = first_report(succ)
        if fr is None:
            links.append(link)
            continue
        window_start = max(r["start"], "2010-01-01")
        cands = set()
        for name in filter(None, [known, sub.get("name", "")]):
            for h in edgar.full_text_search(name, "10-K", window_start, fr[1])[:40]:
                cands.add(h["cik"])
        cands.discard(cik)
        best = None
        for c in sorted(cands):
            try:
                ev = continuity(succ, facts_for(c))
            except edgar.EdgarError:
                continue
            if ev and (best is None or len(ev) > len(best[1])):
                best = (c, ev)
        if best:
            link.predecessor, link.switch = best[0], fr[1]
            link.evidence = (f"{edgar.submissions(best[0]).get('name', '')} ({best[0]}): the new company's first "
                             f"annual report (filed {fr[1]}) shows its numbers as its own history: " + "; ".join(best[1]))
        say(f"{r['ticker']}: predecessor {link.predecessor or 'none'}; valid from {link.valid_from or 'always'}")
        links.append(link)
    return links


def write(links: list[Link]) -> None:
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "start", "cik", "valid_from", "predecessor", "switch", "evidence"])
        for l in links:
            w.writerow([l.ticker, l.start, l.cik, l.valid_from, l.predecessor or "", l.switch, l.evidence])
    lines = ["# Company-ID links (predecessors and late takeovers)", "",
             "Generated by `scripts/build_cik_links.py` from SEC records. See `backend/cik_links.py` for the rules.", "",
             "| Ticker | Today's ID | Counts from | Predecessor | Switch | Evidence |", "|---|---|---|---|---|---|"]
    lines += [f"| {l.ticker} | {l.cik} | {l.valid_from or 'always'} | {l.predecessor or '—'} | {l.switch or '—'} | "
              f"{l.evidence or 'no accounting link found'} |" for l in links]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load(path: Path = OUT_CSV) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[(r["ticker"], r["start"])] = {"cik": int(r["cik"]), "valid_from": r["valid_from"],
                                          "predecessor": int(r["predecessor"]) if r["predecessor"] else None,
                                          "switch": r["switch"]}
    return out
