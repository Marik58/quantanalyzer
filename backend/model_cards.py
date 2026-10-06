"""Model cards: one shape for every model's reading of a stock (Roadmap Phase 2).

Each model answers one question through one lens. A card holds:
- the outlook and the horizon it applies to
- how strongly the evidence points
- the evidence itself (every number computed here, in code)
- plain reasons, and what the model is bad at
- its track record so far, and the lesson that explains it

Built for the agent ecosystem (docs/AGENT_CHARTERS.md):
- Every evidence number has a stable field name (e.g. `dcf_upside`) and a raw
  value, so agents can cite numbers by field and the Auditor can check them.
- `card.packet()` is the evidence packet: the subject, the model version, the
  data date, and every field. It is what gets sealed in the ledger.
- `outlook_from_packet(packet)` recomputes the outlook from the packet alone.
  The card's own outlook is computed exactly that way, so any sealed call can
  be re-checked later (the Auditor's code check).
- Business and News calls are sealed weekly on the tracking list
  (`record_model_calls`), so these rule models build track records too.

The outlook rules are deliberately simple and visible. Strength can never be
"high" until a model's track record passes the bar in AGENT_CHARTERS.md §14,
and no model passes it yet.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable

import pandas as pd

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
OUTLOOKS = ("up", "flat", "down")
STRENGTHS = ("low", "medium", "high")
OUTLOOK_TO_STANCE = {"up": "positive", "flat": "neutral", "down": "negative"}

# Bump a model's version whenever its rules change: its track record restarts.
MODEL_VERSIONS = {
    "business": "business-v1",
    "resilience": "resilience-v1",
    "trend": "v0-signals-technical-score",   # the same rule the Trend twin records
    "news": "news-v1",
}
# Models whose calls are sealed in the ledger every week, and their horizons in
# trading days. (Trend is already sealed by the Trend twin; Resilience doesn't forecast.)
RECORDED_HORIZONS = {"business": 252, "news": 20}

# A DCF whose fair value is more than this far from the price is treated as
# not fitting the company: with fixed assumptions it calls most large
# companies 60-90% overvalued (measured 2026-10-06 on 10 large caps).
DCF_MAX_GAP = 0.5
DCF_UNFIT_SECTORS = ("Financial Services",)   # banks and insurers: FCF-based DCF doesn't apply
MIN_HEADLINES = 5

# The S&P 500's closing peak and trough for each major decline since 2000.
# A stock's behavior is measured over exactly the market's peak-to-trough dates.
MARKET_DECLINES = [
    {"id": "dotcom", "name": "Dot-com bust", "peak": "2000-03-24", "trough": "2002-10-09"},
    {"id": "gfc", "name": "Global financial crisis", "peak": "2007-10-09", "trough": "2009-03-09"},
    {"id": "late2018", "name": "Late-2018 sell-off", "peak": "2018-09-20", "trough": "2018-12-24"},
    {"id": "covid", "name": "COVID crash", "peak": "2020-02-19", "trough": "2020-03-23"},
    {"id": "rates2022", "name": "2022 rate shock", "peak": "2022-01-03", "trough": "2022-10-12"},
]


@dataclass
class Evidence:
    label: str
    value: str                                   # what a person reads
    detail: str = ""
    field: str = ""                              # stable name agents cite, e.g. "dcf_upside"
    raw: float | int | str | None = None         # the number itself, computed in code


@dataclass
class TrackRecord:
    status: str        # "tested" | "untested" | "not_a_forecast"
    summary: str


@dataclass
class ModelCard:
    model_id: str
    title: str
    question: str
    horizon: str
    outlook: str | None            # up | flat | down; None = no outlook from this model
    strength: str | None           # low | medium | high
    headline: str
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    track_record: TrackRecord | None = None
    lessons: list[str] = field(default_factory=list)   # Learn-tab glossary ids
    deep_dive: str = ""            # the tab with the full analysis
    error: str | None = None
    subject: str = ""
    model_version: str = ""
    as_of: str | None = None       # date of the latest price the card used
    inputs: dict[str, Any] = field(default_factory=dict)   # other values the rule reads

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def packet(self) -> dict[str, Any]:
        """The evidence packet: everything the outlook rule reads, by field name."""
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "subject": self.subject,
            "as_of": self.as_of,
            "fields": {e.field: e.raw for e in self.evidence if e.field},
            "inputs": self.inputs,
        }


def _cap_strength(strength: str | None, proven: bool = False) -> str | None:
    """No model has earned "high" until its record passes the real-money bar."""
    if strength == "high" and not proven:
        return "medium"
    return strength


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _pct(x: float | None, signed: bool = True, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _as_of(ticker: str) -> str | None:
    """The date of the latest daily price the cards are working from."""
    from backend.analysis import data as data_mod

    td = data_mod.load(ticker)
    return td.history.index[-1].date().isoformat() if td is not None else None


def _finish(card: ModelCard, extra_reasons: list[str] | None = None) -> ModelCard:
    """Set the outlook from the card's own packet, so it can always be re-checked."""
    card.outlook, card.strength, rule_reasons = outlook_from_packet(card.packet())
    card.reasons = rule_reasons + (extra_reasons or [])
    return card


# --- Business: is this a healthy company at a sensible price? -------------

def business_outlook(dcf_upside: float | None, dcf_reliable: bool, dcf_applicable: bool,
                     peer_label: str | None, revenue_growth: float | None,
                     operating_margin: float | None) -> tuple[str | None, str | None, list[str]]:
    """Two valuation lenses vote cheap (+1), fair (0) or expensive (-1);
    business health can block an "up". Returns (outlook, strength, reasons)."""
    votes: list[int] = []
    reasons: list[str] = []
    if dcf_upside is None:
        pass
    elif not dcf_applicable:
        reasons.append("A cash-flow model doesn't fit this company (banks and insurers, or it "
                       "produced a negative value), so it isn't counted.")
    elif not dcf_reliable:
        reasons.append("The cash-flow model is unreliable here (negative or erratic cash flow), "
                       "so it isn't counted.")
    elif abs(dcf_upside) > DCF_MAX_GAP:
        reasons.append(f"The cash-flow model puts fair value {_pct(dcf_upside)} from the price. A "
                       "gap that large usually means its fixed assumptions don't fit this company, "
                       "so it isn't counted (see the Valuation tab's sensitivity table).")
    elif dcf_upside > 0.15:
        votes.append(1)
        reasons.append(f"The cash-flow model (DCF) puts fair value {_pct(dcf_upside)} from the price: cheap.")
    elif dcf_upside < -0.15:
        votes.append(-1)
        reasons.append(f"The cash-flow model (DCF) puts fair value {_pct(dcf_upside)} from the price: expensive.")
    else:
        votes.append(0)
        reasons.append("The cash-flow model (DCF) says the price is about fair (within ±15%).")

    label = (peer_label or "").lower()
    if label.startswith("cheap"):
        votes.append(1)
        reasons.append("Against its peers it looks cheap on earnings, sales, growth and margins.")
    elif label.startswith("expensive"):
        votes.append(-1)
        reasons.append("Against its peers it looks expensive or weak on earnings, sales, growth and margins.")
    elif label.startswith("fair"):
        votes.append(0)
        reasons.append("Against its peers it looks about fairly priced.")

    healthy: bool | None = None
    if revenue_growth is not None and operating_margin is not None:
        healthy = revenue_growth > 0 and operating_margin > 0
        reasons.append("Revenue is growing and the core business is profitable." if healthy else
                       "Revenue is shrinking or the core business is losing money.")

    if not votes:
        reasons.append("No valuation lens could vote, so there is no outlook.")
        return None, None, reasons
    score = sum(votes)
    if score > 0 and healthy is not False:
        outlook = "up"
    elif score < 0 or (healthy is False and score <= 0):
        outlook = "down"
    else:
        outlook = "flat"
    lenses_agree = len(votes) == 2 and votes[0] == votes[1] != 0
    strength = "medium" if lenses_agree and healthy is not None else "low"
    return outlook, _cap_strength(strength), reasons


_FUNDAMENTAL_KEYS = ("revenueGrowth", "grossMargins", "operatingMargins", "profitMargins",
                     "debtToEquity", "returnOnEquity", "sector", "shortName")


@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda t: f"card_fundamentals:{t}")
def _fundamentals(ticker: str) -> dict[str, Any]:
    """Growth, margins, debt, sector and name from Yahoo's company summary.
    (data.load keeps only a few summary fields, and these aren't among them.)"""
    import yfinance as yf

    from backend.analysis import data as data_mod

    info, _err = data_mod._yf_call_with_retry(
        ticker, "fundamentals", lambda: yf.Ticker(ticker, session=data_mod._SESSION).info or {})
    return {k: info.get(k) for k in _FUNDAMENTAL_KEYS if info and k in info}


