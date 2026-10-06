"""Which company was behind each S&P 500 ticker, and when: a source-checking agent.

A ticker is not an identity. Tickers get reused (ADT in 2012-2016 was a
different company from today's ADT), renamed (FB became META), and one row of
the membership data can span two companies (AGN: Allergan Inc., then Allergan
plc after Actavis bought it and took the ticker). A fundamentals backtest
needs the SEC's company ID (CIK) for every member over time, including
companies that no longer exist; otherwise it silently drops the failures and
buyouts, which is survivorship bias again.

How it decides (the pattern every data agent in this project should follow):
- Several sources PROPOSE candidates, each with a trust tier:
    A  SEC: the current ticker list, and full-text search of 10-K filings (by
       company name and by ticker). Search hits only suggest; they're noisy.
    B  Wikipedia: the current S&P 500 table (which lists CIKs) and the
       historical changes table (removed ticker -> company name), whose rows
       cite S&P press releases. Plus membership continuity: a company whose
       ticker changed (FB -> META) shows up as one row ending the day the next
       begins.
- One official source DECIDES: the SEC's own record of each candidate. The
  company must have filed annual reports (10-Ks) during the years the ticker
  was in the index, and when a name is known, its SEC name or a former name
  must match it.
- Every decision keeps its evidence: which sources proposed it, how much of the
  window its 10-Ks cover, how well the name matches, and an SEC link.
- Anything ambiguous goes to a review list instead of being guessed. Marik's
  decisions go in data/universe/ticker_cik_overrides.csv, with a reason, and
  always win.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from backend import edgar

ROOT = Path(__file__).resolve().parent.parent
MEMBERSHIP_CSV = ROOT / "data" / "universe" / "sp500_membership.csv"
OUT_CSV = ROOT / "data" / "universe" / "ticker_cik.csv"
REVIEW_MD = ROOT / "data" / "universe" / "ticker_cik_review.md"
OVERRIDES_CSV = ROOT / "data" / "universe" / "ticker_cik_overrides.csv"
WIKI_CURRENT = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_HISTORY = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
WIKI_UA = "QuantAnalyzer research (educational project; contact in repo README)"

MIN_COVERAGE = 0.5      # a candidate's 10-Ks must cover at least half the window's years
MIN_NAME_MATCH = 0.6    # when a name is known, the SEC name or a former name must match this well
FILING_LAG_DAYS = 456   # a fiscal year's 10-K can be filed up to ~15 months after it starts

_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "companies", "plc",
             "ltd", "limited", "holdings", "holding", "group", "the", "de", "nv", "sa", "lp",
             "llc", "trust", "international", "intl", "class", "a", "b", "new"}


# --- Small helpers -----------------------------------------------------------

def normalize_name(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()   # Estée -> Estee
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)              # "(ELV)", "(CIK 000...)"
    s = re.sub(r"[/\\][a-z]{2}[/\\]", " ", s)    # "/DE/" or "\DE\" state markers
    s = re.sub(r"['\u2019`]", "", s)             # Casey's -> caseys
    s = re.sub(r"\b([a-z])\.(?=[a-z]\.)", r"\1", s).replace(".", " ")   # U.S. -> us
    tokens = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _SUFFIXES]
    return re.sub(r"\b([a-z0-9]) (?=[a-z0-9]\b)", r"\1", " ".join(tokens))   # "V F CORP" -> vf


# Industry words shared by unrelated companies ("Ra Pharmaceuticals" is not
# "Alexion Pharmaceuticals"), so they never count toward a name match.
_GENERIC = {"pharmaceuticals", "pharmaceutical", "pharma", "financial", "bancorp", "bancshares",
            "bank", "energy", "technologies", "technology", "systems", "industries", "resources",
            "services", "health", "healthcare", "communications", "entertainment", "global",
            "capital", "partners", "brands", "properties", "realty", "semiconductor",
            "semiconductors", "motors", "airlines", "foods", "products", "laboratories", "labs",
            "therapeutics", "biosciences", "sciences", "solutions", "networks", "software", "media",
            "insurance", "and", "of", "us", "america", "american", "national", "united", "first"}


def name_similarity(known: str, candidate: str) -> float:
    """0..1: the share of the known name's distinctive words found in the candidate's name."""
    k = set(normalize_name(known).split())
    c = set(normalize_name(candidate).split())
    if not k or not c:
        return 0.0
    distinct = (k - _GENERIC) or k
    score = len(distinct & c) / len(distinct)
    joined_k = "".join(sorted(distinct, key=normalize_name(known).split().index))
    if score < 1.0 and len(joined_k) >= 5 and joined_k in "".join(normalize_name(candidate).split()):
        score = 1.0
    return score


def token_jaccard(a: str, b: str) -> float:
    """How closely two full names match, word for word (used only to break ties)."""
    ta, tb = set(normalize_name(a).split()), set(normalize_name(b).split())
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def sec_ticker(t: str) -> str:
    return t.upper().replace(".", "-")


@dataclass
class Row:
    ticker: str
    start: str
    end: str | None          # None = still a member


@dataclass
class Candidate:
    cik: int
    sources: set[str] = field(default_factory=set)
    sec_name: str = ""
    former_names: list[str] = field(default_factory=list)
    tenk_in_window: int = 0
    expected: int = 1
    coverage: float = 0.0
    name_match: float | None = None
    first_10k: str | None = None
    last_10k: str | None = None
    window_names: list[str] = field(default_factory=list)


# --- Sources -------------------------------------------------------------------

def _fetch_html(url: str, cache_name: str, max_age_days: float = 7) -> str:
    path = edgar.CACHE_DIR / "wiki" / cache_name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return path.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def wikipedia_current() -> dict[str, dict[str, Any]]:
    """Current members: ticker -> {name, cik} (source tier B)."""
    t = pd.read_html(io.StringIO(_fetch_html(WIKI_CURRENT, "current.html")))[0]
    return {str(r["Symbol"]).upper(): {"name": str(r["Security"]), "cik": int(r["CIK"])}
            for _, r in t.iterrows() if pd.notna(r.get("CIK"))}


def wikipedia_removed() -> dict[str, list[dict[str, str]]]:
    """Removed ticker -> [{name, date}] from the historical changes table (tier B)."""
    t = pd.read_html(io.StringIO(_fetch_html(WIKI_HISTORY, "history.html")))[0]
    t.columns = ["date", "add_ticker", "add_name", "rem_ticker", "rem_name", "reason", "refs"][:len(t.columns)]
    out: dict[str, list[dict[str, str]]] = {}
    for r in t.itertuples():
        if isinstance(r.rem_ticker, str) and isinstance(r.rem_name, str):
            d = pd.to_datetime(r.date, errors="coerce")
            out.setdefault(r.rem_ticker.strip().upper(), []).append(
                {"name": r.rem_name.strip(), "date": d.date().isoformat() if pd.notna(d) else ""})
    return out


def load_membership(since: str = "2010-01-01") -> list[Row]:
    m = pd.read_csv(MEMBERSHIP_CSV, dtype=str)
    rows = []
    for _, r in m.iterrows():
        end = r["end_date"] if isinstance(r["end_date"], str) and r["end_date"] else None
        if end is None or end >= since:
            rows.append(Row(r["ticker"].upper(), r["start_date"], end))
    return rows


# --- Verification against the SEC's own record (tier A, decides) --------------

def verify(cand: Candidate, row: Row, known_name: str | None, today: str,
           since: str = "2010-01-01") -> Candidate:
    sub = edgar.submissions(cand.cik)
    cand.sec_name = sub.get("name", "")
    cand.former_names = [f.get("name", "") for f in sub.get("formerNames", [])]
    # Only the part of the membership the backtest can use (machine-readable
    # filings begin around 2010) is checked. Reports filed in the year before a
    # company joined count too: a 2026 addition can't have filed one since.
    start = max(row.start, since)
    count_from = (date.fromisoformat(start) - timedelta(days=400)).isoformat()
    end = row.end or today
    window_end = (date.fromisoformat(end) + timedelta(days=FILING_LAG_DAYS)).isoformat()
    dates = edgar.annual_report_dates(cand.cik, since=start)
    in_window = [d for d in dates if count_from <= d <= min(window_end, today)]
    years = (date.fromisoformat(min(end, today)) - date.fromisoformat(start)).days / 365.25
    cand.tenk_in_window = len(in_window)
    cand.expected = max(1, int(years))
    cand.coverage = min(1.0, len(in_window) / cand.expected)
    cand.first_10k = in_window[0] if in_window else None
    cand.last_10k = in_window[-1] if in_window else None
    cand.window_names = names_during(sub, start, min(end, today))
    if known_name:
        cand.name_match = max([name_similarity(known_name, n) for n in cand.window_names] or [0.0])
    return cand


def names_during(sub: dict[str, Any], start: str, end: str) -> list[str]:
    """The names a company actually used between start and end. (Johnson Controls'
    CIK was once "ADT LIMITED", but only in 1995-1997.)"""
    former = sub.get("formerNames", [])
    names = [f["name"] for f in former
             if str(f.get("from", ""))[:10] <= end and str(f.get("to", "9999"))[:10] >= start]
    last_change = max((str(f.get("to", ""))[:10] for f in former), default="")
    if not former or last_change <= end:
        names.append(sub.get("name", ""))
    return [n for n in names if n]


# Sources that tie a ticker to one specific company. For a ticker still in use,
# today's SEC ticker list and Wikipedia's CIK column do. For a ticker that's gone,
# today's ticker list does NOT: tickers get reused (BBT now belongs to another bank),
# so only a documented ticker change counts.
_CURRENT_ANCHORS = {"sec_tickers", "wikipedia_current"}
_FORMER_ANCHORS = {"membership_continuity"}


def _passes(c: Candidate, two_anchors_agree: bool = False) -> bool:
    name_ok = c.name_match is None or c.name_match >= MIN_NAME_MATCH or two_anchors_agree
    return c.coverage >= MIN_COVERAGE and name_ok


def _credible(c: Candidate, current: bool) -> bool:
    """Backed by more than a text-search hit: a matching name, or anchor evidence.

    For a gone ticker, "a company joined the index the day this one left" is NOT
    enough: that's usually a replacement (ACS was replaced by Urban Outfitters), not
    a rename. It counts only if the old ticker also appears in the candidate's own
    10-Ks (Meta's reports mention FB; Urban Outfitters' don't mention ACS)."""
    if c.name_match is not None and c.name_match >= 0.85:
        return True
    if current:
        return bool(c.sources & _CURRENT_ANCHORS)
    return {"membership_continuity", "sec_search_ticker"} <= c.sources


def decide(row: Row, cands: list[Candidate], known_name: str | None = None) -> dict[str, Any]:
    """Pure decision from verified candidates (tested without the network)."""
    current = row.end is None
    base = {"ticker": row.ticker, "start": row.start, "end": row.end or "", "cik": "",
            "sec_name": "", "status": "unresolved", "sources": "", "coverage": "",
            "name_match": "", "first_10k": "", "last_10k": "", "notes": ""}

    def listing(cs: list[Candidate]) -> str:
        return "; ".join(f"{c.cik} {c.sec_name or '?'} (10-Ks {c.first_10k} to {c.last_10k}, "
                         f"cov {c.coverage:.2f}, name {'n/a' if c.name_match is None else f'{c.name_match:.2f}'}, "
                         f"via {'+'.join(sorted(c.sources))})" for c in cs[:4])

    agree = current and any(_CURRENT_ANCHORS <= c.sources for c in cands)
    passing = [c for c in cands if _passes(c, agree and _CURRENT_ANCHORS <= c.sources)]
    good = sorted([c for c in passing if _credible(c, current)],
                  key=lambda c: (-c.coverage, -len(c.sources)))
    if not good:
        base["notes"] = ("nothing backed by a name or an anchor passed the SEC filing check"
                         + (f". Search hits only (not used): {listing(passing)}" if passing else "")
                         + (f". Tried: {listing(cands)}" if cands and not passing else "")
                         + ("" if cands else ". No candidates found"))
        return base
    if len(good) > 1 and known_name:
        # parent vs subsidiary (American Airlines Group vs American Airlines, Inc.):
        # take the clearly closer full name, never a near tie
        scored = sorted(good, key=lambda c: -max([token_jaccard(known_name, n) for n in c.window_names] or [0]))
        best = max([token_jaccard(known_name, n) for n in scored[0].window_names] or [0])
        second = max([token_jaccard(known_name, n) for n in scored[1].window_names] or [0])
        if best >= 0.6 and best - second >= 0.25:
            good = [scored[0]]
            base["notes"] = f"chosen over {scored[1].cik} {scored[1].sec_name} by a closer name match"
    if len(good) > 1:
        base.update(status="split" if _disjoint(good[:2]) else "conflict",
                    notes="more than one company passed: " + listing(good))
        return base
    c = good[0]
    strong_name = c.name_match is not None and c.name_match >= 0.85
    anchored = (bool(c.sources & _CURRENT_ANCHORS) if current
                else {"membership_continuity", "sec_search_ticker"} <= c.sources)
    status = "verified" if (len(c.sources) >= 2 or (strong_name and c.coverage >= 0.8)
                            or (anchored and strong_name)) else "likely"
    base.update(cik=str(c.cik), sec_name=c.sec_name, status=status,
                sources="+".join(sorted(c.sources)), coverage=f"{c.coverage:.2f}",
                name_match="" if c.name_match is None else f"{c.name_match:.2f}",
                first_10k=c.first_10k or "", last_10k=c.last_10k or "")
    if status == "likely":
        base["notes"] = (base["notes"] + "; " if base["notes"] else "") + \
            (f"only one source ({base['sources']}) and no matching name to back it; "
             "the SEC filing check passed")
    return base


def _disjoint(cs: list[Candidate]) -> bool:
    a, b = sorted(cs, key=lambda c: c.first_10k or "")
    return bool(a.last_10k and b.first_10k and a.last_10k <= b.first_10k)


# --- The agent -----------------------------------------------------------------

def resolve(row: Row, ctx: dict[str, Any], today: str) -> dict[str, Any]:
    cands: dict[int, Candidate] = {}

    def propose(cik: int | None, source: str) -> None:
        if cik:
            cands.setdefault(int(cik), Candidate(int(cik))).sources.add(source)

    t = row.ticker
    if row.end is None:                       # still a member: today's ticker owners
        sec_hit = ctx["sec"].get(sec_ticker(t))
        propose(sec_hit["cik"] if sec_hit else None, "sec_tickers")
        wiki_hit = ctx["wiki_current"].get(t) or ctx["wiki_current"].get(t.replace("-", "."))
        propose(wiki_hit["cik"] if wiki_hit else None, "wikipedia_current")
        known_name = wiki_hit["name"] if wiki_hit else None
        first = [verify(c, row, known_name, today, ctx.get("since", "2010-01-01")) for c in cands.values()]
        result = decide(row, first, known_name)
        if result["status"] == "verified":
            result["known_name"] = known_name or ""
            return result
        # The current company ID may be a new holding company (XOM, BLK, APA): its
        # history lives under a predecessor ID, so look for one.
        start_s = max(row.start, ctx.get("since", "2010-01-01"))
        if known_name:
            for h in _top(edgar.full_text_search(known_name, "10-K", start_s, today), 3):
                propose(h, "sec_search_name")
        for h in _top(edgar.full_text_search(t.replace(".", "-"), "10-K", start_s, today), 3):
            propose(h, "sec_search_ticker")
        verified = [verify(c, row, known_name, today, ctx.get("since", "2010-01-01")) for c in cands.values()]
        result = decide(row, verified, known_name)
        anchor = next((c for c in verified if _CURRENT_ANCHORS & c.sources), None)
        others = [c for c in verified if c is not anchor and _passes(c) and _credible(c, False)]
        if anchor and anchor.coverage < MIN_COVERAGE and others:
            result.update(status="split", cik="", notes=(
                f"today's company ID {anchor.cik} ({anchor.sec_name}) has little filing history; "
                f"a predecessor filed the earlier reports: " + "; ".join(
                    f"{c.cik} {c.sec_name} (10-Ks {c.first_10k} to {c.last_10k})" for c in others[:2])))
        result["known_name"] = known_name or ""
        return result
    else:
        removed = ctx["wiki_removed"].get(t, [])
        # the removal closest to this row's end date names the company
        near = sorted(removed, key=lambda r: abs((pd.Timestamp(r["date"] or "1900-01-01")
                                                   - pd.Timestamp(row.end)).days))
        known_name = near[0]["name"] if near and abs((pd.Timestamp(near[0]["date"] or "1900-01-01")
                                                      - pd.Timestamp(row.end)).days) <= 45 else None
        sec_hit = ctx["sec"].get(sec_ticker(t))
        propose(sec_hit["cik"] if sec_hit else None, "sec_tickers")   # may be a reused ticker
        start_s = max(row.start, ctx.get("since", "2010-01-01"))     # the window the backtest needs
        if known_name:
            for h in _top(edgar.full_text_search(known_name, "10-K", start_s, row.end), 3):
                propose(h, "sec_search_name")
        for h in _top(edgar.full_text_search(t, "10-K", start_s, row.end), 3):
            propose(h, "sec_search_ticker")
        # a ticker change: a current member whose row starts the day this one ends
        nxt = ctx["starts"].get(row.end, [])
        for other in nxt:
            hit = ctx["wiki_current"].get(other) or ctx["sec"].get(sec_ticker(other))
            if hit:
                propose(hit["cik"], "membership_continuity")
    verified = [verify(c, row, known_name, today, ctx.get("since", "2010-01-01")) for c in cands.values()]
    result = decide(row, verified, known_name)
    result["known_name"] = known_name or ""
    return result


def _top(hits: list[dict[str, Any]], n: int) -> list[int]:
    counts: dict[int, int] = {}
    for h in hits:
        counts[h["cik"]] = counts.get(h["cik"], 0) + 1
    return [cik for cik, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:n]]


