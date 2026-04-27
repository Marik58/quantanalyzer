"""Investment thesis generator — deterministic templated prose.

Pulls quant_score, valuation, sentiment, regime_hmm, catalyst, and peers for a
ticker, then writes a structured thesis with these sections:

  - company_overview      : sector, industry, market cap, business summary
  - edge                  : why the market may be mispricing this name
  - catalysts             : near-term events that could close the gap
  - valuation_summary     : intrinsic vs current, upside/downside
  - scenarios.bull/base/bear : what each case looks like
  - risks                 : what would invalidate the thesis
  - recommendation        : action + conviction + rationale

Method:
  Each section is built from pre-written prose templates that branch on the
  numeric inputs. The output reads like an analyst wrote it because the
  templates are written like an analyst would. It is fully deterministic —
  same inputs always produce the same thesis.

  Every input fetch is wrapped in try/except: a single failed module degrades
  the relevant section to a "data unavailable" line rather than killing the
  whole thesis.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yfinance as yf
from curl_cffi import requests as curl_requests

from backend.analysis import catalyst as catalyst_mod
from backend.analysis import data as data_mod
from backend.analysis import peers as peers_mod
from backend.analysis import quant_score as quant_score_mod
from backend.analysis import regime_hmm as regime_hmm_mod
from backend.analysis import sentiment as sentiment_mod
from backend.analysis import valuation as valuation_mod
from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
_SESSION = curl_requests.Session(impersonate="chrome")


@dataclass
class Thesis:
    ticker: str
    company_overview: str = ""
    edge: str = ""
    catalysts_text: str = ""
    valuation_summary: str = ""
    scenarios: dict[str, str] = field(default_factory=dict)
    risks: str = ""
    recommendation: dict[str, Any] = field(default_factory=dict)
    drivers: dict[str, Any] = field(default_factory=dict)
    inputs_status: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _gather_inputs(ticker: str) -> dict[str, Any]:
    """Best-effort fetch of all input modules. Each missing → None."""
    out: dict[str, Any] = {"status": {}}

    # Price data — needed by sentiment + regime_hmm
    td = _safe(lambda: data_mod.load(ticker))
    out["price_data"] = td
    out["status"]["price_data"] = "ok" if td is not None else "failed"

    # Quant score
    qs = _safe(lambda: quant_score_mod.compute(ticker))
    if qs is not None and not getattr(qs, "error", None):
        out["quant_score"] = qs
        out["status"]["quant_score"] = "ok"
    else:
        out["quant_score"] = None
        out["status"]["quant_score"] = "failed"

    # Valuation
    val = _safe(lambda: valuation_mod.compute(ticker))
    if val is not None and val.method != "unavailable":
        out["valuation"] = val
        out["status"]["valuation"] = "ok"
    else:
        out["valuation"] = None
        out["status"]["valuation"] = "failed"

    # Sentiment
    if td is not None:
        sent = _safe(lambda: sentiment_mod.compute(ticker, td.history["Close"]))
    else:
        sent = _safe(lambda: sentiment_mod.compute(ticker))
    if sent is not None and not getattr(sent, "error", None):
        out["sentiment"] = sent
        out["status"]["sentiment"] = "ok"
    else:
        out["sentiment"] = None
        out["status"]["sentiment"] = "failed"

    # Regime HMM
    if td is not None:
        regime = _safe(lambda: regime_hmm_mod.compute(td.history["Close"]))
        if regime is not None and not getattr(regime, "error", None):
            out["regime"] = regime
            out["status"]["regime"] = "ok"
        else:
            out["regime"] = None
            out["status"]["regime"] = "failed"
    else:
        out["regime"] = None
        out["status"]["regime"] = "skipped (no price data)"

    # Catalyst
    cat = _safe(lambda: catalyst_mod.compute(ticker))
    if cat is not None and not getattr(cat, "error", None):
        out["catalyst"] = cat
        out["status"]["catalyst"] = "ok"
    else:
        out["catalyst"] = None
        out["status"]["catalyst"] = "failed"

    # Peers
    pr = _safe(lambda: peers_mod.compute(ticker))
    if pr is not None:
        out["peers"] = pr
        out["status"]["peers"] = "ok"
    else:
        out["peers"] = None
        out["status"]["peers"] = "failed"

    # Company info via yfinance (for overview)
    try:
        info = yf.Ticker(ticker, session=_SESSION).info or {}
    except Exception:
        info = {}
    out["info"] = info

    return out


def _company_overview(ticker: str, info: dict[str, Any]) -> str:
    name = info.get("shortName") or info.get("longName") or ticker
    sector = info.get("sector") or "n/a"
    industry = info.get("industry") or "n/a"
    mcap = info.get("marketCap")
    summary = info.get("longBusinessSummary") or ""
    first_sentence = summary.split(". ")[0] + "." if summary else ""

    if mcap:
        if mcap >= 1e12:
            mcap_txt = f"${mcap / 1e12:.2f}T market cap"
        elif mcap >= 1e9:
            mcap_txt = f"${mcap / 1e9:.1f}B market cap"
        else:
            mcap_txt = f"${mcap / 1e6:.0f}M market cap"
    else:
        mcap_txt = "market cap unavailable"

    return (f"{name} ({ticker}) — {sector} / {industry}, {mcap_txt}. "
            f"{first_sentence}").strip()


def _edge(qs, val, sent, regime) -> str:
    """Why the market may be mispricing this name. Uses percentile (0..100)."""
    qs_pct = qs.percentile_score if qs else None
    qs_dir = qs.directional_score if qs else None
    upside = val.weighted_upside_pct if val and val.weighted_upside_pct is not None else None
    sent_score = sent.overall_score if sent else None
    regime_lbl = regime.current_regime if regime else None

    # Bullish-with-upside case
    if qs_pct is not None and qs_pct > 65 and upside is not None and upside > 0.15:
        return (f"The full quant stack is constructive (percentile {qs_pct:.0f}/100) and a "
                f"5-year DCF implies +{upside * 100:.0f}% upside to intrinsic value. The "
                f"combination of positive momentum and a discount to fair value is the classic "
                f"setup where the market has not yet caught up to improving fundamentals.")

    # Bullish but expensive
    if qs_pct is not None and qs_pct > 65 and upside is not None and upside < 0:
        return (f"Quant signals are bullish (percentile {qs_pct:.0f}/100), but our DCF shows "
                f"the stock trading {abs(upside) * 100:.0f}% above intrinsic value. The edge "
                f"here is that price/momentum dynamics may persist longer than valuation "
                f"discipline would justify — a momentum trade rather than a value thesis.")

    # Bearish-but-cheap (potential value)
    if qs_pct is not None and qs_pct < 40 and upside is not None and upside > 0.20:
        return (f"Sentiment and price action are weak (percentile {qs_pct:.0f}/100), yet a DCF "
                f"suggests +{upside * 100:.0f}% upside. This is a textbook "
                f"value-vs-momentum dislocation. The edge requires patience: the market is "
                f"pricing in a worse outcome than the fundamentals support, but there is no "
                f"obvious catalyst for re-rating in the near term.")

    # Negative sentiment dislocation
    if sent_score is not None and sent_score < -0.25 and qs_pct is not None and qs_pct > 55:
        return (f"News flow is materially negative (sentiment score {sent_score:+.2f}) but the "
                f"underlying quant picture remains positive (percentile {qs_pct:.0f}/100). "
                f"The edge is the gap between narrative and fundamentals — historically these "
                f"dislocations close as headlines fade.")

    # All-aligned bearish
    if qs_pct is not None and qs_pct < 40 and (upside is None or upside < 0):
        return (f"Both quant signals (percentile {qs_pct:.0f}/100) and valuation point in the "
                f"same direction. There is no obvious mispricing in our favor; the market "
                f"appears to be reading the same data we are.")

    # Default — middling, no strong edge
    parts = []
    if qs_pct is not None:
        parts.append(f"quant percentile {qs_pct:.0f}/100 (directional {qs_dir:+.0f})")
    if upside is not None:
        parts.append(f"DCF upside {upside * 100:+.0f}%")
    if sent_score is not None:
        parts.append(f"sentiment {sent_score:+.2f}")
    if regime_lbl:
        parts.append(f"regime '{regime_lbl}'")
    detail = "; ".join(parts) if parts else "limited inputs available"
    return (f"No high-conviction edge identified. Inputs are mixed or middling "
            f"({detail}). This is a name to monitor rather than press in either direction.")


def _catalysts_text(cat) -> str:
    if cat is None:
        return "Catalyst data unavailable."

    lines: list[str] = []

    # Earnings
    if cat.earnings and cat.earnings.get("days_until") is not None:
        d = cat.earnings["days_until"]
        eps = cat.earnings.get("eps_estimate")
        eps_txt = f" (Street EPS estimate ${eps:.2f})" if eps is not None else ""
        if 0 <= d <= 30:
            lines.append(f"Earnings in {d} days{eps_txt} — high-volatility catalyst window.")
        elif d > 30:
            lines.append(f"Next earnings in {d} days{eps_txt} — no near-term print.")

    # Dividend
    if cat.dividend and cat.dividend.get("days_until") is not None:
        d = cat.dividend["days_until"]
        amt = cat.dividend.get("amount")
        if 0 <= d <= 60 and amt:
            lines.append(f"Ex-dividend in {d} days (${amt:.2f}/share).")

    # Rating changes
    if cat.rating_changes_30d:
        ups = sum(1 for r in cat.rating_changes_30d if "up" in (r.get("action") or "").lower())
        downs = sum(1 for r in cat.rating_changes_30d if "down" in (r.get("action") or "").lower())
        if ups or downs:
            lines.append(f"{ups} upgrade(s) and {downs} downgrade(s) in the last 30 days from "
                         f"sell-side coverage.")

    # Analyst upside
    if cat.analyst_targets and cat.analyst_targets.get("upside_to_median_pct") is not None:
        ups = cat.analyst_targets["upside_to_median_pct"]
        n = cat.analyst_targets.get("n_analysts")
        n_txt = f" ({n} analysts)" if n else ""
        if ups > 0.10:
            lines.append(f"Street median target implies +{ups * 100:.0f}% upside{n_txt} — "
                         f"consensus is constructive.")
        elif ups < -0.05:
            lines.append(f"Street median target implies {ups * 100:.0f}% downside{n_txt} — "
                         f"consensus is cautious.")

    # Short interest squeeze
    if cat.short_interest_pct_float is not None and cat.short_interest_pct_float > 0.10:
        lines.append(f"Short interest of {cat.short_interest_pct_float * 100:.1f}% of float "
                     f"creates a squeeze setup on positive surprises.")

    if not lines:
        return "No material near-term catalysts identified."
    return " ".join(lines)


def _valuation_summary(val) -> str:
    if val is None:
        return "Valuation unavailable — DCF could not be computed."

    price = val.current_price
    intrinsic = val.weighted_intrinsic
    upside = val.weighted_upside_pct
    if price is None or intrinsic is None or upside is None:
        return f"DCF method: {val.method}. Insufficient data for a confident valuation."

    direction = "upside" if upside > 0 else "downside"
    if abs(upside) < 0.05:
        verdict = "fair-valued — within ±5% of intrinsic"
    elif abs(upside) < 0.15:
        verdict = f"modestly mispriced ({upside * 100:+.0f}% to intrinsic)"
    elif abs(upside) < 0.30:
        verdict = f"materially mispriced ({upside * 100:+.0f}% to intrinsic)"
    else:
        verdict = f"deeply mispriced ({upside * 100:+.0f}% to intrinsic)"

    reliability_note = ""
    if val.history and val.history.reliability == "low":
        reliability_note = (" Note: historical free cash flow is erratic, so the DCF "
                            "should be treated as directional rather than precise.")

    return (f"5-year probability-weighted DCF places intrinsic value at "
            f"${intrinsic:,.2f}/share against a current price of ${price:,.2f} — "
            f"{verdict}, implying {abs(upside) * 100:.0f}% {direction}.{reliability_note}")


def _scenarios(val, qs, regime) -> dict[str, str]:
    """Bull / Base / Bear case prose. Pulls DCF scenarios when available."""
    out = {}
    if val and val.scenarios:
        scen_map = {s.name: s for s in val.scenarios}
        bull = scen_map.get("Bull")
        base = scen_map.get("Base")
        bear = scen_map.get("Bear")

        if bull:
            out["bull"] = (f"Bull case — DCF intrinsic ${bull.intrinsic_per_share:,.2f} "
                           f"({bull.upside_pct * 100:+.0f}%). Assumes initial growth of "
                           f"{bull.assumptions.initial_growth * 100:+.0f}% fading to terminal "
                           f"growth of {bull.assumptions.terminal_growth * 100:+.0f}% at a "
                           f"{bull.assumptions.discount_rate * 100:.1f}% discount rate. "
                           f"Path requires sustained margin expansion or market share gains.")
        if base:
            out["base"] = (f"Base case — DCF intrinsic ${base.intrinsic_per_share:,.2f} "
                           f"({base.upside_pct * 100:+.0f}%). Assumes initial growth of "
                           f"{base.assumptions.initial_growth * 100:+.0f}% fading to "
                           f"{base.assumptions.terminal_growth * 100:+.0f}% terminal at "
                           f"{base.assumptions.discount_rate * 100:.1f}% discount. "
                           f"This is the most likely outcome under current trends.")
        if bear:
            out["bear"] = (f"Bear case — DCF intrinsic ${bear.intrinsic_per_share:,.2f} "
                           f"({bear.upside_pct * 100:+.0f}%). Assumes initial growth of "
                           f"{bear.assumptions.initial_growth * 100:+.0f}% fading to "
                           f"{bear.assumptions.terminal_growth * 100:+.0f}% terminal at "
                           f"{bear.assumptions.discount_rate * 100:.1f}% discount. "
                           f"Triggered by margin compression, demand weakness, or rising rates.")
    else:
        out["bull"] = "Bull case — DCF unavailable; would require sustained earnings beat and multiple expansion."
        out["base"] = "Base case — DCF unavailable; assume the stock tracks sector returns from here."
        out["bear"] = "Bear case — DCF unavailable; downside driven by macro shock or company-specific stumble."
    return out


def _risks(qs, val, sent, regime, cat) -> str:
    risks: list[str] = []

    # Regime risk
    if regime and regime.current_regime:
        r = regime.current_regime.lower()
        if "bear" in r or "down" in r or "volatile" in r:
            risks.append(f"current market regime is '{regime.current_regime}' — "
                         f"adverse backdrop for long positions")

    # Sentiment risk
    if sent and sent.overall_score is not None and sent.overall_score < -0.20:
        risks.append(f"news sentiment is negative ({sent.overall_score:+.2f}) — "
                     f"narrative risk of further headline-driven selling")

    # Quant conflict risk
    if qs and getattr(qs, "conflicts", None):
        risks.append(f"quant components disagree ({len(qs.conflicts)} conflict(s)) — "
                     f"signal confidence is lower than headline score suggests")

    # Earnings volatility risk
    if cat and cat.earnings and cat.earnings.get("days_until") is not None:
        d = cat.earnings["days_until"]
        if 0 <= d <= 14:
            risks.append(f"earnings in {d} days — binary event risk in either direction")

    # Valuation risk
    if val and val.weighted_upside_pct is not None and val.weighted_upside_pct < -0.10:
        risks.append(f"DCF places stock {abs(val.weighted_upside_pct) * 100:.0f}% above "
                     f"intrinsic — multiple compression risk if growth disappoints")

    # Reliability risk
    if val and val.history and val.history.reliability == "low":
        risks.append("DCF reliability is low (erratic FCF history) — "
                     "valuation conclusions are directional only")

    if not risks:
        return ("No specific risk flags from the model. Standard risks apply: macro shocks, "
                "company-specific operational missteps, and unexpected competitive moves.")

    return "Key risks: " + "; ".join(risks) + "."


def _recommendation(qs, val, sent, regime) -> dict[str, Any]:
    # Use percentile_score (0..100) — directional_score is -100..+100 and the
    # thresholds below are calibrated to the 0..100 scale.
    qs_pct = qs.percentile_score if qs else None
    qs_dir = qs.directional_score if qs else None
    upside = val.weighted_upside_pct if val and val.weighted_upside_pct is not None else None
    sent_score = sent.overall_score if sent else None

    # Action: based primarily on quant percentile, modulated by valuation
    if qs_pct is None:
        action = "Hold"
        action_reason = "insufficient quant data to issue a directional call"
    elif qs_pct >= 70 and (upside is None or upside > 0):
        action = "Buy"
        action_reason = f"strong quant signal (percentile {qs_pct:.0f}) with non-negative valuation"
    elif qs_pct >= 60:
        action = "Buy"
        action_reason = f"moderately positive quant signal (percentile {qs_pct:.0f})"
    elif qs_pct >= 45:
        action = "Hold"
        action_reason = f"neutral-to-mild quant signal (percentile {qs_pct:.0f})"
    elif qs_pct >= 30:
        action = "Sell"
        action_reason = f"weak quant signal (percentile {qs_pct:.0f})"
    else:
        action = "Sell"
        action_reason = f"strongly negative quant signal (percentile {qs_pct:.0f})"

    # Conviction: starts at Medium, raised/lowered by alignment of inputs
    align_score = 0
    if qs_pct is not None and upside is not None:
        if (qs_pct >= 55 and upside > 0.05) or (qs_pct < 45 and upside < -0.05):
            align_score += 1
        if (qs_pct >= 55 and upside < -0.10) or (qs_pct < 45 and upside > 0.10):
            align_score -= 1
    if sent_score is not None and qs_pct is not None:
        if (qs_pct >= 55 and sent_score > 0) or (qs_pct < 45 and sent_score < 0):
            align_score += 1
        elif abs(sent_score) > 0.20:
            align_score -= 1
    if qs and getattr(qs, "conflicts", None):
        align_score -= 1

    if align_score >= 2:
        conviction = "High"
    elif align_score <= -1:
        conviction = "Low"
    else:
        conviction = "Medium"

    rationale_bits = []
    if qs_pct is not None:
        rationale_bits.append(f"quant percentile {qs_pct:.0f}/100 (directional {qs_dir:+.0f})")
    if upside is not None:
        rationale_bits.append(f"DCF upside {upside * 100:+.0f}%")
    if sent_score is not None:
        rationale_bits.append(f"sentiment {sent_score:+.2f}")
    if regime and regime.current_regime:
        rationale_bits.append(f"regime '{regime.current_regime}'")

    rationale = (f"{action_reason}. Inputs: " + "; ".join(rationale_bits) + "." +
                 (" Conviction lowered due to conflicting signals." if align_score < 0 else "") +
                 (" Conviction raised — multiple signals align." if align_score >= 2 else ""))

    return {"action": action, "conviction": conviction, "rationale": rationale}


def _drivers(qs) -> dict[str, Any]:
    """Break down which quant components are pulling the score up vs down.

    Each component contributes (score * weight) to the overall directional
    score. Positive contributions push toward Buy, negative toward Sell.
    """
    if qs is None or not getattr(qs, "components", None):
        return {"available": False, "summary": "Driver breakdown unavailable — quant_score did not run.",
                "positive": [], "negative": [], "neutral_or_missing": []}

    rows = []
    missing = []
    for c in qs.components:
        if c.score is None:
            missing.append({"name": c.name, "weight": c.weight, "detail": c.detail})
            continue
        contribution = float(c.score) * float(c.weight)
        rows.append({
            "name": c.name,
            "score": float(c.score),
            "weight": float(c.weight),
            "contribution": contribution,
            "detail": c.detail,
        })

    positive = sorted([r for r in rows if r["contribution"] > 1.0],
                      key=lambda r: r["contribution"], reverse=True)
    negative = sorted([r for r in rows if r["contribution"] < -1.0],
                      key=lambda r: r["contribution"])
    neutral = [r for r in rows if abs(r["contribution"]) <= 1.0]

    # One-sentence summary
    if positive and negative:
        top_pos = positive[0]
        top_neg = negative[0]
        summary = (f"Score pulled UP most by {top_pos['name']} "
                   f"({top_pos['contribution']:+.1f} pts) and DOWN most by "
                   f"{top_neg['name']} ({top_neg['contribution']:+.1f} pts).")
    elif positive:
        summary = (f"All directional signals pulling UP — strongest contributor: "
                   f"{positive[0]['name']} ({positive[0]['contribution']:+.1f} pts).")
    elif negative:
        summary = (f"All directional signals pulling DOWN — strongest drag: "
                   f"{negative[0]['name']} ({negative[0]['contribution']:+.1f} pts).")
    else:
        summary = "All quant components are roughly neutral — no dominant driver in either direction."

    return {
        "available": True,
        "summary": summary,
        "positive": positive,
        "negative": negative,
        "neutral_or_missing": neutral + [
            {"name": m["name"], "score": None, "weight": m["weight"],
             "contribution": 0.0, "detail": m["detail"]}
            for m in missing
        ],
    }


@cached(ttl_seconds=CACHE_TTL, key_fn=lambda t: f"thesis:v3:{t.upper()}")
def compute(ticker: str) -> Thesis:
    ticker = ticker.upper()
    inp = _gather_inputs(ticker)

    # If literally everything failed, return an error result
    ok_count = sum(1 for v in inp["status"].values() if v == "ok")
    if ok_count == 0:
        return Thesis(ticker=ticker, error="all input modules failed for this ticker",
                      inputs_status=inp["status"])

    qs = inp["quant_score"]
    val = inp["valuation"]
    sent = inp["sentiment"]
    regime = inp["regime"]
    cat = inp["catalyst"]
    info = inp["info"]

    return Thesis(
        ticker=ticker,
        company_overview=_company_overview(ticker, info),
        edge=_edge(qs, val, sent, regime),
        catalysts_text=_catalysts_text(cat),
        valuation_summary=_valuation_summary(val),
        scenarios=_scenarios(val, qs, regime),
        risks=_risks(qs, val, sent, regime, cat),
        recommendation=_recommendation(qs, val, sent, regime),
        drivers=_drivers(qs),
        inputs_status=inp["status"],
    )


def to_dict(t: Thesis) -> dict[str, Any]:
    # Use getattr defaults so old pickled objects (missing newly-added fields)
    # don't crash the serialization layer if the cache key isn't bumped.
    return {
        "ticker": getattr(t, "ticker", None),
        "company_overview": getattr(t, "company_overview", ""),
        "edge": getattr(t, "edge", ""),
        "catalysts": getattr(t, "catalysts_text", ""),
        "valuation_summary": getattr(t, "valuation_summary", ""),
        "scenarios": getattr(t, "scenarios", {}),
        "risks": getattr(t, "risks", ""),
        "recommendation": getattr(t, "recommendation", {}),
        "drivers": getattr(t, "drivers", {"available": False, "summary": "n/a",
                                          "positive": [], "negative": [], "neutral_or_missing": []}),
        "inputs_status": getattr(t, "inputs_status", {}),
        "error": getattr(t, "error", None),
    }
