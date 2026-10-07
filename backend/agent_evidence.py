"""Writes each agent's evidence file (context/agents/<id>/evidence.md) from the research,
giving every agent what its job needs and nothing its charter forbids.

Who gets what (docs/AGENT_CHARTERS.md, the "Can see / Cannot see" lines):

| Evidence | Goes to | Why |
|---|---|---|
| Base rates for any S&P 500 stock | everyone (_shared) | House rule 5: start from the base rate |
| What happened after big price moves | Trend Trader, Hype Watch, Risk Manager, Chief Analyst | They may see prices. The Growth Hunter and Quality & Value may NOT (charters §9.2-9.3), so they never get it |
| A twin's backtest | that agent, and the Chief Analyst (it weighs every agent) | An agent should know its own method's record |
| Form 8-K items | News Analyst, Hype Watch | Their charters read filings ("8-K event types"; "whether real news explains the move") |
| Data hazards and guards | Auditor, Source Checker | They check data and sources |
| Source trust tiers | Source Checker | Its job is rating sources |

Macro Strategist, Supply-Chain Mapper, Horizon Scout, Bull and Bear get only the shared base
rates for now; their evidence arrives with their data (Phases 7-8).

Run `python scripts/refresh_agent_evidence.py` after any backtest or base-rate rebuild.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BOXES = ROOT / "context" / "agents"
BASE_RATES = ROOT / "context" / "research" / "base_rates.json"
BACKTESTS = ROOT / "context" / "research" / "backtests"
MOVE_HISTORY_MARKER = "What happened after big price moves"    # tests check who gets this

# The Trend twin's record (scripts/_universe_pilot_n200.log, run 2026-09-21): numbers
# copied from that log, which predates the backtests folder.
TREND_TWIN = {"source": "scripts/_universe_pilot_n200.log (run 2026-09-21)", "stocks": 200, "months": 37,
              "window": "2023-08-31 to 2026-08-20", "observations": 6662, "technical_ic": 0.022,
              "technical_t": 0.72, "technical_q": 0.66, "composite_ir": 0.20, "composite_t": 0.35}

ROUTES: dict[str, list[str]] = {
    "_shared": ["base"],
    "trend-trader": ["trend_twin", "moves"],
    "growth-hunter": ["twin:growth-v1"],
    "quality-value": ["twin:value-v1"],
    "news-analyst": ["8k"],
    "hype-watch": ["moves", "drops", "8k"],
    "risk-manager": ["moves", "drops"],
    "chief-analyst": ["scoreboard", "moves"],
    "auditor": ["hazards"],
    "source-checker": ["tiers", "hazards"],
}


def pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


def latest_run(prefix: str = "screens-v1") -> Path | None:
    runs = sorted(p for p in BACKTESTS.glob(f"*-{prefix}*") if (p / "summary.json").exists())
    return runs[-1] if runs else None


# --- Blocks ---------------------------------------------------------------------------

def block_base(r: dict[str, Any]) -> str:
    a = r["all_stocks"]
    return f"""## Base rates: a typical S&P 500 stock

From {r['period']} ({a['n']:,} stock-months, S&P 500 members at the time):
- beat the S&P 500 over the next 12 months: **{pct(a['beat_spy_next_12m'])}** of the time
- beat it over the next month: {pct(a['beat_spy_next_month'])}
- returned 25% or more over the next 12 months: {pct(a['made_25pct_next_12m'])}
- fell 30% or more at some point within 3 months: {pct(a['fell_30pct_within_3m'])}

Start every probability here and move only as far as your evidence justifies (house rule 5).
A forecaster that always says these numbers is the Base-Rate Forecaster; beating it is the
minimum. Limits: large caps only, from 2011; companies that no longer trade are missing.
"""


def _table(rows: list[dict[str, Any]], drops: bool) -> str:
    head = "| Past move | Cases | Beat S&P 500 next 12m | All stocks, same months | t |" + (" Fell 30%+ within 3m |" if drops else "")
    sep = "|---|---|---|---|---|" + ("---|" if drops else "")
    lines = [head, sep]
    for x in rows:
        lines.append(f"| {x['bucket']} | {x['n']:,} | {pct(x['beat_spy_next_12m'])} | "
                     f"{pct(x['same_months_all_stocks'])} | {x['vs_all_stocks_t']:+.2f} |"
                     + (f" {pct(x['fell_30pct_within_3m'])} |" if drops else ""))
    return "\n".join(lines)


def block_moves(r: dict[str, Any], drops: bool = False) -> str:
    rows = r["after_1_month_move"] + r["after_12_month_move"]
    strong = [x for x in rows if abs(x["vs_all_stocks_t"]) >= 2]
    if not strong:
        meaning = ("no past-move group differs reliably from other stocks (every |t| < 2). A big move by "
                   "itself hasn't predicted the next year for large caps. Don't treat a jump as momentum "
                   "or a drop as a bargain without other evidence.")
    else:
        meaning = ("these groups differ reliably from other stocks (|t| >= 2): " + "; ".join(
            f"{x['bucket']} ({pct(x['beat_spy_next_12m'])} vs {pct(x['same_months_all_stocks'])}, "
            f"t = {x['vs_all_stocks_t']:+.2f})" for x in strong) + ". The rest don't.")
    return f"""## {MOVE_HISTORY_MARKER}