def apply_overrides(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not OVERRIDES_CSV.exists():
        return results
    with OVERRIDES_CSV.open(encoding="utf-8") as f:
        overrides = {(r["ticker"].upper(), r["start"]): r for r in csv.DictReader(f)}
    for r in results:
        o = overrides.get((r["ticker"], r["start"]))
        if o:
            r.update(cik=o["cik"], status="reviewed", notes=f"reviewed by {o.get('reviewer', 'Marik')}: {o['reason']}")
    return results


def build(since: str = "2010-01-01", rows: list[Row] | None = None,
          progress: Callable[[int, int, dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    members = rows if rows is not None else load_membership(since)
    all_rows = load_membership("1900-01-01")
    starts: dict[str, list[str]] = {}
    for r in all_rows:
        starts.setdefault(r.start, []).append(r.ticker)
    ctx = {"sec": edgar.ticker_map(), "wiki_current": wikipedia_current(),
           "wiki_removed": wikipedia_removed(), "starts": starts, "since": since}
    results = []
    for i, row in enumerate(members):
        try:
            res = resolve(row, ctx, today)
        except edgar.EdgarError as exc:
            res = {"ticker": row.ticker, "start": row.start, "end": row.end or "", "cik": "",
                   "sec_name": "", "status": "unresolved", "sources": "", "coverage": "",
                   "name_match": "", "first_10k": "", "last_10k": "", "known_name": "",
                   "notes": f"SEC error: {exc}"}
        results.append(res)
        if progress:
            progress(i + 1, len(members), res)
    return apply_overrides(results)


FIELDS = ["ticker", "start", "end", "cik", "sec_name", "status", "sources", "coverage",
          "name_match", "first_10k", "last_10k", "known_name", "notes"]


def write_outputs(results: list[dict[str, Any]]) -> dict[str, int]:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    review = [r for r in results if r["status"] in ("split", "conflict", "unresolved", "likely")]
    lines = [
        "# Ticker-to-company review list",
        "",
        "Generated by `backend/cik_map.py`. Each row below could not be confirmed by two sources "
        "plus the SEC filing check. To decide one, add a line to `ticker_cik_overrides.csv` "
        "(`ticker,start,cik,reason,reviewer`) and re-run. Your decision always wins.",
        "",
        "Sources: SEC EDGAR (ticker list, full-text search, filing records) and Wikipedia "
        "([current members](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies), "
        "[historical changes](https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500), "
        "CC BY-SA).",
        "",
        "Counts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
        "| Ticker | In index | Status | Name (Wikipedia) | Best candidate | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for r in review:
        link = (f"[SEC](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r['cik']})"
                if r["cik"] else "")
        lines.append(f"| {r['ticker']} | {r['start']} to {r['end'] or 'now'} | {r['status']} | "
                     f"{r.get('known_name', '')} | {r['cik']} {r['sec_name']} {link} | "
                     f"{(r['notes'] or '').replace('|', '/')} |")
    REVIEW_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts
