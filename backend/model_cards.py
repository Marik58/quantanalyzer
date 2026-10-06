"""Model cards: one shape for every model's reading of a stock (Roadmap Phase 2).

Each model answers one question through one lens. A card holds:
- the outlook and the horizon it applies to
- how strongly the evidence points
- the evidence itself (every number computed here, in code)
- plain reasons, and what the model is bad at
- its track record so far, and the lesson that explains it

The outlook rules are deliberately simple and visible, so a learner can check
each one against the evidence on the same card. Strength can never be "high"
until a model's track record passes the bar in docs/AGENT_CHARTERS.md §14, and
no model passes it yet. These cards are also what the AI agents will read in
Phase 4.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import pandas as pd

from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
OUTLOOKS = ("up", "flat", "down")
STRENGTHS = ("low", "medium", "high")
_ACTION_TO_OUTLOOK = {"BUY": "up", "HOLD": "flat", "SELL": "down"}

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
    value: str
    detail: str = ""


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


# --- Business: is this a healthy company at a sensible price? -------------

def business_outlook(dcf_upside: float | None, dcf_reliable: bool, peer_label: str | None,
                     revenue_growth: float | None,
                     operating_margin: float | None) -> tuple[str | None, str | None, list[str]]:
    """Two valuation lenses vote cheap (+1), fair (0) or expensive (-1);
    business health can block an "up". Returns (outlook, strength, reasons)."""
    votes: list[int] = []
    reasons: list[str] = []
    if dcf_upside is not None and dcf_reliable:
        if dcf_upside > 0.15:
            votes.append(1)
            reasons.append(f"The cash-flow model (DCF) puts fair value {_pct(dcf_upside)} from the price: cheap.")
        elif dcf_upside < -0.15:
            votes.append(-1)
            reasons.append(f"The cash-flow model (DCF) puts fair value {_pct(dcf_upside)} from the price: expensive.")
        else:
            votes.append(0)
            reasons.append("The cash-flow model (DCF) says the price is about fair (within ±15%).")
    elif dcf_upside is not None:
        reasons.append("The cash-flow model is unreliable here (negative or erratic cash flow), so it isn't counted.")
    if dcf_upside is not None and dcf_reliable and (dcf_upside < -0.5 or dcf_upside > 1.0):
        reasons.append("A gap this large usually means the cash-flow model's fixed assumptions don't fit "
                       "this company, not that the price is that far off. Treat it as a warning about the "
                       "model, and see the Valuation tab's sensitivity table.")

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
        reasons.append("There isn't enough valuation data for an outlook.")
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
                     "debtToEquity", "returnOnEquity")


@cached(ttl_seconds=CACHE_TTL * 4, key_fn=lambda t: f"card_fundamentals:{t}")
def _fundamentals(ticker: str) -> dict[str, Any]:
    """Growth, margins and debt from Yahoo's company summary. (data.load keeps
    only a few summary fields, and these aren't among them.)"""
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

    dcf_upside = _num(dcf.weighted_upside_pct)
    reliable = bool(dcf.history and dcf.history.reliability not in ("negative", "volatile"))
    peer_label = pc.relative_value_label if pc else None
    growth = _num(info.get("revenueGrowth"))
    op_margin = _num(info.get("operatingMargins"))
    outlook, strength, reasons = business_outlook(dcf_upside, reliable, peer_label, growth, op_margin)

    headline = {
        "up": "The business looks healthy, and the price looks low against its cash flows or its peers.",
        "down": "The price looks high against its cash flows and peers, or the business is weakening.",
        "flat": "No clear signal: the valuation lenses disagree, or both say the price is about fair.",
        None: "Not enough financial data to judge the business and its price.",
    }[outlook]
    de = _num(info.get("debtToEquity"))
    evidence = [
        Evidence("Revenue growth", _pct(growth), "Latest year over year, from Yahoo's company summary"),
        Evidence("Gross margin", _pct(_num(info.get("grossMargins")), signed=False)),
        Evidence("Operating margin", _pct(op_margin, signed=False), "Profit from the core business per $1 of sales"),
        Evidence("Debt to equity", "n/a" if de is None else f"{de / 100:.2f}×"),
        Evidence("DCF fair value vs price",
                 "n/a" if dcf.weighted_intrinsic is None else
                 f"${dcf.weighted_intrinsic:,.2f} vs ${dcf.current_price:,.2f} ({_pct(dcf_upside)})",
                 "Probability-weighted across bear, base and bull cases"),
        Evidence("Relative value vs peers",
                 "n/a" if not pc or pc.relative_value_score is None else
                 f"{pc.relative_value_score:.0f}/100 ({pc.relative_value_label})",
                 f"Peers: {', '.join(pc.peers_used)}" if pc and pc.peers_used else ""),
    ]
    return ModelCard(
        model_id="business", title="Business",
        question="Is this a healthy, growing company at a sensible price?",
        horizon="1 year or more", outlook=outlook, strength=strength, headline=headline,
        evidence=evidence, reasons=reasons,
        caveats=[
            "DCF fair values swing a lot with small changes in growth and discount-rate "
            "assumptions, and fixed assumptions tend to call fast growers overvalued.",
            "It uses today's financial snapshot, so it can't see what changed since the last report.",
            "Peer comparisons depend on who counts as a peer.",
        ],
        track_record=TrackRecord("untested",
            "Never tested. A fair test needs financial statements as they were known at the "
            "time, which arrive with SEC filings in Roadmap Phase 3."),
        lessons=["dcf", "multiples", "relative-value-score"], deep_dive="valuation")


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
    b = beta(s_close, m_close)
    one_year = s_close.tail(252)
    from_high = float(one_year.iloc[-1] / one_year.max() - 1.0) if len(one_year) else None

    evidence = [Evidence(r["name"], f"{_pct(r['stock_return'])} vs market {_pct(r['market_return'])}",
                         f"Worst point {_pct(r['max_drawdown'])}; {_years(r['recovery_days'])}")
                for r in rows]
    evidence += [Evidence("Beta (2 years)", "n/a" if b is None else f"{b:.2f}",
                          "How much it tends to move when the market moves 1%"),
                 Evidence("From its 1-year high", _pct(from_high))]
    reasons: list[str] = []
    if rows:
        avg_s = sum(r["stock_return"] for r in rows) / len(rows)
        avg_m = sum(r["market_return"] for r in rows) / len(rows)
        fell_less = sum(r["stock_return"] > r["market_return"] for r in rows)
        headline = (f"In the {len(rows)} big market decline{'s' if len(rows) > 1 else ''} it lived "
                    f"through, it moved {_pct(avg_s, digits=0)} on average, versus "
                    f"{_pct(avg_m, digits=0)} for the S&P 500.")
        reasons.append(f"It fell less than the market in {fell_less} of {len(rows)} declines.")
        unrecovered = [r["name"] for r in rows if r["recovery_days"] is None]
        if unrecovered:
            reasons.append(f"It has still not regained its pre-decline price after: {', '.join(unrecovered)}.")
    else:
        headline = "It wasn't trading during any of the big market declines since 2000, so there's no crash history yet."
    if b is not None:
        reasons.append(f"On a typical day it moves about {b:.1f}× as much as the market.")
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
        lessons=["max-drawdown", "beta"], deep_dive="risk")