def business_card(ticker: str) -> ModelCard:
    from backend.analysis import peers as peers_mod
    from backend.analysis import valuation as val_mod

    info = _fundamentals(ticker)
    dcf = val_mod.compute(ticker)
    try:
        pc = peers_mod.compute(ticker)
    except Exception:
        pc = None

    upside = _num(dcf.weighted_upside_pct)
    fair = _num(dcf.weighted_intrinsic)
    price = _num(dcf.current_price)
    sector = info.get("sector") or ""
    reliability = dcf.history.reliability if dcf.history else "n/a"
    applicable = sector not in DCF_UNFIT_SECTORS and (fair is None or fair > 0)
    growth = _num(info.get("revenueGrowth"))
    gross = _num(info.get("grossMargins"))
    op_margin = _num(info.get("operatingMargins"))
    de = _num(info.get("debtToEquity"))
    de_ratio = de / 100 if de is not None else None   # Yahoo reports it in percent
    peer_score = _num(pc.relative_value_score) if pc else None

    # A DCF value is an estimate, never a fact: label it as one and name its source.
    if fair is None or price is None:
        dcf_value, dcf_detail = "n/a", ""
    elif not applicable:
        dcf_value = "not meaningful here"
        dcf_detail = "A free-cash-flow DCF doesn't fit banks and insurers, or it came out negative"
    elif upside is not None and abs(upside) > DCF_MAX_GAP:
        dcf_value = "model doesn't fit (not counted)"
        dcf_detail = (f"Estimate from this app's DCF (fixed assumptions): ${fair:,.2f} vs price "
                      f"${price:,.2f}. A gap this large points to the assumptions, not the stock.")
    else:
        dcf_value = f"estimate ${fair:,.2f} vs ${price:,.2f} ({_pct(upside)})"
        dcf_detail = ("Estimate, not a fact: this app's DCF with fixed growth and discount-rate "
                      "assumptions, weighted across bear, base and bull cases")
    card = ModelCard(
        model_id="business", title="Business",
        question="Is this a healthy, growing company at a sensible price?",
        horizon="1 year or more", outlook=None, strength=None, headline="",
        evidence=[
            Evidence("Revenue growth", _pct(growth), "Latest year over year", "revenue_growth", growth),
            Evidence("Gross margin", _pct(gross, signed=False), "", "gross_margin", gross),
            Evidence("Operating margin", _pct(op_margin, signed=False),
                     "Profit from the core business per $1 of sales", "operating_margin", op_margin),
            Evidence("Debt to equity", "n/a" if de_ratio is None else f"{de_ratio:.2f}×", "",
                     "debt_to_equity", de_ratio),
            Evidence("DCF fair value vs price", dcf_value, dcf_detail, "dcf_upside", upside),
            Evidence("Relative value vs peers",
                     "no peer group for this stock" if peer_score is None else
                     f"{peer_score:.0f}/100 ({pc.relative_value_label})",
                     f"Peers: {', '.join(pc.peers_used)}" if pc and pc.peers_used else
                     "Peer groups currently cover 25 hand-picked stocks", "peer_score", peer_score),
        ],
        caveats=[
            "DCF fair values swing a lot with small changes in growth and discount-rate "
            "assumptions, and fixed assumptions tend to call fast growers overvalued.",
            "It uses today's financial snapshot, so it can't see what changed since the last report.",
            "Peer comparisons depend on who counts as a peer, and only 25 stocks have a peer group so far.",
        ],
        track_record=TrackRecord("untested",
            "Never tested. A fair test needs financial statements as they were known at the "
            "time, which arrive with SEC filings in Roadmap Phase 3. Its weekly calls are "
            "sealed in the ledger from October 2026."),
        lessons=["dcf", "multiples", "relative-value-score"], deep_dive="valuation",
        subject=ticker, model_version=MODEL_VERSIONS["business"], as_of=_as_of(ticker),
        inputs={"dcf_reliable": reliability not in ("negative", "volatile", "n/a"),
                "dcf_reliability": reliability, "dcf_applicable": applicable,
                "dcf_fair_value": fair, "price": price, "sector": sector,
                "peer_label": pc.relative_value_label if pc else None,
                "peers_used": pc.peers_used if pc else []})
    _finish(card)
    card.headline = {
        "up": "The business looks healthy, and the price looks low against its cash flows or its peers.",
        "down": "The price looks high against its cash flows or peers, or the business is weakening.",
        "flat": "No clear signal: the valuation lenses disagree, or say the price is about fair.",
        None: "No reliable valuation lens for this stock, so no outlook.",
    }[card.outlook]
    return card


