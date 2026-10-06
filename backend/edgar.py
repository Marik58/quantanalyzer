"""SEC EDGAR financial statements, as first filed (Roadmap Phase 3).

Free, official, and point-in-time: every number in the SEC's "company facts"
API carries the date it was filed. That is what makes an honest backtest of
the Business, Growth and Value lenses possible: on any past date we can use
only the numbers that had already been published.

Three things the raw data does that this module handles (each was checked
against Apple's real company facts on 2026-10-06):

1. The same fiscal year appears many times: every later annual report repeats
   prior years as comparatives. We keep the FIRST filing of each period, so a
   later restatement never leaks backwards into the past.
2. Annual reports (10-K) also carry quarter-length numbers tagged fp="FY". We
   keep a flow (revenue, income, cash flow) only if its period is about a year
   long (350-380 days), whatever its tags say.
3. Companies renamed concepts over time (e.g. "Revenues" became
   "RevenueFromContractWithCustomerExcludingAssessedTax" after ASC 606 in
   2018). Each metric has a fallback chain; for every period the first concept
   in the chain that reports it wins.

The SEC requires every request to identify a contact. Set SEC_USER_AGENT in
.env (it is used only for requests to sec.gov). Requests are kept under the
SEC's 10-per-second limit and the raw JSON is cached under data/edgar/.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "edgar"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MIN_INTERVAL = 0.15            # seconds between requests: under the SEC's 10/second limit
MAX_AGE_DAYS = 7               # re-download cached facts after a week (new filings)

# metric -> (taxonomy, unit, kind, concept chain, mode).
#   kind: "flow" = over a period (income statement, cash flow); "instant" = at a date.
#   mode: "earliest" when the concepts mean the same thing (a renamed concept):
#         take the earliest filing across all of them, so the date really is the
#         first time the number was public. "priority" when later concepts are
#         genuinely different measures: use one only where the earlier is missing.
METRICS: dict[str, tuple[str, str, str, list[str], str]] = {
    "revenue": ("us-gaap", "USD", "flow", [
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax"], "earliest"),
    "gross_profit": ("us-gaap", "USD", "flow", ["GrossProfit"], "priority"),
    "operating_income": ("us-gaap", "USD", "flow", ["OperatingIncomeLoss"], "priority"),
    "net_income": ("us-gaap", "USD", "flow", ["NetIncomeLoss"], "priority"),
    "rd_expense": ("us-gaap", "USD", "flow", ["ResearchAndDevelopmentExpense"], "priority"),
    "stock_comp": ("us-gaap", "USD", "flow", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"], "priority"),
    "operating_cash_flow": ("us-gaap", "USD", "flow", ["NetCashProvidedByUsedInOperatingActivities"], "priority"),
    "capex": ("us-gaap", "USD", "flow", ["PaymentsToAcquirePropertyPlantAndEquipment"], "priority"),
    "total_assets": ("us-gaap", "USD", "instant", ["Assets"], "priority"),
    "total_liabilities": ("us-gaap", "USD", "instant", ["Liabilities"], "priority"),
    "equity": ("us-gaap", "USD", "instant", [
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "priority"),
    "cash": ("us-gaap", "USD", "instant", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], "priority"),
    "long_term_debt": ("us-gaap", "USD", "instant", ["LongTermDebtNoncurrent", "LongTermDebt"], "priority"),
    "receivables": ("us-gaap", "USD", "instant", ["AccountsReceivableNetCurrent"], "priority"),
    "shares_outstanding": ("dei", "shares", "instant", ["EntityCommonStockSharesOutstanding"], "priority"),
}
_ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "10-K405", "10-KT/A")


class EdgarError(RuntimeError):
    """A download or parse failed; the message says why."""


# --- Downloading -------------------------------------------------------------

def user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT", "").strip()
    if not ua:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
            ua = os.getenv("SEC_USER_AGENT", "").strip()
        except ImportError:
            pass
    if not ua or "@" not in ua:
        raise EdgarError("The SEC requires a contact on every request: set SEC_USER_AGENT in "
                         ".env to a name and email, e.g. 'MyApp research (Name, me@example.com)'.")
    return ua


_last_request = 0.0


def _get_json(url: str, retries: int = 3) -> Any:
    global _last_request
    for attempt in range(retries):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent(),
                                                   "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise EdgarError(f"not found on EDGAR: {url}") from exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise EdgarError(f"EDGAR returned HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise EdgarError(f"could not reach EDGAR: {exc.reason}") from exc
    raise EdgarError(f"gave up on {url}")


def _cached(path: Path, url: str, max_age_days: float) -> Any:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - payload.get("_fetched_at", 0)
        if age < max_age_days * 86400:
            return payload["data"]
    data = _get_json(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"_fetched_at": time.time(), "_url": url, "data": data}),
                    encoding="utf-8")
    return data


def ticker_map(max_age_days: float = MAX_AGE_DAYS) -> dict[str, dict[str, Any]]:
    """TICKER -> {"cik": int, "title": str} for every company on EDGAR."""
    raw = _cached(CACHE_DIR / "company_tickers.json", TICKERS_URL, max_age_days)
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]} for v in raw.values()}


def cik_for(ticker: str) -> int:
    t = ticker.upper().strip()
    m = ticker_map()
    hit = m.get(t) or m.get(t.replace(".", "-")) or m.get(t.replace("-", "."))
    if hit is None:
        raise EdgarError(f"{t} is not in EDGAR's ticker list (delisted, foreign, or renamed)")
    return hit["cik"]


def company_facts(ticker: str, max_age_days: float = MAX_AGE_DAYS) -> dict[str, Any]:
    cik = cik_for(ticker)
    return _cached(CACHE_DIR / "facts" / f"CIK{cik:010d}.json", FACTS_URL.format(cik=cik), max_age_days)


# --- Parsing: first-filed, point-in-time ----------------------------------------

def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def annual_values(facts: dict[str, Any], metric: str,
                  as_of: str | date | None = None) -> list[dict[str, Any]]:
    """One value per fiscal-year period, as FIRST filed, known on or before as_of.

    Returns [{"end", "start", "value", "filed", "form", "accn", "concept"}] sorted by end.
    """
    taxonomy, unit, kind, chain, mode = METRICS[metric]
    cutoff = str(as_of)[:10] if as_of else None
    tax = facts.get("facts", {}).get(taxonomy, {})
    candidates: dict[str, list[dict[str, Any]]] = {}     # period end -> one row per concept
    for rank, concept in enumerate(chain):
        best: dict[str, dict[str, Any]] = {}
        for r in tax.get(concept, {}).get("units", {}).get(unit, []):
            if r.get("form") not in _ANNUAL_FORMS:
                continue
            if kind == "flow" and (not r.get("start") or not 350 <= _days(r["start"], r["end"]) <= 380):
                continue   # quarter-length numbers inside a 10-K
            if cutoff and r["filed"] > cutoff:
                continue   # not public yet on as_of
            if r["end"] not in best or r["filed"] < best[r["end"]]["filed"]:
                best[r["end"]] = {**r, "concept": concept, "rank": rank}
        for end, row in best.items():
            candidates.setdefault(end, []).append(row)
    out = []
    for end, rows in candidates.items():
        row = (min(rows, key=lambda r: (r["filed"], r["rank"])) if mode == "earliest"
               else min(rows, key=lambda r: r["rank"]))
        out.append({"end": row["end"], "start": row.get("start"), "value": float(row["val"]),
                    "filed": row["filed"], "form": row["form"], "accn": row.get("accn"),
                    "concept": row["concept"]})
    return sorted(out, key=lambda r: r["end"])


def statements(ticker: str, as_of: str | date | None = None,
               metrics: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Every metric's first-filed annual values for one company, as known on as_of."""
    facts = company_facts(ticker)
    return {m: annual_values(facts, m, as_of) for m in (metrics or list(METRICS))}


def fetched_on(ticker: str) -> str | None:
    """When the cached facts for this ticker were downloaded (UTC date)."""
    try:
        path = CACHE_DIR / "facts" / f"CIK{cik_for(ticker):010d}.json"
        ts = json.loads(path.read_text(encoding="utf-8")).get("_fetched_at")
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None
    except (EdgarError, OSError, ValueError):
        return None
