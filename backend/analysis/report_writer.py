"""Full sell-side-style research report writer.

Combines every relevant module into a long-form markdown document with these
sections (each rendered as a `## Header` so we can verify structure):

  1. Executive Summary
  2. Company Overview
  3. Quantitative Analysis
  4. Valuation
  5. Catalyst Review
  6. Risk Analysis
  7. Bull / Base / Bear Scenarios
  8. Conclusion
  9. Appendix — Speaker Prep Q&A

Method:
  - Reuses the cached thesis (which already aggregated quant_score,
    valuation, sentiment, regime, catalyst, peers).
  - Reuses cached speaker_prep for the appendix.
  - Calls risk_framework directly for the deeper Risk Analysis section
    (stress scenarios, drawdown, Kelly sizing).
  - Calls peers directly for the comparable-company table in Valuation.

Tone: structured, honest, flags uncertainty. Never oversells a signal.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.analysis import peers as peers_mod
from backend.analysis import quant_score as quant_score_mod
from backend.analysis import risk_framework as risk_fw_mod
from backend.analysis import speaker_prep as speaker_prep_mod
from backend.analysis import thesis as thesis_mod
from backend.cache import cached

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))


@dataclass
class Report:
    ticker: str
    report_markdown: str = ""
    word_count: int = 0
    sections: list[str] = field(default_factory=list)
    error: str | None = None


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "n/a"
    if abs(v) >= 1e12:
        return f"${v / 1e12:,.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.2f}M"
    return f"${v:,.2f}"


def _fmt_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:+.{digits}f}%"


# --- Section builders -----------------------------------------------------

def _executive_summary(th: dict[str, Any]) -> str:
    rec = th.get("recommendation", {})
    drv = th.get("drivers", {})
    val_text = th.get("valuation_summary", "") or ""

    bullets = []
    bullets.append(f"**Recommendation:** {rec.get('action', 'n/a')} "
                   f"({rec.get('conviction', 'n/a')} conviction)")

    if drv.get("available") and drv.get("summary"):
        bullets.append(f"**Quant view:** {drv['summary']}")

    bullets.append(f"**Valuation:** {val_text}")

    edge = th.get("edge", "")
    if edge:
        bullets.append(f"**Edge:** {edge}")

    return "## Executive Summary\n\n" + "\n\n".join(f"- {b}" for b in bullets)


def _company_overview(th: dict[str, Any]) -> str:
    return "## Company Overview\n\n" + (th.get("company_overview") or "n/a")


def _quantitative_analysis(th: dict[str, Any], qs_payload: dict[str, Any] | None) -> str:
    parts = ["## Quantitative Analysis\n"]

    if qs_payload is None or qs_payload.get("error"):
        parts.append("Quant score data unavailable for this ticker.")
        return "\n".join(parts)

    parts.append(f"**Aggregate score:** directional {qs_payload['directional_score']:+.1f} "
                 f"(percentile {qs_payload['percentile_score']:.0f}/100), verdict "
                 f"**{qs_payload['verdict']}**, model confidence "
                 f"{qs_payload['confidence']:.0f}/100.\n")

    drv = th.get("drivers", {})
    if drv.get("available"):
        parts.append(f"_{drv['summary']}_\n")
        parts.append("\n**Component contributions** (score × weight):\n")
        parts.append("| Component | Score | Weight | Contribution | Detail |")
        parts.append("|---|---:|---:|---:|---|")
        all_rows = (drv.get("positive", []) + drv.get("negative", [])
                    + drv.get("neutral_or_missing", []))
        for r in all_rows:
            score_txt = f"{r['score']:+.1f}" if r.get("score") is not None else "n/a"
            parts.append(f"| {r['name']} | {score_txt} | {r['weight']:.2f} "
                         f"| {r['contribution']:+.1f} | {r['detail'][:60]} |")

    if qs_payload.get("conflicts"):
        parts.append("\n**Conflicts flagged:**")
        for c in qs_payload["conflicts"]:
            parts.append(f"- {c}")

    return "\n".join(parts)


def _valuation_section(th: dict[str, Any], peers_payload: dict[str, Any] | None) -> str:
    parts = ["## Valuation\n"]
    parts.append(th.get("valuation_summary", "n/a"))

    if peers_payload and peers_payload.get("peer_rows"):
        parts.append("\n**Peer comparison:**\n")
        target = peers_payload.get("target_row") or {}
        rows = [target] + peers_payload["peer_rows"]
        metric_order = peers_payload.get("metric_order", []) or []
        metric_labels = peers_payload.get("metric_labels", {}) or {}
        # Take up to 6 metrics so the table stays readable
        metrics_used = metric_order[:6]
        # Per-metric formatting: multiples are decimals; rates are percents
        pct_metrics = {"rev_grow", "gross_m", "mom_6m"}
        def _fmt_metric(m: str, v):
            if v is None:
                return "n/a"
            try:
                v = float(v)
            except (TypeError, ValueError):
                return str(v)
            if m in pct_metrics:
                sign = "+" if v >= 0 and m != "gross_m" else ""
                return f"{sign}{v * 100:.1f}%"
            return f"{v:.2f}"

        if metrics_used:
            header = "| Ticker | " + " | ".join(metric_labels.get(m, m) for m in metrics_used) + " |"
            sep = "|---|" + "|".join(["---:"] * len(metrics_used)) + "|"
            parts.append(header)
            parts.append(sep)
            for r in rows:
                tkr = r.get("ticker", "?")
                metrics = r.get("metrics") or {}
                cells = []
                for m in metrics_used:
                    mv = metrics.get(m) or {}
                    cells.append(_fmt_metric(m, mv.get("value")))
                marker = " ★" if tkr == peers_payload.get("ticker") else ""
                parts.append(f"| {tkr}{marker} | " + " | ".join(cells) + " |")
            rv_score = peers_payload.get("relative_value_score")
            rv_label = peers_payload.get("relative_value_label") or ""
            if rv_score is not None:
                parts.append(f"\n**Relative-value score:** {rv_score:.0f}/100 ({rv_label}).")

    return "\n".join(parts)


def _catalyst_review(th: dict[str, Any]) -> str:
    return "## Catalyst Review\n\n" + (th.get("catalysts") or "n/a")


def _risk_analysis(th: dict[str, Any], rf_payload: dict[str, Any] | None) -> str:
    parts = ["## Risk Analysis\n"]

    parts.append(th.get("risks", "") or "n/a")

    if rf_payload is None or rf_payload.get("error"):
        parts.append("\n_Detailed stress and tail-risk data unavailable._")
        return "\n".join(parts)

    label = rf_payload.get("overall_risk_label", "n/a")
    score = rf_payload.get("overall_risk_score")
    beta = rf_payload.get("beta_vs_spy")
    score_txt = f"{score:.0f}/100" if score is not None else "n/a"
    beta_txt = f"{beta:.2f}" if beta is not None else "n/a"
    parts.append(f"\n**Overall risk rating:** {label} ({score_txt}). β vs SPY: {beta_txt}.")

    # Drawdown
    dd = rf_payload.get("drawdown")
    if dd:
        parts.append(f"\n**Drawdown profile:** "
                     f"max drawdown {_fmt_pct(dd.get('max_drawdown'))} "
                     f"(over {dd.get('max_drawdown_duration_days')} days); "
                     f"currently {_fmt_pct(dd.get('current_drawdown'))} from 1Y high; "
                     f"worst 3M {_fmt_pct(dd.get('worst_3m'))}, "
                     f"worst 6M {_fmt_pct(dd.get('worst_6m'))}.")

    # Tail risk
    tr = rf_payload.get("tail_risk")
    if tr:
        parts.append(f"\n**Tail risk (daily):** "
                     f"95% VaR {_fmt_pct(tr.get('var_95_historical'))}, "
                     f"99% VaR {_fmt_pct(tr.get('var_99_historical'))}, "
                     f"95% CVaR (expected loss in tail) "
                     f"{_fmt_pct(tr.get('cvar_95'))}.")

    # Stress
    stress = rf_payload.get("stress_scenarios") or []
    if stress:
        parts.append("\n**Historical stress scenarios:**\n")
        parts.append("| Scenario | Period | Market Drawdown | Estimated Impact | Method |")
        parts.append("|---|---|---:|---:|---|")
        for s in stress:
            parts.append(f"| {s.get('name', '?')} | {s.get('period', '?')} | "
                         f"{_fmt_pct(s.get('market_drawdown'))} | "
                         f"{_fmt_pct(s.get('estimated_impact'))} | "
                         f"{s.get('method', 'n/a')} |")

    # Kelly sizing
    kelly = rf_payload.get("kelly")
    if kelly:
        parts.append(f"\n**Position sizing (Kelly):** full Kelly fraction "
                     f"{_fmt_pct(kelly.get('kelly_fraction'))}, half-Kelly "
                     f"{_fmt_pct(kelly.get('half_kelly'))}. "
                     f"{kelly.get('recommendation', '')}")

    return "\n".join(parts)


def _scenarios_section(th: dict[str, Any]) -> str:
    parts = ["## Bull / Base / Bear Scenarios\n"]
    sc = th.get("scenarios", {}) or {}
    for name in ("bull", "base", "bear"):
        text = sc.get(name)
        if text:
            parts.append(f"**{name.capitalize()} case:** {text}\n")
    return "\n".join(parts)


def _conclusion(th: dict[str, Any]) -> str:
    rec = th.get("recommendation", {})
    parts = ["## Conclusion\n"]
    parts.append(f"**Action:** {rec.get('action', 'n/a')}. "
                 f"**Conviction:** {rec.get('conviction', 'n/a')}.\n")
    parts.append(rec.get("rationale", "") or "")
    parts.append("\n_This report is a model-driven research aid, not investment advice. "
                 "All conclusions are conditional on the input data quality and the "
                 "deterministic templates used to render them._")
    return "\n".join(parts)


def _appendix_qa(sp_payload: dict[str, Any] | None) -> str:
    parts = ["## Appendix — Speaker Prep Q&A\n"]
    if sp_payload is None or not sp_payload.get("questions"):
        parts.append("Q&A pack unavailable.")
        return "\n".join(parts)
    for i, q in enumerate(sp_payload["questions"], start=1):
        parts.append(f"**Q{i}.** {q.get('question', '')}")
        parts.append(f"  *Why it matters:* {q.get('why_it_matters', '')}\n")
    return "\n".join(parts)


# --- Orchestrator ---------------------------------------------------------

@cached(ttl_seconds=CACHE_TTL, key_fn=lambda t: f"report:v1:{t.upper()}")
def compute(ticker: str) -> Report:
    ticker = ticker.upper()

    # Reuse cached upstream results
    th_result = thesis_mod.compute(ticker)
    if th_result.error:
        return Report(ticker=ticker,
                      error=f"thesis unavailable: {th_result.error}")
    th = thesis_mod.to_dict(th_result)

    sp_result = _safe(lambda: speaker_prep_mod.compute(ticker))
    sp_payload = speaker_prep_mod.to_dict(sp_result) if sp_result and not sp_result.error else None

    qs_result = _safe(lambda: quant_score_mod.compute(ticker))
    qs_payload = quant_score_mod.to_dict(qs_result) if qs_result and not qs_result.error else None

    rf_result = _safe(lambda: risk_fw_mod.compute(ticker))
    rf_payload = risk_fw_mod.to_dict(rf_result) if rf_result and not rf_result.error else None

    peers_result = _safe(lambda: peers_mod.compute(ticker))
    peers_payload = peers_mod.to_dict(peers_result) if peers_result else None

    today = date.today().isoformat()
    header = (f"# {ticker} — Investment Research Note\n\n"
              f"_Date: {today} | Source: QuantAnalyzer (model-driven, deterministic)_\n")

    sections = [
        _executive_summary(th),
        _company_overview(th),
        _quantitative_analysis(th, qs_payload),
        _valuation_section(th, peers_payload),
        _catalyst_review(th),
        _risk_analysis(th, rf_payload),
        _scenarios_section(th),
        _conclusion(th),
        _appendix_qa(sp_payload),
    ]

    body = "\n\n".join(sections)
    full = header + "\n" + body

    word_count = len(full.split())
    section_titles = [s.split("\n", 1)[0].lstrip("# ").strip()
                      for s in sections if s.startswith("##")]

    return Report(
        ticker=ticker,
        report_markdown=full,
        word_count=word_count,
        sections=section_titles,
    )


def to_dict(r: Report) -> dict[str, Any]:
    return {
        "ticker": getattr(r, "ticker", None),
        "report_markdown": getattr(r, "report_markdown", ""),
        "word_count": getattr(r, "word_count", 0),
        "sections": getattr(r, "sections", []),
        "error": getattr(r, "error", None),
    }