# --- Resilience: how does it behave when the market falls? ---------------

def decline_stats(stock: pd.Series, market: pd.Series, window: dict[str, str]) -> dict[str, Any] | None:
    """The stock over the market's exact peak-to-trough dates, plus how long it
    took to get back to its starting price. None if it wasn't trading yet."""
    peak, trough = pd.Timestamp(window["peak"]), pd.Timestamp(window["trough"])
    s, m = stock.dropna(), market.dropna()
    if s.empty or s.index[0] > peak + pd.Timedelta(days=7):
        return None
    s_win, m_win = s[(s.index >= peak) & (s.index <= trough)], m[(m.index >= peak) & (m.index <= trough)]
    if len(s_win) < 2 or len(m_win) < 2:
        return None
    start = float(s_win.iloc[0])
    drawdown = float((s_win / s_win.cummax() - 1.0).min())
    after = s[s.index > s_win.index[-1]]
    back = after[after >= start]
    recovery_days = int((after.index < back.index[0]).sum()) + 1 if not back.empty else None
    return {
        "id": window["id"], "name": window["name"],
        "stock_return": float(s_win.iloc[-1]) / start - 1.0,
        "market_return": float(m_win.iloc[-1]) / float(m_win.iloc[0]) - 1.0,
        "max_drawdown": drawdown,
        "recovery_days": recovery_days,
    }


def _naive(series: pd.Series) -> pd.Series:
    """A copy indexed by plain dates (Yahoo's long histories carry a timezone)."""
    out = series.copy()
    idx = pd.to_datetime(out.index)
    # Drop the timezone but keep the local date: converting to UTC first would
    # shift midnight New York time to 4-5 am and push trough days out of range.
    out.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return out


def beta(stock: pd.Series, market: pd.Series, days: int = 504) -> float | None:
    r = pd.concat([stock.pct_change(), market.pct_change()], axis=1, join="inner").dropna().tail(days)
    if len(r) < 60 or r.iloc[:, 1].var() == 0:
        return None
    return float(r.iloc[:, 0].cov(r.iloc[:, 1]) / r.iloc[:, 1].var())


def monthly_beta(stock: pd.Series, market: pd.Series, months: int = 60) -> float | None:
    """Beta from 5 years of monthly returns: the convention published sources use,
    and much steadier than a short daily window (KO's 2-year daily beta read -0.02
    in Oct 2026 while its 5-year monthly beta was 0.29 against Yahoo's 0.32)."""
    sm = stock.resample("ME").last().pct_change()
    mm = market.resample("ME").last().pct_change()
    r = pd.concat([sm, mm], axis=1, join="inner").dropna().tail(months)
    if len(r) < 24 or r.iloc[:, 1].var() == 0:
        return None
    return float(r.iloc[:, 0].cov(r.iloc[:, 1]) / r.iloc[:, 1].var())


def _years(trading_days: int | None) -> str:
    if trading_days is None:
        return "not yet recovered"
    return f"recovered in {trading_days / 252:.1f} years" if trading_days >= 126 else \
        f"recovered in {trading_days} trading days"


