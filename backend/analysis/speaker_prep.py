"""Speaker prep / Q&A pack — 5 sharp questions for the name.

Reads the thesis output (which already gathered quant_score, valuation,
sentiment, regime, catalyst, peers) and surfaces the five highest-uncertainty
areas as questions you would ask company management or that a PM would press
you on in a Q&A.

Method:
  1. Run the thesis (cached) to get the structured view of the name.
  2. Score a library of "uncertainty triggers" against the thesis data.
     Each trigger that fires generates one templated question + rationale.
  3. Sort by trigger severity, take the top 5.
  4. If fewer than 5 specific triggers fire, top up with generic-but-strong
     fallback questions so the output is always exactly 5.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from backend.analysis import thesis as thesis_mod
from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))


@dataclass
class SpeakerPrep:
    ticker: str
    questions: list[dict[str, str]] = field(default_factory=list)
    triggers_fired: list[str] = field(default_factory=list)
    error: str | None = None


# --- Trigger evaluation ---------------------------------------------------

def _trigger_quant_conflicts(t: dict[str, Any]) -> dict[str, Any] | None:
    """Quant components are disagreeing with each other."""
    drv = t.get("drivers", {})
    pos = drv.get("positive", []) or []
    neg = drv.get("negative", []) or []
    if not pos or not neg:
        return None
    top_pos = pos[0]
    top_neg = neg[0]
    return {
        "severity": 9,
        "label": "quant_internal_conflict",
        "question": (f"Our '{top_pos['name']}' signal is firmly bullish "
                     f"({top_pos['contribution']:+.1f} pts) while '{top_neg['name']}' "
                     f"is firmly bearish ({top_neg['contribution']:+.1f} pts) — "
                     f"which one do you believe is the leading indicator here, "
                     f"and what would have to happen for the lagging signal to flip?"),
        "why_it_matters": (f"When the quant stack disagrees with itself, the headline "
                           f"score hides the real bet. Forces the analyst to articulate "
                           f"which factor is the actual driver of the thesis."),
    }


def _trigger_valuation_vs_quant_split(t: dict[str, Any]) -> dict[str, Any] | None:
    """DCF says one thing, quant says another."""
    drv = t.get("drivers", {})
    components = drv.get("positive", []) + drv.get("negative", []) + drv.get("neutral_or_missing", [])
    val_comp = next((c for c in components if c.get("name") == "valuation"), None)
    tech_comp = next((c for c in components if c.get("name") == "technical"), None)
    if not val_comp or not tech_comp:
        return None
    if val_comp.get("score") is None or tech_comp.get("score") is None:
        return None
    if val_comp["score"] < -20 and tech_comp["score"] > 20:
        return {
            "severity": 8,
            "label": "value_momentum_split",
            "question": ("Technicals are firmly positive but our DCF flags this name "
                         "as expensive. If we go long here on momentum, what is the "
                         "explicit exit trigger that would tell us the valuation gap "
                         "has finally caught up?"),
            "why_it_matters": ("Momentum-vs-value splits are how analysts get caught "
                               "long at the top. Forces a pre-committed exit rule."),
        }
    if val_comp["score"] > 20 and tech_comp["score"] < -20:
        return {
            "severity": 8,
            "label": "cheap_but_falling",
            "question": ("DCF says this is cheap but technicals are firmly negative. "
                         "What evidence would convince us the market has stopped "
                         "selling and started discounting the value, rather than us "
                         "catching a falling knife?"),
            "why_it_matters": ("'Cheap and getting cheaper' is the value trap. The "
                               "answer should be a measurable price-action criterion."),
        }
    return None


def _trigger_dcf_unreliable(t: dict[str, Any]) -> dict[str, Any] | None:
    """The DCF itself isn't trustworthy — wide range or low FCF reliability."""
    val_text = t.get("valuation_summary", "") or ""
    if "directional rather than precise" in val_text or "Insufficient data" in val_text:
        return {
            "severity": 7,
            "label": "dcf_unreliable",
            "question": ("Our DCF flags low reliability for this name due to erratic "
                         "free cash flow history. What is the alternative anchor we "
                         "are using to size the position — peer multiples, EV/sales, "
                         "or a sum-of-the-parts?"),
            "why_it_matters": ("Forces an honest answer about what the position is "
                               "actually grounded in when the headline DCF can't be "
                               "trusted at face value."),
        }
    return None