# --- Trend: what are the price trends saying? ----------------------------

def trend_strength(composite: float) -> str:
    return _cap_strength("low" if abs(composite) <= 50 else "medium" if abs(composite) <= 75 else "high")


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
    outlook = _ACTION_TO_OUTLOOK.get(sig.action, "flat")
    close = td.history["Close"]
    last = ready.iloc[-1]

    def ret(n: int) -> float | None:
        return float(close.iloc[-1] / close.iloc[-n - 1] - 1.0) if len(close) > n else None

    evidence = [Evidence("Trend score", f"{sig.composite:+.0f} of ±100",
                         "Above +25 reads as up, below -25 as down")]
    evidence += [Evidence(f.name, f"{f.score:+.2f}", f.explanation) for f in sig.factors]
    evidence += [
        Evidence("Return, 1 / 3 / 12 months", f"{_pct(ret(21), digits=0)} / {_pct(ret(63), digits=0)} / {_pct(ret(252), digits=0)}"),
        Evidence("Price vs 200-day average", _pct(float(last["Close"] / last["SMA200"] - 1.0))),
    ]
    headline = {
        "up": "Price trends point up: the stock is rising and stronger than the market.",
        "down": "Price trends point down: the stock is falling or weaker than the market.",
        "flat": "No clear trend: the price signals are mixed or weak.",
    }[outlook]
    reasons = [f"{f.name}: {'supports up' if f.score > 0.15 else 'supports down' if f.score < -0.15 else 'neutral'}."
               for f in sig.factors]
    return ModelCard(
        model_id="trend", title="Trend",
        question="What are price trends and momentum saying?",
        horizon="About 1 month", outlook=outlook, strength=trend_strength(sig.composite),
        headline=headline, evidence=evidence, reasons=reasons,
        caveats=[
            "Every input comes from the same past prices, so its factors aren't independent confirmations.",
            "Trends reverse at turning points, and momentum strategies crash in sharp rebounds.",
            "Its own backtest found no edge (see the track record).",
        ],
        track_record=_trend_track_record(),
        lessons=["technical-indicators", "momentum-vs-meanreversion", "relative-strength"],
        deep_dive="quant")


