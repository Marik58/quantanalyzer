"""News sentiment — yfinance headlines scored with VADER, then time-weighted.

Pipeline:
  1. Pull up to 20 recent news items via yfinance. Handle BOTH the legacy flat
     format and the newer nested {"content": {...}} format silently.
  2. Score each headline (title, optionally + summary) with VADER. VADER's
     compound score is in [-1, +1]; classify as positive / negative / neutral
     using standard ±0.05 thresholds.
  3. Aggregate into an overall sentiment score in [-100, +100], time-weighted
     with a 48-hour half-life so fresh news dominates stale news.
  4. Build a per-day trend over the last 30 days for frontend charting.
  5. Cross-check against the 20-day price return. If the tape and news disagree,
     explicitly flag "conflicted" — that's the interesting case for a PM.

Design notes:
  * No paid API. VADER is pure Python (no model download).
  * If yfinance returns nothing or VADER is missing, return an empty result with
    a clear error; the frontend renders an empty state rather than crashing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

_VADER_ERROR: str | None = None
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _HAS_VADER = True
    _analyzer = SentimentIntensityAnalyzer()
except Exception as _exc:
    _HAS_VADER = False
    _VADER_ERROR = f"{type(_exc).__name__}: {_exc}"
    _analyzer = None  # type: ignore


POS_THRESHOLD = 0.05
NEG_THRESHOLD = -0.05
HALF_LIFE_HOURS = 48.0      # news older than this counts half as much


@dataclass
class Headline:
    title: str
    publisher: str
    link: str
    published_ts: int         # unix seconds, UTC
    published_iso: str        # human-readable UTC
    compound: float           # VADER compound score in [-1, 1]
    label: str                # "positive" | "negative" | "neutral"
    age_hours: float


@dataclass
class DailyTrend:
    date: str
    avg_sentiment: float      # -1..+1
    headline_count: int


@dataclass
class SentimentAnalysis:
    ticker: str
    overall_score: float      # -100..+100 (time-weighted)
    overall_label: str        # "bullish" | "bearish" | "neutral"
    headline_count: int
    headlines: list[Headline]
    trend: list[DailyTrend]
    alignment_with_price: str # "aligned" | "conflicted" | "neutral" | "n/a"
    price_return_20d: float   # the tape half of the comparison
    method: str               # "vader" | "unavailable"
    error: str | None
    explanations: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# yfinance news extraction (handles legacy AND current formats)
# --------------------------------------------------------------------------- #

def _fetch_raw_news(ticker: str, limit: int = 20) -> list[dict]:
    # Reuse the project's Chrome-impersonating session when available.
    session = None
    try:
        from backend.analysis.data import _SESSION as _s
        session = _s
    except Exception:
        session = None
    try:
        t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        news = t.news or []
    except Exception:
        news = []
    return news[:limit]


def _normalize(item: dict) -> dict | None:
    """Return a flat {title, summary, publisher, link, ts} dict, or None on failure."""
    # --- Newer nested format: item["content"] holds the real fields ---
    if isinstance(item.get("content"), dict):
        c = item["content"]
        title = c.get("title") or ""
        summary = c.get("description") or c.get("summary") or ""
        provider = c.get("provider")
        if isinstance(provider, dict):
            publisher = provider.get("displayName") or ""
        else:
            publisher = str(provider or "")
        click = c.get("clickThroughUrl") or c.get("canonicalUrl") or {}
        link = click.get("url", "") if isinstance(click, dict) else str(click)
        pub = c.get("pubDate") or c.get("displayTime")
        ts = _parse_ts(pub)
    else:
        # --- Legacy flat format ---
        title = item.get("title") or ""
        summary = item.get("summary") or ""
        publisher = item.get("publisher") or ""
        link = item.get("link") or ""
        ts = item.get("providerPublishTime")
        if ts is None:
            ts = int(time.time())
        ts = int(ts)

    if not title:
        return None
    return {
        "title": title.strip(),
        "summary": summary.strip() if isinstance(summary, str) else "",
        "publisher": publisher.strip() if isinstance(publisher, str) else "",
        "link": link,
        "ts": int(ts),
    }


def _parse_ts(raw) -> int:
    """Best-effort conversion of a yfinance pubDate value to unix seconds."""
    if raw is None:
        return int(time.time())
    try:
        return int(pd.Timestamp(raw).timestamp())
    except Exception:
        try:
            return int(raw)
        except Exception:
            return int(time.time())


# --------------------------------------------------------------------------- #
# scoring + aggregation
# --------------------------------------------------------------------------- #

def _score_one(text: str) -> float:
    if not text or _analyzer is None:
        return 0.0
    return float(_analyzer.polarity_scores(text)["compound"])


def _score_headlines(normalized: list[dict]) -> list[Headline]:
    now = time.time()
    out: list[Headline] = []
    for item in normalized:
        text = item["title"]
        if item["summary"]:
            text += ". " + item["summary"]
        compound = _score_one(text)
        if compound >= POS_THRESHOLD:
            label = "positive"
        elif compound <= NEG_THRESHOLD:
            label = "negative"
        else:
            label = "neutral"
        age_hours = max(0.0, (now - item["ts"]) / 3600.0)
        iso = datetime.fromtimestamp(item["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        out.append(Headline(
            title=item["title"], publisher=item["publisher"],
            link=item["link"],
            published_ts=item["ts"], published_iso=iso,
            compound=compound, label=label, age_hours=age_hours,
        ))
    return out


def _aggregate(headlines: list[Headline]) -> tuple[float, str]:
    if not headlines:
        return 0.0, "neutral"
    weights = np.array([2.0 ** (-h.age_hours / HALF_LIFE_HOURS) for h in headlines])
    if weights.sum() == 0:
        return 0.0, "neutral"
    scores = np.array([h.compound for h in headlines])
    weighted = float(np.sum(weights * scores) / weights.sum())     # [-1, +1]
    overall = weighted * 100.0
    if weighted >= POS_THRESHOLD:
        label = "bullish"
    elif weighted <= NEG_THRESHOLD:
        label = "bearish"
    else:
        label = "neutral"
    return overall, label


def _daily_trend(headlines: list[Headline]) -> list[DailyTrend]:
    if not headlines:
        return []
    df = pd.DataFrame({
        "date": [datetime.fromtimestamp(h.published_ts, tz=timezone.utc).date()
                 for h in headlines],
        "compound": [h.compound for h in headlines],
    })
    df["date"] = pd.to_datetime(df["date"])    # tz-naive
    cutoff = pd.Timestamp(datetime.now(timezone.utc).date()) - pd.Timedelta(days=30)
    df = df[df["date"] >= cutoff]
    if df.empty:
        return []
    grouped = df.groupby("date")["compound"].agg(["mean", "count"]).sort_index()
    return [
        DailyTrend(
            date=idx.strftime("%Y-%m-%d"),
            avg_sentiment=float(row["mean"]),
            headline_count=int(row["count"]),
        )
        for idx, row in grouped.iterrows()
    ]


# --------------------------------------------------------------------------- #
# price alignment
# --------------------------------------------------------------------------- #

def _alignment(overall_score: float, ret_20d: float | None) -> str:
    if ret_20d is None:
        return "n/a"
    tape_up   = ret_20d > 0.02
    tape_down = ret_20d < -0.02
    news_bull = overall_score > 5.0
    news_bear = overall_score < -5.0
    if (tape_up and news_bull) or (tape_down and news_bear):
        return "aligned"
    if (tape_up and news_bear) or (tape_down and news_bull):
        return "conflicted"
    return "neutral"


# --------------------------------------------------------------------------- #
# narrative
# --------------------------------------------------------------------------- #

def _explain(score: float, label: str, headlines: list[Headline],
             trend: list[DailyTrend], alignment: str,
             ret_20d: float | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not headlines:
        out["overview"] = (
            "No recent headlines returned for this ticker. Either yfinance has nothing "
            "for this name right now, or the feed is temporarily empty — the sentiment "
            "signal is unavailable and should not weigh on the decision."
        )
        return out

    out["overview"] = (
        f"Aggregated {len(headlines)} recent headlines. Time-weighted sentiment score is "
        f"{score:+.1f} on the [-100, +100] scale — classified as {label}. Recent news "
        "is weighted more heavily than older news (48-hour half-life)."
    )

    pos = sum(1 for h in headlines if h.label == "positive")
    neg = sum(1 for h in headlines if h.label == "negative")
    neu = sum(1 for h in headlines if h.label == "neutral")
    if pos > neg * 1.5:
        tone = "Mostly constructive coverage."
    elif neg > pos * 1.5:
        tone = "Mostly skeptical / critical coverage."
    else:
        tone = "Balanced coverage — no clear one-way narrative."
    out["mix"] = f"Headline mix: {pos} positive, {neg} negative, {neu} neutral. {tone}"

    if trend and len(trend) >= 2:
        week_ago = pd.Timestamp.now().normalize() - pd.Timedelta(days=7)
        recent = [t.avg_sentiment for t in trend if pd.Timestamp(t.date) >= week_ago]
        older  = [t.avg_sentiment for t in trend if pd.Timestamp(t.date) <  week_ago]
        if recent and older:
            rec_avg = float(np.mean(recent))
            old_avg = float(np.mean(older))
            if rec_avg > old_avg + 0.1:
                out["trend"] = ("Sentiment is improving over the last week vs. the "
                                "prior period — narrative is turning constructive.")
            elif rec_avg < old_avg - 0.1:
                out["trend"] = ("Sentiment is deteriorating over the last week vs. the "
                                "prior period — narrative is turning skeptical.")
            else:
                out["trend"] = "Sentiment is flat across the 30-day window."

    if alignment == "aligned":
        out["alignment"] = (
            f"Sentiment aligns with the tape (20-day return {ret_20d:+.1%} vs. sentiment "
            f"{score:+.1f}). News flow and price are telling the same story — no "
            "contradictory evidence."
        )
    elif alignment == "conflicted":
        out["alignment"] = (
            f"Sentiment conflicts with the tape (20-day return {ret_20d:+.1%} vs. "
            f"sentiment {score:+.1f}). When news and price disagree one of them is "
            "typically early: either news is leading a turn the tape has not priced, or "
            "the tape is ignoring headlines it will eventually have to price. This is "
            "the situation worth investigating — dig into specific headlines."
        )
    elif alignment == "neutral":
        out["alignment"] = (
            f"Sentiment is roughly neutral relative to the tape "
            f"(20-day return {ret_20d:+.1%}) — no strong alignment signal either way."
        )
    else:
        out["alignment"] = "Price alignment check skipped (no price series supplied)."

    out["caveat"] = (
        "VADER is rule-based and tuned for social / news-style short text. It handles "
        "clear bullish/bearish language well but misses some equity-research nuance — "
        "e.g. 'beat estimates' does not score as strongly as it deserves. Treat this as "
        "one input, not a standalone verdict."
    )
    return out


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #

def compute(ticker: str, close: pd.Series | None = None) -> SentimentAnalysis:
    if not _HAS_VADER:
        return SentimentAnalysis(
            ticker=ticker, overall_score=0.0, overall_label="neutral",
            headline_count=0, headlines=[], trend=[],
            alignment_with_price="n/a", price_return_20d=0.0,
            method="unavailable", error=_VADER_ERROR,
            explanations={"overview": f"VADER unavailable: {_VADER_ERROR}"},
        )
    raw = _fetch_raw_news(ticker)
    normalized = [n for n in (_normalize(i) for i in raw) if n is not None]
    headlines = _score_headlines(normalized)
    score, label = _aggregate(headlines)
    trend = _daily_trend(headlines)

    ret_20d: float | None = None
    if close is not None and len(close) >= 21:
        ret_20d = float(close.iloc[-1] / close.iloc[-21] - 1)
    alignment = _alignment(score, ret_20d)

    explanations = _explain(score, label, headlines, trend, alignment, ret_20d)

    return SentimentAnalysis(
        ticker=ticker,
        overall_score=score, overall_label=label,
        headline_count=len(headlines),
        headlines=headlines, trend=trend,
        alignment_with_price=alignment,
        price_return_20d=ret_20d if ret_20d is not None else 0.0,
        method="vader", error=None,
        explanations=explanations,
    )


def to_dict(s: SentimentAnalysis) -> dict[str, Any]:
    return {
        "ticker": s.ticker,
        "method": s.method,
        "error": s.error,
        "overall_score": s.overall_score,
        "overall_label": s.overall_label,
        "headline_count": s.headline_count,
        "alignment_with_price": s.alignment_with_price,
        "price_return_20d": s.price_return_20d,
        "headlines": [asdict(h) for h in s.headlines],
        "trend": [asdict(t) for t in s.trend],
        "explanations": s.explanations,
    }