def _trigger_earnings_imminent(t: dict[str, Any]) -> dict[str, Any] | None:
    """Earnings within 14 days — binary event risk."""
    cat_text = t.get("catalysts", "") or ""
    # Detect "Earnings in N days" with N <= 14
    import re
    m = re.search(r"Earnings in (\d+) days", cat_text)
    if not m:
        return None
    days = int(m.group(1))
    if days > 14:
        return None
    return {
        "severity": 8,
        "label": "earnings_imminent",
        "question": (f"With earnings in {days} days, are we positioned for the print "
                     f"itself, or holding through it? If holding, what is the bear-case "
                     f"reaction we are willing to take on the chin without changing the "
                     f"thesis — and at what level do we cut?"),
        "why_it_matters": ("Most thesis blow-ups around earnings come from not having "
                           "decided the holding-vs-trading question in advance. Forces "
                           "the trade structure conversation."),
    }


def _trigger_negative_sentiment_dislocation(t: dict[str, Any]) -> dict[str, Any] | None:
    """Sentiment is bad, quant is good — narrative risk."""
    drv = t.get("drivers", {})
    components = drv.get("positive", []) + drv.get("negative", []) + drv.get("neutral_or_missing", [])
    sent_comp = next((c for c in components if c.get("name") == "sentiment"), None)
    if not sent_comp or sent_comp.get("score") is None:
        return None
    if sent_comp["score"] < -25:
        return {
            "severity": 6,
            "label": "negative_sentiment",
            "question": ("News sentiment is materially negative — what is the specific "
                         "narrative the market is selling, and what data point in the "
                         "next 90 days would force the narrative to change?"),
            "why_it_matters": ("Identifies whether the bear story is a known issue "
                               "already priced in, or a developing problem that could "
                               "get worse before it gets better."),
        }
    return None


def _trigger_regime_unfavorable(t: dict[str, Any]) -> dict[str, Any] | None:
    """We're long but the regime is hostile."""
    drv = t.get("drivers", {})
    components = drv.get("positive", []) + drv.get("negative", []) + drv.get("neutral_or_missing", [])
    regime_comp = next((c for c in components if c.get("name") == "regime"), None)
    rec = t.get("recommendation", {})
    if not regime_comp:
        return None
    detail = (regime_comp.get("detail") or "").lower()
    is_hostile = any(w in detail for w in ("bear", "down", "volatile"))
    if is_hostile and rec.get("action") == "Buy":
        return {
            "severity": 7,
            "label": "regime_hostile",
            "question": ("The HMM places this name in an unfavorable regime, yet we "
                         "are recommending a long. What position-sizing adjustment "
                         "are we making to account for the elevated drawdown risk "
                         "this regime historically produces?"),
            "why_it_matters": ("Regime-aware sizing is what separates a quant book "
                               "from a discretionary one. Forces the answer to be "
                               "specific (e.g., half-size, wider stop)."),
        }
    return None


def _trigger_concentrated_driver(t: dict[str, Any]) -> dict[str, Any] | None:
    """A single component is doing most of the work — fragile thesis."""
    drv = t.get("drivers", {})
    pos = drv.get("positive", []) or []
    neg = drv.get("negative", []) or []
    rec = t.get("recommendation", {})
    target = pos if rec.get("action") == "Buy" else neg if rec.get("action") == "Sell" else None
    if not target or len(target) < 2:
        return None
    top = target[0]
    rest_sum = sum(abs(r["contribution"]) for r in target[1:])
    if abs(top["contribution"]) > rest_sum * 1.5 and abs(top["contribution"]) > 5:
        direction = "bull" if rec.get("action") == "Buy" else "bear"
        return {
            "severity": 6,
            "label": "concentrated_driver",
            "question": (f"The {direction} case is heavily concentrated in our "
                         f"'{top['name']}' signal — if that one component flipped "
                         f"tomorrow, what is the rest of the stack telling us, and "
                         f"would we still want to be in this name?"),
            "why_it_matters": ("Tests whether the thesis has redundancy or rests "
                               "on a single point of failure."),
        }
    return None


def _trigger_short_squeeze_risk(t: dict[str, Any]) -> dict[str, Any] | None:
    cat_text = t.get("catalysts", "") or ""
    if "squeeze setup" in cat_text:
        return {
            "severity": 5,
            "label": "short_squeeze_setup",
            "question": ("Short interest is elevated enough to create squeeze risk on "
                         "any positive surprise. Are we positioned to benefit from a "
                         "squeeze, or hedged against being on the wrong side of one?"),
            "why_it_matters": ("Crowded shorts cut both ways. The honest answer "
                               "tells us whether we have an asymmetric setup or "
                               "an asymmetric risk."),
        }
    return None