def resilience_card(ticker: str) -> ModelCard:
    from backend.analysis import risk_framework as rf_mod

    stock = rf_mod._fetch_full_history(ticker)
    market = rf_mod._fetch_full_history("SPY")
    if stock is None or market is None or stock.empty or market.empty:
        raise RuntimeError("no long price history available")
    s_close, m_close = _naive(stock["Close"]), _naive(market["Close"])

    rows = [r for w in MARKET_DECLINES if (r := decline_stats(s_close, m_close, w))]
    b = monthly_beta(s_close, m_close)
    one_year = s_close.tail(252)
    from_high = float(one_year.iloc[-1] / one_year.max() - 1.0) if len(one_year) else None

    evidence: list[Evidence] = []
    for r in rows:
        evidence.append(Evidence(r["name"], f"{_pct(r['stock_return'])} vs market {_pct(r['market_return'])}",
                                 f"Worst point {_pct(r['max_drawdown'])}; {_years(r['recovery_days'])}",
                                 f"{r['id']}_stock_return", r["stock_return"]))
    evidence += [Evidence("Beta (5 years, monthly)", "n/a" if b is None else f"{b:.2f}",
                          "How much it tends to move when the market moves 1%", "beta_5y_monthly", b),
                 Evidence("From its 1-year high", _pct(from_high), "", "from_1y_high", from_high)]
    inputs: dict[str, Any] = {}
    for r in rows:
        inputs[f"{r['id']}_market_return"] = r["market_return"]
        inputs[f"{r['id']}_max_drawdown"] = r["max_drawdown"]
        inputs[f"{r['id']}_recovery_days"] = r["recovery_days"]

    reasons: list[str] = []
    if rows:
        avg_s = sum(r["stock_return"] for r in rows) / len(rows)
        avg_m = sum(r["market_return"] for r in rows) / len(rows)
        fell_less = sum(r["stock_return"] > r["market_return"] for r in rows)
        evidence += [Evidence("Average in these declines", f"{_pct(avg_s)} vs market {_pct(avg_m)}", "",
                              "avg_decline_stock_return", avg_s)]
        inputs.update({"avg_decline_market_return": avg_m, "declines_lived": len(rows),
                       "declines_fell_less": fell_less})
        headline = (f"In the {len(rows)} big market decline{'s' if len(rows) > 1 else ''} it lived "
                    f"through, it moved {_pct(avg_s, digits=0)} on average, versus "
                    f"{_pct(avg_m, digits=0)} for the S&P 500.")
        reasons.append(f"It fell less than the market in {fell_less} of {len(rows)} declines.")
        unrecovered = [r["name"] for r in rows if r["recovery_days"] is None]
        if unrecovered:
            reasons.append(f"It has still not regained its pre-decline price after: {', '.join(unrecovered)}.")
    else:
        headline = "It wasn't trading during any of the big market declines since 2000, so there's no crash history yet."
    if b is not None and abs(b) < 0.2:
        reasons.append("Over the last 5 years its moves have been almost unrelated to the market's.")
    elif b is not None:
        reasons.append(f"Over the last 5 years it has tended to move about {b:.1f}× as much as the market.")
    return ModelCard(
        model_id="resilience", title="Resilience",
        question="How has it held up when the whole market fell, and how fast did it recover?",
        horizon="A scenario, not a forecast", outlook=None, strength=None, headline=headline,
        evidence=evidence, reasons=reasons,
        caveats=[
            "This describes the past, not the future. Companies change, so a 2008 result may "
            "describe a very different business.",
            "It only covers declines since the stock was listed, and a new kind of crisis can "
            "hit differently.",
        ],
        track_record=TrackRecord("not_a_forecast",
            "Not a forecast, so there's nothing to grade yet. In Phase 7 the Risk Manager will be "
            "graded on whether real drops land inside its predicted ranges."),
        lessons=["max-drawdown", "beta"], deep_dive="risk",
        subject=ticker, model_version=MODEL_VERSIONS["resilience"], as_of=_as_of(ticker),
        inputs=inputs)


# --- Trend: what are the price trends saying? ----------------------------

def trend_strength(composite: float) -> str:
    return _cap_strength("low" if abs(composite) <= 50 else "medium" if abs(composite) <= 75 else "high")


def trend_outlook(score: float | None) -> tuple[str | None, str | None]:
    """The technical score's own thresholds (signals.py): above +25 up, below -25 down."""
    if score is None:
        return None, None
    outlook = "up" if score > 25 else "down" if score < -25 else "flat"
    return outlook, trend_strength(score)


def _trend_track_record() -> TrackRecord:
    live = ""
    try:
        from backend import ledger
        tr = ledger.track_record("trend_twin")
        if tr["calls"]:
            live = (f" Live: this exact rule has {tr['calls']} sealed calls since October 2026 "
                    f"({tr['graded']} graded so far).")
    except Exception:
        pass
    return TrackRecord("tested",
        "Backtested on 6,662 point-in-time observations (200 S&P 500 stocks, Aug 2023 to Aug "
        "2026): the technical signal's information coefficient was +0.022 (t = +0.72), "
        "indistinguishable from luck." + live)