S&P 500 members, {r['period']}. "t" compares each group with all stocks in the same months,
allowing for overlapping windows; |t| under 2 means no reliable difference.

After a 1-month move:

{_table(r['after_1_month_move'], drops)}

After a 12-month move:

{_table(r['after_12_month_move'], drops)}

**What this means:** {meaning}
"""


def block_drops(r: dict[str, Any]) -> str:
    rows = {x["bucket"]: x for x in r["after_1_month_move"]}
    up, down = rows.get("rose 20%+"), rows.get("fell 20%+")
    return f"""## Base rate for `p_drop_30` (a 30%+ fall within 3 months)

- Any S&P 500 stock: {pct(r['all_stocks']['fell_30pct_within_3m'])}
- After rising 20%+ in a month: {pct(up['fell_30pct_within_3m']) if up else 'n/a'} ({up['n'] if up else 0:,} cases)
- After falling 20%+ in a month: {pct(down['fell_30pct_within_3m']) if down else 'n/a'} ({down['n'] if down else 0:,} cases)

These are **large caps**. Pump-and-dump targets are usually tiny stocks, where the charter's
lesson applies instead: promoted stocks fell 53% on average within 120 trading days (Leuz et al.).
"""


def block_twin(version: str, run: Path) -> str:
    s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    x, a = s["results"][version], s["results"][version].get("factor_adjusted") or {}
    b = s["base_rates"][version]
    rel = run.relative_to(ROOT).as_posix()
    return f"""## Your twin: {version}, the rule version of your method

Backtest `{rel}`: S&P 500 members month by month, {x['start']} to {x['end']} ({x['months']}
months), SEC numbers used only after they were filed, after a {s['cost_bps']:.0f} bp trading cost.

- **Stage A: {x['stage_a'].upper()}.** Against its Candidate Pool: {pct(x['excess_per_year'], True)} a year,
  t = {x['excess_t']:+.2f}. After known factor tilts: alpha {a.get('alpha_per_year', 0):+.2%} a year, t = {a.get('alpha_t', 0):+.2f}.
- Yearly growth after costs: picks {pct(x['cagr_picks_net'])}, pool {pct(x['cagr_pool'])}, SPY {pct(x['cagr_spy'])};
  full years at 25%+: {x['years_at_25pct']} of {x['years']}.
- A pick beat SPY over the next 12 months {pct(b['picks']['beat_spy'])} of the time and made 25%+
  {pct(b['picks']['made_25pct'])} (n = {b['picks']['n']:,}); any pool stock: {pct(b['pool']['beat_spy'])} and {pct(b['pool']['made_25pct'])}.

**What this means:** passing the rule is not, by itself, a reason for a positive stance. Your
value has to come from judgment the rule doesn't capture, and the scoreboard will check
whether it does (Stage B: not worse than this twin on the same stocks).
"""


def block_trend_twin() -> str:
    t = TREND_TWIN
    return f"""## Your twin: the technical score (backend/analysis/signals.py)

Source: `{t['source']}`. {t['stocks']} randomly sampled S&P 500 members (point-in-time),
{t['window']}, {t['months']} months, {t['observations']:,} observations.
- Rank correlation with next month's return: +{t['technical_ic']:.3f}, t = +{t['technical_t']:.2f}
  (q = {t['technical_q']:.2f} after correcting for five components): **no measurable edge.**
- The full composite score: information ratio +{t['composite_ir']:.2f}, t = +{t['composite_t']:.2f}.

**What this means:** a "strong" stance needs a reason beyond the technical score.
"""


def block_scoreboard(run: Path | None) -> str:
    lines = ["## The panel's track records so far (weigh agents by these)", "",
             "| Agent | Its twin's record | Verdict |", "|---|---|---|",
             f"| Trend Trader | technical score: IC +{TREND_TWIN['technical_ic']:.3f}, t = +{TREND_TWIN['technical_t']:.2f} "
             f"({TREND_TWIN['months']} months) | no measurable edge |"]
    if run:
        s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        for version, name in (("growth-v1", "Growth Hunter"), ("value-v1", "Quality & Value")):
            x = s["results"][version]
            lines.append(f"| {name} | {version}: {pct(x['excess_per_year'], True)}/yr vs pool, t = {x['excess_t']:+.2f} "
                         f"({x['months']} months) | Stage A {x['stage_a']} |")
    lines += ["", "No agent has a proven edge yet, and no AI agent has graded calls yet. When agents agree, "
              "that isn't extra evidence if their methods have no record; say so. Weight a view by its "
              "record, not by how confident it sounds."]
    return "\n".join(lines) + "\n"


def block_8k() -> str:
    from backend.briefing import ITEMS_8K
    rows = "\n".join(f"| {k} | {v} |" for k, v in ITEMS_8K.items())
    return f"""## Reading SEC Form 8-K filings (item codes)