# --- News: what is the news saying? ---------------------------------------

def news_outlook(score: float | None, headline_count: int) -> tuple[str | None, str | None]:
    """Headline mood from -100 to +100. Too few headlines means no outlook."""
    if score is None or headline_count < 5:
        return None, None
    outlook = "up" if score >= 25 else "down" if score <= -25 else "flat"
    return outlook, "low"   # untested: strength stays low


def news_card(ticker: str) -> ModelCard:
    from backend.analysis import catalyst as cat_mod
    from backend.analysis import data as data_mod
    from backend.analysis import sentiment as sent_mod

    td = data_mod.load(ticker)
    s = sent_mod.compute(ticker, td.history["Close"] if td else None)
    try:
        cat = cat_mod.compute(ticker)
    except Exception:
        cat = None
    score = _num(s.overall_score) if s.method != "unavailable" else None
    outlook, strength = news_outlook(score, s.headline_count)

    evidence = [
        Evidence("Headline mood", "n/a" if score is None else f"{score:+.0f} of ±100 ({s.overall_label})",
                 "Time-weighted, newer headlines count more"),
        Evidence("Headlines read", str(s.headline_count)),
    ]
    if s.alignment_with_price in ("aligned", "conflicted", "neutral"):
        evidence.append(Evidence("Mood vs last 20 days of price", s.alignment_with_price,
                                 f"Price moved {_pct(_num(s.price_return_20d))}"))
    earn = cat.earnings if cat else None
    if earn and earn.get("next_date"):
        days = earn.get("days_until")
        evidence.append(Evidence("Next earnings", str(earn["next_date"])[:10],
                                 "" if days is None else f"in {days} days"))
    for h in s.headlines[:3]:
        evidence.append(Evidence(f"Headline ({h.label})", h.title, h.publisher))

    reasons: list[str] = []
    if outlook is None:
        headline = "Too few recent headlines to read the mood."
        reasons.append(f"Only {s.headline_count} headline(s) found; at least 5 are needed.")
    else:
        headline = {"up": "Recent news is mostly positive.",
                    "down": "Recent news is mostly negative.",
                    "flat": "Recent news is mixed or neutral."}[outlook]
        reasons.append(f"The time-weighted mood of {s.headline_count} headlines is {score:+.0f}.")
        if s.alignment_with_price in ("aligned", "conflicted"):
            reasons.append(f"The mood is {s.alignment_with_price} with the last 20 days of price moves.")
    if earn and earn.get("days_until") is not None and 0 <= earn["days_until"] <= 30:
        reasons.append(f"Earnings in {earn['days_until']} days could move the stock either way.")
    return ModelCard(
        model_id="news", title="News",
        question="What is the news saying, and what's coming up?",
        horizon="About 1 month", outlook=outlook, strength=strength, headline=headline,
        evidence=evidence, reasons=reasons,
        caveats=[
            "The mood score (VADER) was built for social media, not finance, and misreads "
            "financial language.",
            "Headlines measure attention and tone, not facts, and prices often react before the story is written.",
        ],
        track_record=TrackRecord("untested",
            "Never tested. Old headlines can't be downloaded later, so the archive that makes a "
            "test possible only began in September 2026. A fair test needs about a year of it."),
        lessons=["vader"], deep_dive="sentiment")


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
    try:
        return BUILDERS[model_id](ticker.upper().strip())
    except Exception as exc:
        return ModelCard(model_id=model_id, title=_TITLES.get(model_id, model_id), question="",
                         horizon="", outlook=None, strength=None,
                         headline="This model is unavailable for this stock right now.",
                         error=f"{type(exc).__name__}: {exc}")


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
        text = (f"Of {n} models that give an outlook: {', '.join(parts)}. They look at "
                f"different evidence over different time spans, so disagreement is normal. "
                f"Read each card's reasons.")
    return {"counts": counts, "with_outlook": n, "text": text}