def trend_card(ticker: str) -> ModelCard:
    from backend.analysis import data as data_mod
    from backend.analysis import indicators as ind_mod
    from backend.analysis import signals as signals_mod

    td = data_mod.load(ticker)
    if td is None:
        raise RuntimeError("no price history")
    spy = data_mod.load("SPY")
    df = ind_mod.compute_all(td.history)
    ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
    if ready.empty:
        raise RuntimeError("not enough history for a 200-day average")
    sig = signals_mod.compute(ready, spy.history if spy else None)
    values = [sig.composite, *(f.score for f in sig.factors)]
    if not all(_num(v) is not None for v in values):
        # A recent listing can't fill every factor; showing "nan" or a call
        # built on it would be made up, so this card is unavailable instead.
        raise RuntimeError("the trend score couldn't be computed: a factor lacks enough price history")
    close = td.history["Close"]
    last = ready.iloc[-1]

    def ret(n: int) -> float | None:
        return float(close.iloc[-1] / close.iloc[-n - 1] - 1.0) if len(close) > n else None

    r1, r3, r12 = ret(21), ret(63), ret(252)
    vs_200 = float(last["Close"] / last["SMA200"] - 1.0)
    evidence = [Evidence("Trend score", f"{sig.composite:+.0f} of ±100",
                         "Above +25 reads as up, below -25 as down", "trend_score", sig.composite)]
    evidence += [Evidence(f.name, f"{f.score:+.2f}", f.explanation, f"factor_{_slug(f.name)}", f.score)
                 for f in sig.factors]
    evidence += [
        Evidence("Return, 1 month", _pct(r1, digits=0), "", "return_1m", r1),
        Evidence("Return, 3 months", _pct(r3, digits=0), "", "return_3m", r3),
        Evidence("Return, 12 months", _pct(r12, digits=0), "", "return_12m", r12),
        Evidence("Price vs 200-day average", _pct(vs_200), "", "price_vs_sma200", vs_200),
    ]
    card = ModelCard(
        model_id="trend", title="Trend",
        question="What are price trends and momentum saying?",
        horizon="About 1 month", outlook=None, strength=None, headline="",
        evidence=evidence,
        caveats=[
            "Every input comes from the same past prices, so its factors aren't independent confirmations.",
            "Trends reverse at turning points, and momentum strategies crash in sharp rebounds.",
            "Its own backtest found no edge (see the track record).",
        ],
        track_record=_trend_track_record(),
        lessons=["technical-indicators", "momentum-vs-meanreversion", "relative-strength"],
        deep_dive="quant", subject=ticker, model_version=MODEL_VERSIONS["trend"],
        as_of=td.history.index[-1].date().isoformat(), inputs={"signals_action": sig.action})
    _finish(card, [f"{f.name}: {'supports up' if f.score > 0.15 else 'supports down' if f.score < -0.15 else 'neutral'}."
                   for f in sig.factors])
    card.headline = {
        "up": "Price trends point up: the stock is rising and stronger than the market.",
        "down": "Price trends point down: the stock is falling or weaker than the market.",
        "flat": "No clear trend: the price signals are mixed or weak.",
    }[card.outlook]
    return card


# --- News: what is the news saying? ---------------------------------------

_NAME_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
                          r"holdings?|group|n\.?v|s\.?a|the)\.?$", re.IGNORECASE)
# First words too generic to identify a company on their own.
_GENERIC_FIRST_WORDS = {"general", "american", "united", "first", "international", "national",
                        "global", "bank", "royal", "west", "east", "north", "south", "new"}


def company_keywords(ticker: str, name: str) -> list[str]:
    """Words that mark a headline as about this company: its core name (and a
    distinctive first word of it). The ticker itself is matched separately."""
    core = (name or "").strip()
    while True:
        shorter = _NAME_SUFFIX.sub("", core).strip()
        if shorter == core:
            break
        core = shorter
    if core.lower().startswith("the "):
        core = core[4:]
    keys = []
    if len(core) >= 3:
        keys.append(core)
    first = core.split()[0].strip(",.") if core else ""
    if len(first) >= 4 and first.lower() not in _GENERIC_FIRST_WORDS and first != core:
        keys.append(first)
    return keys


def relevant_headlines(headlines: list, ticker: str, name: str) -> list:
    """Only headlines that name the company or its ticker. Yahoo's per-stock feed
    mixes in stories about other companies (a Marvell story under MSFT)."""
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in company_keywords(ticker, name)]
    patterns.append(re.compile(rf"\b{re.escape(ticker.upper())}\b"))   # tickers: exact case
    return [h for h in headlines if any(p.search(h.title) for p in patterns)]


def news_outlook(score: float | None, headline_count: int) -> tuple[str | None, str | None]:
    """Headline mood from -100 to +100. Too few headlines means no outlook."""
    if score is None or headline_count < MIN_HEADLINES:
        return None, None
    outlook = "up" if score >= 25 else "down" if score <= -25 else "flat"
    return outlook, "low"   # untested: strength stays low