Companies must file an 8-K within four business days of these events. Titles as printed on
the SEC's Form 8-K (sec.gov/files/form8-k.pdf):

| Item | Event |
|---|---|
{rows}

**Use it this way:** before reading a big move as hype or momentum, check for an 8-K. Example
from the data: PTC rose 33% on 2026-10-05, the day its 8-K reported Item 1.01 (a material
agreement): Schneider Electric agreed to buy it for $205 a share in cash. A cash buyout
caps the price near the deal price. That's news, not a trend.
"""


def _n(x: Any) -> str:
    return f"{x:,}" if isinstance(x, (int, float)) else "n/a"


def block_hazards(run: Path | None) -> str:
    cov = json.loads((run / "summary.json").read_text(encoding="utf-8"))["coverage"] if run else {}
    reasons = cov.get("missing_by_reason", {})
    return f"""## Known data hazards, and how the pipeline guards against them

Check any packet against these (counts from the latest backtest data build):
- **Scale typos in filings** (McDonald's tagged 732.3 shares for 2023, meaning millions):
  {_n(cov.get('rows_with_guarded_ratio'))} rows had a ratio blanked as a likely typo;
  {_n(cov.get('market_value_from_cover_count'))} market values used the cover-page share count instead.
- **Reused tickers** (BBT is now a different bank): prices are looked up by the company's
  ticker today, from its SEC ID, never by the old ticker.
- **A company ID that took over a ticker later** (IR was Gardner Denver until 2020):
  {reasons.get('company ID belonged to another company then', 0):,} rows excluded.
- **Holding-company reorganizations** (Google to Alphabet): linked only when the new company's
  first annual report shows the old one's revenue, two years matching within 0.5%.
- **Unverified company IDs are excluded, never guessed**:
  {sum(v for k, v in reasons.items() if k.startswith('company ID not verified')):,} rows.
- **Companies that no longer trade** have no free prices:
  {reasons.get('no longer trades (the SEC lists no current ticker)', 0):,} rows. This survivorship gap is the
  biggest limit on every backtest number.
- **Restatements**: every financial number is the first-filed value, used only after its
  filing date.

Rules for quoting numbers: context/project/honesty-rules.md.
"""


def block_tiers() -> str:
    return """## Source trust tiers (full list: context/data/sources.md)

- **Tier A, decides:** official or research-grade. SEC EDGAR filings, Kenneth French's data
  library, government statistics (FRED/ALFRED), peer-reviewed research.
- **Tier B, used and cross-checked:** reliable but unofficial or community-maintained. Yahoo
  Finance prices, the GitHub S&P 500 membership history, reputable press.
- **Tier C, suggests only:** Wikipedia, search results, headlines. Never enough on its own.

The house pattern: several sources suggest, the official one decides, and disagreements are
shown, not resolved by guessing.
"""


# --- Writing ---------------------------------------------------------------------------

def refresh(run: Path | None = None) -> dict[str, Path]:
    run = run or latest_run()
    rates = json.loads(BASE_RATES.read_text(encoding="utf-8")) if BASE_RATES.exists() else None
    sources = [p for p in (BASE_RATES.relative_to(ROOT).as_posix() if rates else None,
                           (run / "summary.json").relative_to(ROOT).as_posix() if run else None) if p]
    written = {}
    for agent_id, blocks in ROUTES.items():
        parts = []
        for blk in blocks:
            if blk == "base" and rates:
                parts.append(block_base(rates))
            elif blk == "moves" and rates:
                parts.append(block_moves(rates, drops="drops" in blocks))
            elif blk == "drops" and rates:
                parts.append(block_drops(rates))
            elif blk.startswith("twin:") and run:
                parts.append(block_twin(blk[5:], run))
            elif blk == "trend_twin":
                parts.append(block_trend_twin())
            elif blk == "scoreboard":
                parts.append(block_scoreboard(run))
            elif blk == "8k":
                parts.append(block_8k())
            elif blk == "hazards":
                parts.append(block_hazards(run))
            elif blk == "tiers":
                parts.append(block_tiers())
        if not parts:
            continue
        title = "every agent" if agent_id == "_shared" else agent_id
        text = (f"---\nid: {agent_id}\nkind: agent-evidence\neditable_by: code (backend/agent_evidence.py)\n"
                f"updated: {date.today().isoformat()}\nsources: {', '.join(sources)}\n---\n\n"
                f"# Evidence for {title}\n\n" + "\n".join(parts))
        path = BOXES / agent_id / "evidence.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written[agent_id] = path
    return written