def _trigger_low_conviction(t: dict[str, Any]) -> dict[str, Any] | None:
    rec = t.get("recommendation", {})
    if rec.get("conviction") == "Low":
        return {
            "severity": 6,
            "label": "low_conviction",
            "question": ("This name is rated low conviction — what is the single piece "
                         "of evidence (an upcoming print, a competitor disclosure, an "
                         "industry data point) that would move us to medium conviction "
                         "in either direction?"),
            "why_it_matters": ("Low-conviction names should either get upgraded with "
                               "new data or be dropped. Forces a falsifiable trigger."),
        }
    return None


# Generic fallback questions — always strong, used to top up to 5.
FALLBACK_QUESTIONS = [
    {
        "question": ("If the position were down 15% in the next quarter, what would "
                     "we expect to be the most likely cause — macro, idiosyncratic, "
                     "or sector rotation?"),
        "why_it_matters": ("Pre-mortem framing. Forces the analyst to identify the "
                           "real risk vector before it becomes a P&L hit."),
    },
    {
        "question": ("Where does this name sit in the peer group on the metrics that "
                     "drive its multiple — and is the relative ranking justified by "
                     "growth, margin, or capital efficiency?"),
        "why_it_matters": ("Validates whether the relative-value call is anchored to "
                           "a fundamental driver or just a multiple comparison."),
    },
    {
        "question": ("What does the buy-side own here vs. consensus? Is the trade "
                     "we're making consensus or contrarian, and how does that affect "
                     "our edge?"),
        "why_it_matters": ("Consensus longs unwind violently on disappointment. "
                           "Identifies positioning risk that the model can't see."),
    },
    {
        "question": ("If we were starting fresh today with no prior position, would "
                     "this name make our top-5 ideas list — or are we anchored to "
                     "a thesis we built on data that has since changed?"),
        "why_it_matters": ("Anchor-bias check. Forces a rebuild-from-scratch test of "
                           "whether the thesis is still the best use of risk capital."),
    },
    {
        "question": ("What is the cleanest catalyst path to a 25% return on this "
                     "name, and what is the cleanest path to a 25% loss? Which is "
                     "more probable, and over what time horizon?"),
        "why_it_matters": ("Forces an explicit risk/reward articulation rather than "
                           "a directional 'I like it' call."),
    },
]


TRIGGER_FUNCS = [
    _trigger_quant_conflicts,
    _trigger_valuation_vs_quant_split,
    _trigger_dcf_unreliable,
    _trigger_earnings_imminent,
    _trigger_negative_sentiment_dislocation,
    _trigger_regime_unfavorable,
    _trigger_concentrated_driver,
    _trigger_short_squeeze_risk,
    _trigger_low_conviction,
]


@cached(ttl_seconds=CACHE_TTL, key_fn=lambda t: f"speaker_prep:v1:{t.upper()}")
def compute(ticker: str) -> SpeakerPrep:
    ticker = ticker.upper()
    th_result = thesis_mod.compute(ticker)
    if th_result.error:
        return SpeakerPrep(ticker=ticker,
                           error=f"thesis unavailable: {th_result.error}")
    th = thesis_mod.to_dict(th_result)

    fired: list[dict[str, Any]] = []
    for fn in TRIGGER_FUNCS:
        try:
            res = fn(th)
            if res:
                fired.append(res)
        except Exception:
            continue

    fired.sort(key=lambda r: r["severity"], reverse=True)

    questions: list[dict[str, str]] = []
    triggers_fired: list[str] = []
    for r in fired[:5]:
        questions.append({"question": r["question"], "why_it_matters": r["why_it_matters"]})
        triggers_fired.append(r["label"])

    # Top up with fallbacks so we always return exactly 5
    fallback_idx = 0
    while len(questions) < 5 and fallback_idx < len(FALLBACK_QUESTIONS):
        questions.append(dict(FALLBACK_QUESTIONS[fallback_idx]))
        triggers_fired.append("fallback")
        fallback_idx += 1

    return SpeakerPrep(ticker=ticker, questions=questions, triggers_fired=triggers_fired)


def to_dict(s: SpeakerPrep) -> dict[str, Any]:
    return {
        "ticker": getattr(s, "ticker", None),
        "questions": getattr(s, "questions", []),
        "triggers_fired": getattr(s, "triggers_fired", []),
        "error": getattr(s, "error", None),
    }