def news_card(ticker: str) -> ModelCard:
    from backend.analysis import catalyst as cat_mod
    from backend.analysis import data as data_mod
    from backend.analysis import sentiment as sent_mod

    td = data_mod.load(ticker)
    close = td.history["Close"] if td is not None else None
    s = sent_mod.compute(ticker, close)
    try:
        cat = cat_mod.compute(ticker)
    except Exception:
        cat = None
    name = _fundamentals(ticker).get("shortName") or ""
    relevant = relevant_headlines(s.headlines, ticker, name) if s.method != "unavailable" else []
    mood = float(sent_mod._aggregate(relevant)[0]) if relevant else None
    ret20 = _num(s.price_return_20d) if close is not None and len(close) > 21 else None
    alignment = sent_mod._alignment(mood, ret20) if mood is not None else "n/a"
    earn = cat.earnings if cat else None
    days_to_earnings = earn.get("days_until") if earn else None

    evidence = [
        Evidence("Headline mood", "n/a" if mood is None else f"{mood:+.0f} of ±100",
                 "Time-weighted over headlines about this company; newer ones count more",
                 "mood_score", mood),
        Evidence("Headlines about the company", f"{len(relevant)} of {s.headline_count}",
                 "The others mentioned different companies", "headlines_relevant", len(relevant)),
    ]
    if alignment != "n/a":
        evidence.append(Evidence("Mood vs last 20 days of price", alignment,
                                 f"Price moved {_pct(ret20)}", "price_return_20d", ret20))
    if earn and earn.get("next_date"):
        evidence.append(Evidence("Next earnings", str(earn["next_date"])[:10],
                                 "" if days_to_earnings is None else f"in {days_to_earnings} days",
                                 "days_to_earnings", days_to_earnings))
    for h in relevant[:3]:
        evidence.append(Evidence(f"Headline ({h.label})", h.title, h.publisher))

    card = ModelCard(
        model_id="news", title="News",
        question="What is the news saying, and what's coming up?",
        horizon="About 1 month", outlook=None, strength=None, headline="",
        evidence=evidence,
        caveats=[
            "The mood score (VADER) was built for social media, not finance, and misreads "
            "financial language.",
            "Headlines measure attention and tone, not facts, and prices often react before the story is written.",
            "A headline counts only if it names the company or its ticker, which can miss stories "
            "that use a brand or product name instead.",
        ],
        track_record=TrackRecord("untested",
            "Never tested. Old headlines can't be downloaded later, so the archive that makes a "
            "test possible only began in September 2026. Its weekly calls are sealed in the "
            "ledger from October 2026."),
        lessons=["vader"], deep_dive="sentiment", subject=ticker,
        model_version=MODEL_VERSIONS["news"],
        as_of=td.history.index[-1].date().isoformat() if td is not None else None,
        inputs={"alignment": alignment, "headlines_total": s.headline_count,
                "next_earnings_date": str(earn["next_date"])[:10] if earn and earn.get("next_date") else None,
                "headline_titles": [h.title for h in relevant[:10]]})
    extra: list[str] = []
    if mood is None or len(relevant) < MIN_HEADLINES:
        extra.append(f"Only {len(relevant)} recent headline(s) name the company; at least "
                     f"{MIN_HEADLINES} are needed for an outlook.")
    else:
        extra.append(f"The time-weighted mood of {len(relevant)} headlines about the company is {mood:+.0f}.")
        if alignment in ("aligned", "conflicted"):
            extra.append(f"The mood is {alignment} with the last 20 days of price moves.")
    if days_to_earnings is not None and 0 <= days_to_earnings <= 30:
        extra.append(f"Earnings in {days_to_earnings} days could move the stock either way.")
    _finish(card, extra)
    card.headline = {"up": "Recent news about the company is mostly positive.",
                     "down": "Recent news about the company is mostly negative.",
                     "flat": "Recent news about the company is mixed or neutral.",
                     None: "Too few recent headlines about the company to read the mood."}[card.outlook]
    return card


# --- Re-checking any card from its packet -----------------------------------

def outlook_from_packet(packet: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
    """Recompute (outlook, strength, rule reasons) from an evidence packet alone.
    Every card's outlook is set through this, so a sealed call can be re-checked."""
    f, i, model = packet.get("fields", {}), packet.get("inputs", {}), packet.get("model_id")
    if model == "business":
        return business_outlook(f.get("dcf_upside"), bool(i.get("dcf_reliable")),
                                bool(i.get("dcf_applicable")), i.get("peer_label"),
                                f.get("revenue_growth"), f.get("operating_margin"))
    if model == "trend":
        return (*trend_outlook(f.get("trend_score")), [])
    if model == "news":
        return (*news_outlook(f.get("mood_score"), f.get("headlines_relevant") or 0), [])
    return None, None, []


# --- The board -------------------------------------------------------------

BUILDERS: dict[str, Callable[[str], ModelCard]] = {
    "business": business_card,
    "resilience": resilience_card,
    "trend": trend_card,
    "news": news_card,
}
_TITLES = {"business": "Business", "resilience": "Resilience", "trend": "Trend", "news": "News"}


def safe_card(model_id: str, ticker: str) -> ModelCard:
    """A card never takes the board down: failures become an "unavailable" card."""
    t = ticker.upper().strip()
    try:
        return BUILDERS[model_id](t)
    except Exception as exc:
        return ModelCard(model_id=model_id, title=_TITLES.get(model_id, model_id), question="",
                         horizon="", outlook=None, strength=None,
                         headline="This model is unavailable for this stock right now.",
                         error=f"{type(exc).__name__}: {exc}", subject=t,
                         model_version=MODEL_VERSIONS.get(model_id, ""))


def board_summary(cards: list[ModelCard]) -> dict[str, Any]:
    """Count the outlooks. Agreement among untested models proves nothing, and
    the summary says so."""
    with_view = [c for c in cards if c.outlook in OUTLOOKS and not c.error]
    counts = {o: sum(c.outlook == o for c in with_view) for o in OUTLOOKS}
    n = len(with_view)
    if n == 0:
        text = "None of the models gives an outlook for this stock right now."
    elif max(counts.values()) == n and n > 1:
        text = (f"All {n} models that give an outlook lean {with_view[0].outlook}. Agreement "
                f"among models with no proven edge is not proof, so check each track record.")
    else:
        parts = [f"{counts[o]} {o}" for o in OUTLOOKS if counts[o]]
        if n == 1:
            text = (f"Only 1 model gives an outlook ({parts[0]}). The others have no reliable "
                    f"reading for this stock right now.")
        else:
            text = (f"Of {n} models that give an outlook: {', '.join(parts)}. They look at "
                    f"different evidence over different time spans, so disagreement is normal. "
                    f"Read each card's reasons.")
    return {"counts": counts, "with_outlook": n, "text": text}


# --- Sealing the rule models' calls -----------------------------------------

def record_model_calls(model_id: str, tickers: list[str],
                       build: Callable[[str], ModelCard] | None = None,
                       max_stale_days: int = 4) -> dict[str, Any]:
    """Seal one call per ticker per week for a rule model, with its packet, so it
    builds a track record like an agent. Re-running in the same week only fills gaps."""
    from backend import ledger

    horizon = RECORDED_HORIZONS[model_id]
    make = build or (lambda t: safe_card(model_id, t))
    agent_id = f"{model_id}_model"
    today = ledger._today()
    names = sorted({t.strip().upper() for t in tickers if t.strip()})
    pool_id = ledger.record_pool(f"{agent_id} tracking list", today, names)
    done = ledger.called_this_week(agent_id)
    summary: dict[str, Any] = {"recorded": 0, "already_done": 0, "skipped": []}
    for t in names:
        if t in done:
            summary["already_done"] += 1
            continue
        card = make(t)
        if card.error:
            summary["skipped"].append({"ticker": t, "reason": f"unavailable ({card.error})"})
            continue
        if card.outlook is None:
            summary["skipped"].append({"ticker": t, "reason": f"no outlook: {card.headline}"})
            continue
        if not card.as_of or (today - date.fromisoformat(card.as_of)).days > max_stale_days:
            summary["skipped"].append({"ticker": t, "reason": f"data is stale (as of {card.as_of})"})
            continue
        ledger.record_call(
            agent_id=agent_id, charter_version=card.model_version, model_id="rules",
            subject=t, as_of=card.as_of, horizon_days=horizon,
            output={"stance": OUTLOOK_TO_STANCE[card.outlook], "outlook": card.outlook,
                    "strength": card.strength, "headline": card.headline, "p_beat_market": None},
            packet=card.packet(), source_tag="tracking-list", pool_id=pool_id)
        summary["recorded"] += 1
    return summary
