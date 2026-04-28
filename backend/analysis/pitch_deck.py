"""Pitch deck PDF — 5-slide research deck for a name.

Slides:
  1. Cover           — ticker, company, price, recommendation badge, quant gauge
  2. Thesis          — edge paragraph + catalyst bullets
  3. Valuation       — DCF intrinsic vs current bar + peer comparison table
  4. Risk            — overall risk + stress scenarios + position sizing
  5. Drivers         — horizontal bar chart of the 9 quant component contributions

Library: reportlab (pure Python, ships wheels on Windows). Reuses the cached
thesis (which already aggregated quant_score / valuation / sentiment / regime
/ catalyst / peers) plus risk_framework directly.

Output goes to data/pitch_decks/<TICKER>_<YYYYMMDD>.pdf and the path is
returned. The endpoint serves it as a FileResponse.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from backend.analysis import data as data_mod
from backend.analysis import peers as peers_mod
from backend.analysis import risk_framework as risk_fw_mod
from backend.analysis import sentiment as sentiment_mod
from backend.analysis import speaker_prep as speaker_prep_mod
from backend.analysis import thesis as thesis_mod
from backend.analysis import valuation as valuation_mod

ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = ROOT / "data" / "pitch_decks"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_W, PAGE_H = landscape(A4)

# Colors
NAVY = colors.HexColor("#0f1f3d")
ACCENT = colors.HexColor("#2563eb")
GREEN = colors.HexColor("#16a34a")
RED = colors.HexColor("#dc2626")
GRAY = colors.HexColor("#6b7280")
LIGHT = colors.HexColor("#f3f4f6")

ACTION_COLOR = {"Buy": GREEN, "Hold": GRAY, "Sell": RED}


@dataclass
class PitchDeck:
    ticker: str
    pdf_path: str | None = None
    error: str | None = None


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _fmt_pct(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _draw_header(c: pdf_canvas.Canvas, ticker: str, slide_num: int, slide_total: int = 11) -> None:
    """Top navy bar with ticker on left, slide counter on right."""
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 1.2 * cm, PAGE_W, 1.2 * cm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * cm, PAGE_H - 0.8 * cm, f"QuantAnalyzer  ·  {ticker}")
    c.setFont("Helvetica", 10)
    c.drawRightString(PAGE_W - 1 * cm, PAGE_H - 0.8 * cm,
                      f"Slide {slide_num} / {slide_total}  ·  {date.today().isoformat()}")


def _draw_footer(c: pdf_canvas.Canvas) -> None:
    c.setFillColor(GRAY)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(1 * cm, 0.6 * cm,
                 "Model-driven research aid. Not investment advice. "
                 "Conclusions are conditional on input data quality.")


# --- Slide 1: Cover ------------------------------------------------------

def _slide_cover(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any]) -> None:
    _draw_header(c, ticker, 1)
    rec = th.get("recommendation", {})
    action = rec.get("action", "n/a")
    conviction = rec.get("conviction", "n/a")
    badge_color = ACTION_COLOR.get(action, GRAY)

    # Big ticker + company name
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 60)
    c.drawString(2 * cm, PAGE_H - 5 * cm, ticker)

    overview = th.get("company_overview", "") or ""
    company_name = overview.split(" — ")[0] if " — " in overview else ticker
    c.setFont("Helvetica", 18)
    c.setFillColor(GRAY)
    c.drawString(2 * cm, PAGE_H - 6.2 * cm, company_name[:60])

    # Recommendation badge
    badge_x, badge_y, badge_w, badge_h = 2 * cm, PAGE_H - 9.5 * cm, 9 * cm, 2.5 * cm
    c.setFillColor(badge_color)
    c.roundRect(badge_x, badge_y, badge_w, badge_h, 0.3 * cm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(badge_x + badge_w / 2, badge_y + badge_h / 2 + 0.2 * cm, action.upper())
    c.setFont("Helvetica", 12)
    c.drawCentredString(badge_x + badge_w / 2, badge_y + 0.5 * cm,
                        f"Conviction: {conviction}")

    # Quant gauge — directional score on a horizontal bar
    drv = th.get("drivers", {})
    qs_components = (drv.get("positive", []) + drv.get("negative", [])
                     + drv.get("neutral_or_missing", []))
    total_contribution = sum(c.get("contribution", 0) for c in qs_components)

    gauge_x, gauge_y, gauge_w, gauge_h = 13 * cm, PAGE_H - 9.5 * cm, 13 * cm, 2.5 * cm
    c.setFillColor(LIGHT)
    c.roundRect(gauge_x, gauge_y, gauge_w, gauge_h, 0.2 * cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(gauge_x + 0.5 * cm, gauge_y + gauge_h - 0.7 * cm,
                 "Aggregate Quant Score (directional, -100 to +100)")

    # Bar
    bar_y = gauge_y + 0.6 * cm
    bar_h = 0.5 * cm
    c.setFillColor(colors.white)
    c.rect(gauge_x + 0.5 * cm, bar_y, gauge_w - 1 * cm, bar_h, fill=1, stroke=1)
    # Mark
    score_clamped = max(-100, min(100, total_contribution))
    mark_x = gauge_x + 0.5 * cm + ((score_clamped + 100) / 200) * (gauge_w - 1 * cm)
    c.setFillColor(badge_color)
    c.rect(mark_x - 0.15 * cm, bar_y - 0.1 * cm, 0.3 * cm, bar_h + 0.2 * cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(mark_x, bar_y - 0.5 * cm, f"{total_contribution:+.1f}")

    # Edge sentence
    edge = th.get("edge", "") or ""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11,
                          textColor=NAVY, leading=15)
    p = Paragraph(edge, body)
    p.wrapOn(c, PAGE_W - 4 * cm, 4 * cm)
    p.drawOn(c, 2 * cm, 2 * cm)

    _draw_footer(c)


# --- Slide: Price History (1 year) --------------------------------------

def _slide_price_history(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any],
                          td, val_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 2)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          textColor=colors.black, leading=13)

    title = Paragraph("Price History — 1 Year", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, PAGE_H - 3 * cm)

    if td is None or td.history is None or td.history.empty:
        no_data = Paragraph("No price history available.", body)
        no_data.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
        no_data.drawOn(c, 2 * cm, PAGE_H - 5 * cm)
        _draw_footer(c)
        return

    # 252 trading days ~ 1 year
    df = td.history.tail(252).copy()
    closes = list(df["Close"].astype(float))
    if not closes:
        _draw_footer(c)
        return

    chart_w, chart_h = PAGE_W - 5 * cm, 11 * cm
    d = Drawing(chart_w, chart_h)
    lp = LinePlot()
    lp.x = 1 * cm
    lp.y = 0.5 * cm
    lp.width = chart_w - 2 * cm
    lp.height = chart_h - 1.5 * cm

    series = [(i, v) for i, v in enumerate(closes)]
    lp.data = [series]
    lp.lines[0].strokeColor = ACCENT
    lp.lines[0].strokeWidth = 1.6
    lp.lines.symbol = makeMarker("Circle", size=0)
    lp.xValueAxis.visible = False
    lp.yValueAxis.labels.fontSize = 9
    lp.yValueAxis.labels.fillColor = GRAY

    cur_price = closes[-1]
    y_min = min(closes) * 0.97
    y_max = max(closes) * 1.03

    intrinsic = None
    if val_payload and val_payload.get("weighted_intrinsic") is not None:
        intrinsic = float(val_payload["weighted_intrinsic"])
        # Clamp into chart range so the marker line stays visible
        y_min = min(y_min, intrinsic * 0.97)
        y_max = max(y_max, intrinsic * 1.03)

    lp.yValueAxis.valueMin = y_min
    lp.yValueAxis.valueMax = y_max
    d.add(lp)

    # Horizontal reference lines: current price + intrinsic
    def _y_pix(val: float) -> float:
        frac = (val - y_min) / (y_max - y_min) if y_max != y_min else 0.5
        return lp.y + frac * lp.height

    d.add(Line(lp.x, _y_pix(cur_price), lp.x + lp.width, _y_pix(cur_price),
               strokeColor=colors.HexColor("#9ca3af"), strokeDashArray=[3, 3],
               strokeWidth=0.7))
    d.add(String(lp.x + lp.width + 0.1 * cm, _y_pix(cur_price) - 3,
                 f"current ${cur_price:,.2f}", fontSize=8, fillColor=colors.HexColor("#6b7280")))

    if intrinsic is not None:
        d.add(Line(lp.x, _y_pix(intrinsic), lp.x + lp.width, _y_pix(intrinsic),
                   strokeColor=GREEN, strokeDashArray=[5, 3], strokeWidth=0.9))
        d.add(String(lp.x + lp.width + 0.1 * cm, _y_pix(intrinsic) - 3,
                     f"DCF intrinsic ${intrinsic:,.2f}", fontSize=8, fillColor=GREEN))

    d.drawOn(c, 2 * cm, 4 * cm)

    # Caption with 52w high/low and YTD return
    high_52 = float(df["Close"].max())
    low_52  = float(df["Close"].min())
    yr_ret  = (closes[-1] / closes[0] - 1.0) if closes[0] else None
    yr_txt  = f"{yr_ret * 100:+.1f}%" if yr_ret is not None else "n/a"
    caption = (f"52-week high ${high_52:,.2f} · low ${low_52:,.2f} · "
               f"1-year return {yr_txt}.")
    cap_p = Paragraph(caption, body)
    cap_p.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    cap_p.drawOn(c, 2 * cm, 2.5 * cm)

    _draw_footer(c)


# --- Slide 3 (was 2): Thesis & Catalysts ---------------------------------

def _slide_thesis(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any]) -> None:
    _draw_header(c, ticker, 3)
    styles = getSampleStyleSheet()

    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11,
                          textColor=colors.black, leading=15)

    y = PAGE_H - 2.5 * cm
    title = Paragraph("Investment Thesis", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, y - 0.8 * cm)

    edge_p = Paragraph(th.get("edge", "") or "", body)
    w, edge_h = edge_p.wrapOn(c, PAGE_W - 4 * cm, 6 * cm)
    edge_p.drawOn(c, 2 * cm, y - 0.8 * cm - edge_h - 0.3 * cm)

    # Catalysts
    cat_y = y - 0.8 * cm - edge_h - 1.5 * cm
    cat_title = Paragraph("Near-term Catalysts", h)
    cat_title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    cat_title.drawOn(c, 2 * cm, cat_y - 0.5 * cm)

    cat_text = th.get("catalysts", "") or "n/a"
    # Split into bullets at sentence boundaries
    sentences = [s.strip() for s in cat_text.replace("...", ".").split(". ")
                 if s.strip()]
    bullet_text = "<br/>".join(f"• {s.rstrip('.')}." for s in sentences[:6])
    cat_p = Paragraph(bullet_text, body)
    w, cat_h = cat_p.wrapOn(c, PAGE_W - 4 * cm, 8 * cm)
    cat_p.drawOn(c, 2 * cm, cat_y - 0.5 * cm - cat_h - 0.3 * cm)

    _draw_footer(c)


# --- Slide 3: Valuation -------------------------------------------------

def _slide_valuation(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any],
                     peers_payload: dict[str, Any] | None,
                     val_payload: dict[str, Any] | None = None) -> None:
    _draw_header(c, ticker, 5)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11,
                          textColor=colors.black, leading=15)

    y = PAGE_H - 2.5 * cm
    title = Paragraph("Valuation", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, y - 0.8 * cm)

    val_p = Paragraph(th.get("valuation_summary", "") or "n/a", body)
    w, val_h = val_p.wrapOn(c, PAGE_W - 4 * cm, 4 * cm)
    val_p.drawOn(c, 2 * cm, y - 0.8 * cm - val_h - 0.3 * cm)

    # ---- Bull / Base / Bear / Current vertical bar chart ----
    if val_payload and val_payload.get("scenarios"):
        scen_map = {s.get("name"): s for s in val_payload["scenarios"]}
        labels = ["Bear", "Base", "Bull", "Current"]
        values = [
            scen_map.get("Bear", {}).get("intrinsic_per_share"),
            scen_map.get("Base", {}).get("intrinsic_per_share"),
            scen_map.get("Bull", {}).get("intrinsic_per_share"),
            val_payload.get("current_price"),
        ]
        if all(v is not None for v in values):
            chart_w_px, chart_h_px = 13 * cm, 6 * cm
            d = Drawing(chart_w_px, chart_h_px)
            chart = VerticalBarChart()
            chart.x = 1.5 * cm
            chart.y = 0.5 * cm
            chart.width = chart_w_px - 2 * cm
            chart.height = chart_h_px - 1.2 * cm
            chart.data = [values]
            chart.categoryAxis.categoryNames = labels
            chart.categoryAxis.labels.fontSize = 9
            chart.valueAxis.labels.fontSize = 8
            chart.valueAxis.valueMin = min(values) * 0.85
            chart.valueAxis.valueMax = max(values) * 1.10
            for i, color in enumerate([RED, ACCENT, GREEN, GRAY]):
                chart.bars[(0, i)].fillColor = color
            chart.barLabels.nudge = 8
            chart.barLabelFormat = "$%0.0f"
            chart.barLabels.fontSize = 8
            d.add(chart)
            d.drawOn(c, 2 * cm, y - 0.8 * cm - val_h - 7 * cm)

    # Peer table
    peers_y = y - 0.8 * cm - val_h - 8.5 * cm
    peers_title = Paragraph("Peer Comparison", h)
    peers_title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    peers_title.drawOn(c, 2 * cm, peers_y - 0.3 * cm)

    if peers_payload and peers_payload.get("peer_rows"):
        target = peers_payload.get("target_row") or {}
        rows_data = [target] + peers_payload["peer_rows"]
        metric_order = (peers_payload.get("metric_order") or [])[:5]
        metric_labels = peers_payload.get("metric_labels") or {}

        pct_metrics = {"rev_grow", "gross_m", "mom_6m"}

        def _fmt_metric(m, v):
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

        header_row = ["Ticker"] + [metric_labels.get(m, m) for m in metric_order]
        table_rows = [header_row]
        for r in rows_data:
            tkr = r.get("ticker", "?")
            metrics = r.get("metrics") or {}
            cells = [tkr]
            for m in metric_order:
                mv = metrics.get(m) or {}
                cells.append(_fmt_metric(m, mv.get("value")))
            table_rows.append(cells)

        col_count = len(header_row)
        col_w = (PAGE_W - 4 * cm) / col_count
        t = Table(table_rows, colWidths=[col_w] * col_count)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("BACKGROUND", (0, 1), (-1, 1), LIGHT),  # highlight target row
            ("GRID", (0, 0), (-1, -1), 0.25, GRAY),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        tw, th_ = t.wrapOn(c, PAGE_W - 4 * cm, 8 * cm)
        t.drawOn(c, 2 * cm, peers_y - 0.5 * cm - th_)
    else:
        no_data = Paragraph("Peer comparison data unavailable.", body)
        no_data.wrapOn(c, PAGE_W - 4 * cm, 1 * cm)
        no_data.drawOn(c, 2 * cm, peers_y - 1.2 * cm)

    _draw_footer(c)


# --- Slide: Bull vs Bear (two-column case map) --------------------------

def _classify(score: float | None, hi: float = 20, lo: float = -20) -> str:
    if score is None:
        return "neutral"
    if score >= hi:
        return "bullish"
    if score <= lo:
        return "bearish"
    return "neutral"


def _extract_bull_bear(th: dict[str, Any], peers_payload: dict[str, Any] | None,
                       rf_payload: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Walk every input and bucket each finding as supports-bull or supports-bear."""
    bull: list[str] = []
    bear: list[str] = []

    drv = th.get("drivers", {}) or {}
    components = (drv.get("positive", []) + drv.get("negative", [])
                  + drv.get("neutral_or_missing", []))

    # Quant components
    for comp in components:
        name = comp.get("name", "?")
        score = comp.get("score")
        if score is None:
            continue
        cls = _classify(score)
        if cls == "bullish":
            bull.append(f"{name.capitalize()} signal positive ({score:+.0f}/100): "
                        f"{comp.get('detail', '')[:80]}")
        elif cls == "bearish":
            bear.append(f"{name.capitalize()} signal negative ({score:+.0f}/100): "
                        f"{comp.get('detail', '')[:80]}")

    # Valuation summary
    val_text = (th.get("valuation_summary") or "").lower()
    if "upside" in val_text and "downside" not in val_text:
        bull.append(f"DCF: {th.get('valuation_summary', '')[:120]}")
    elif "downside" in val_text:
        bear.append(f"DCF: {th.get('valuation_summary', '')[:120]}")

    # Catalysts
    cat_text = th.get("catalysts", "") or ""
    if "Earnings in" in cat_text:
        bear.append("Earnings imminent — binary event risk in either direction.")
    if "constructive" in cat_text:
        bull.append("Sell-side consensus is constructive (analyst targets imply upside).")
    if "cautious" in cat_text:
        bear.append("Sell-side consensus is cautious (analyst targets imply downside).")
    if "upgrade" in cat_text and "downgrade" in cat_text:
        # Try to detect net direction from the text
        if "1 upgrade(s) and 0 downgrade(s)" in cat_text or "2 upgrade(s) and 0 downgrade(s)" in cat_text:
            bull.append("Recent analyst rating changes skew positive.")
        elif "0 upgrade(s)" in cat_text:
            bear.append("Recent analyst rating changes skew negative.")
    if "squeeze setup" in cat_text:
        bull.append("Short interest creates squeeze potential on positive surprises.")

    # Risk framework
    if rf_payload:
        label = rf_payload.get("overall_risk_label", "")
        if label in ("High", "Extreme"):
            bear.append(f"Overall risk profile rated {label} — elevated drawdown probability.")
        elif label == "Low":
            bull.append("Overall risk profile rated Low — favorable risk-adjusted setup.")
        beta = rf_payload.get("beta_vs_spy")
        if beta is not None and beta > 1.3:
            bear.append(f"High beta ({beta:.2f}) — amplified downside in market drawdowns.")
        elif beta is not None and beta < 0.8:
            bull.append(f"Low beta ({beta:.2f}) — defensive characteristics.")

    # Peer relative value
    if peers_payload:
        rv = peers_payload.get("relative_value_score")
        if rv is not None:
            if rv >= 60:
                bull.append(f"Cheap vs. peers (relative-value score {rv:.0f}/100).")
            elif rv <= 40:
                bear.append(f"Expensive vs. peers (relative-value score {rv:.0f}/100).")

    # Conflicts → uncertainty (lands on bearish side as risk to thesis)
    conflicts = drv.get("conflicts") or []  # may not exist; harmless if so
    if conflicts:
        bear.append(f"{len(conflicts)} internal quant conflict(s) — signal confidence lower than headline suggests.")

    if not bull:
        bull.append("No specific bullish drivers — model is not finding directional support.")
    if not bear:
        bear.append("No specific bearish drivers — model is not flagging directional risk.")

    return bull[:8], bear[:8]


def _slide_bull_bear(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any],
                     peers_payload: dict[str, Any] | None,
                     rf_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 4)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          textColor=colors.black, leading=13)
    bull_h = ParagraphStyle("bull_h", parent=styles["Heading3"], textColor=GREEN,
                            fontSize=14, spaceAfter=6)
    bear_h = ParagraphStyle("bear_h", parent=styles["Heading3"], textColor=RED,
                            fontSize=14, spaceAfter=6)

    title = Paragraph("Bull Case vs. Bear Case", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, PAGE_H - 3 * cm)

    bull, bear = _extract_bull_bear(th, peers_payload, rf_payload)

    # Two-column layout
    col_w = (PAGE_W - 6 * cm) / 2
    left_x = 2 * cm
    right_x = 2 * cm + col_w + 2 * cm
    col_top_y = PAGE_H - 4.5 * cm
    col_h = col_top_y - 2 * cm

    # Column backgrounds
    c.setFillColor(colors.HexColor("#ecfdf5"))  # very light green
    c.roundRect(left_x - 0.3 * cm, 1.7 * cm, col_w + 0.6 * cm, col_h + 0.6 * cm,
                0.2 * cm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#fef2f2"))  # very light red
    c.roundRect(right_x - 0.3 * cm, 1.7 * cm, col_w + 0.6 * cm, col_h + 0.6 * cm,
                0.2 * cm, fill=1, stroke=0)

    # Bull column header
    bull_title = Paragraph(f"BULL CASE  ·  {len(bull)} factor(s)", bull_h)
    bull_title.wrapOn(c, col_w, 1 * cm)
    bull_title.drawOn(c, left_x, col_top_y - 0.7 * cm)

    # Bull bullets
    bull_text = "<br/><br/>".join(f"• {b}" for b in bull)
    bull_p = Paragraph(bull_text, body)
    w, ph = bull_p.wrapOn(c, col_w, col_h - 1 * cm)
    bull_p.drawOn(c, left_x, col_top_y - 1.5 * cm - ph)

    # Bear column header
    bear_title = Paragraph(f"BEAR CASE  ·  {len(bear)} factor(s)", bear_h)
    bear_title.wrapOn(c, col_w, 1 * cm)
    bear_title.drawOn(c, right_x, col_top_y - 0.7 * cm)

    bear_text = "<br/><br/>".join(f"• {b}" for b in bear)
    bear_p = Paragraph(bear_text, body)
    w, ph = bear_p.wrapOn(c, col_w, col_h - 1 * cm)
    bear_p.drawOn(c, right_x, col_top_y - 1.5 * cm - ph)

    _draw_footer(c)


# --- Slide 4: Risk -------------------------------------------------------

def _slide_risk(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any],
                rf_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 7)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11,
                          textColor=colors.black, leading=15)

    y = PAGE_H - 2.5 * cm
    title = Paragraph("Risk Analysis", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, y - 0.8 * cm)

    risks_p = Paragraph(th.get("risks", "") or "", body)
    w, risk_h = risks_p.wrapOn(c, PAGE_W - 4 * cm, 4 * cm)
    risks_p.drawOn(c, 2 * cm, y - 0.8 * cm - risk_h - 0.3 * cm)

    if rf_payload and not rf_payload.get("error"):
        # Stress scenarios table
        stress_y = y - 0.8 * cm - risk_h - 1.5 * cm
        stress_title = Paragraph("Historical Stress Scenarios", h)
        stress_title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
        stress_title.drawOn(c, 2 * cm, stress_y - 0.3 * cm)

        stress = rf_payload.get("stress_scenarios") or []
        if stress:
            rows = [["Scenario", "Period", "Market DD", "Estimated Impact"]]
            for s in stress:
                period = (s.get("period") or "").replace("→", "->")
                mdd = s.get("market_drawdown")
                imp = s.get("estimated_impact")
                rows.append([
                    s.get("name", "?"),
                    period,
                    f"{mdd * 100:+.1f}%" if mdd is not None else "n/a",
                    f"{imp * 100:+.1f}%" if imp is not None else "n/a",
                ])
            col_w = (PAGE_W - 4 * cm) / 4
            t = Table(rows, colWidths=[col_w] * 4)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, GRAY),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]))
            tw, th_ = t.wrapOn(c, PAGE_W - 4 * cm, 6 * cm)
            t.drawOn(c, 2 * cm, stress_y - 0.5 * cm - th_)

        # Sizing line at the bottom
        kelly = rf_payload.get("kelly")
        if kelly:
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 11)
            half = kelly.get("half_kelly")
            full = kelly.get("kelly_fraction")
            txt = (f"Position sizing — full Kelly: "
                   f"{full * 100:+.1f}%, half-Kelly: {half * 100:+.1f}%. "
                   f"Overall risk: {rf_payload.get('overall_risk_label', 'n/a')} "
                   f"({rf_payload.get('overall_risk_score', 0):.0f}/100).")
            c.drawString(2 * cm, 2 * cm, txt)

    _draw_footer(c)


# --- Slide 5: Drivers chart ---------------------------------------------

def _interpret_pattern(positive: list[dict], negative: list[dict],
                       neutral: list[dict]) -> str:
    """Plain-English commentary on the *pattern* of component contributions."""
    n_pos = len(positive)
    n_neg = len(negative)
    n_neu = len(neutral)
    total_active = n_pos + n_neg + n_neu

    if total_active == 0:
        return "No active quant components — interpretation unavailable."

    pos_sum = sum(r.get("contribution", 0) for r in positive)
    neg_sum = abs(sum(r.get("contribution", 0) for r in negative))

    # Concentration check — is one component dominating?
    all_active = positive + negative
    if all_active:
        top = max(all_active, key=lambda r: abs(r.get("contribution", 0)))
        rest_sum = sum(abs(r.get("contribution", 0)) for r in all_active
                       if r is not top)
        concentrated = (abs(top["contribution"]) > rest_sum * 1.2
                        and abs(top["contribution"]) > 5)
    else:
        concentrated = False
        top = None

    parts = []
    if n_pos > n_neg + 2:
        parts.append(f"Broadly bullish: {n_pos} of {total_active} components are pulling up "
                     f"vs only {n_neg} pulling down.")
    elif n_neg > n_pos + 2:
        parts.append(f"Broadly bearish: {n_neg} of {total_active} components are pulling down "
                     f"vs only {n_pos} pulling up.")
    elif abs(n_pos - n_neg) <= 1:
        parts.append(f"Mixed picture: {n_pos} bullish components vs {n_neg} bearish — the "
                     f"signal stack is internally divided.")

    if concentrated and top is not None:
        direction = "bullish" if top["contribution"] > 0 else "bearish"
        parts.append(f"The {direction} case is concentrated: '{top['name']}' "
                     f"({top['contribution']:+.1f}) is doing most of the work. "
                     f"If that one signal flips, the thesis is fragile.")

    if pos_sum > 0 and neg_sum > 0:
        ratio = pos_sum / neg_sum if neg_sum > 0 else float("inf")
        if 0.7 <= ratio <= 1.3:
            parts.append(f"Bullish and bearish weights are roughly balanced "
                         f"({pos_sum:.1f} vs {neg_sum:.1f} pts) — explains low conviction.")

    return " ".join(parts) if parts else "Component pattern is neutral with no dominant theme."


def _slide_drivers(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any]) -> None:
    _draw_header(c, ticker, 9)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          textColor=colors.black, leading=13)

    y = PAGE_H - 2.5 * cm
    title = Paragraph("Quant Score — Component Drivers", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, y - 0.8 * cm)

    drv = th.get("drivers", {})
    summary = drv.get("summary") or "Driver breakdown unavailable."
    sum_p = Paragraph(f"<b>Headline:</b> {summary}", body)
    w, sum_h = sum_p.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    sum_p.drawOn(c, 2 * cm, y - 0.8 * cm - sum_h - 0.2 * cm)

    # Build component list
    positive = drv.get("positive", []) or []
    negative = drv.get("negative", []) or []
    neutral = drv.get("neutral_or_missing", []) or []
    all_components = sorted(positive + negative + neutral,
                            key=lambda r: r.get("contribution", 0), reverse=True)

    # Pattern interpretation
    pattern_text = _interpret_pattern(positive, negative, neutral)
    pat_p = Paragraph(f"<b>Pattern interpretation:</b> {pattern_text}", body)
    w, pat_h = pat_p.wrapOn(c, PAGE_W - 4 * cm, 3 * cm)
    pat_p.drawOn(c, 2 * cm, y - 0.8 * cm - sum_h - pat_h - 0.6 * cm)

    if not all_components:
        _draw_footer(c)
        return

    # Horizontal bar chart — sized to fit below the prose
    chart_top_y = y - 0.8 * cm - sum_h - pat_h - 1.2 * cm
    chart_h = chart_top_y - 2 * cm
    chart_w = PAGE_W - 6 * cm
    d = Drawing(chart_w, chart_h)
    chart = HorizontalBarChart()
    chart.x = 4 * cm
    chart.y = 0.5 * cm
    chart.width = chart_w - 5 * cm
    chart.height = chart_h - 1 * cm
    chart.data = [[r.get("contribution", 0) for r in all_components]]
    chart.categoryAxis.categoryNames = [r.get("name", "?") for r in all_components]
    chart.categoryAxis.labels.fontSize = 9
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.valueMin = -25
    chart.valueAxis.valueMax = 25
    chart.bars[0].fillColor = ACCENT
    chart.bars.strokeColor = colors.white
    d.add(chart)
    d.drawOn(c, 3 * cm, 2 * cm)

    _draw_footer(c)


# --- Slide 7: Component-by-component plain-English breakdown ------------

# Per-component interpretation library, keyed by (name, polarity).
# Polarity is "bullish" if score > +20, "bearish" if score < -20, else "neutral".
COMPONENT_PROSE: dict[str, dict[str, str]] = {
    "technical": {
        "bullish": ("Price action, moving averages, and momentum oscillators (MACD, RSI) "
                    "are aligned to the upside. Trend-following systems would be long here."),
        "neutral": ("Price/momentum signals are mixed — no clear directional bias from "
                    "trend-following systems. A name to watch rather than press."),
        "bearish": ("Price action, moving averages, and momentum oscillators are aligned "
                    "to the downside. Trend-following systems would be short or flat."),
    },
    "regime": {
        "bullish": ("The Hidden Markov Model places this name in a Bull regime — historical "
                    "returns in this state are positive on average and volatility is contained."),
        "neutral": ("The HMM places this name in a Sideways/transitional regime — no strong "
                    "directional bias from the macro-state classifier."),
        "bearish": ("The HMM places this name in a Bear or Volatile regime — historical "
                    "returns in this state are negative and drawdown risk is elevated."),
    },
    "valuation": {
        "bullish": ("Relative-value screen (P/E, P/S, EV/EBITDA, growth, margin) ranks this "
                    "name as cheap vs. its peer group — fundamentals support a higher multiple."),
        "neutral": ("Relative-value screen places this name roughly in line with its peer "
                    "group — no clear value or growth dislocation."),
        "bearish": ("Relative-value screen ranks this name as expensive vs. its peer group — "
                    "current multiple is hard to justify on growth/margin metrics."),
    },
    "sentiment": {
        "bullish": ("News flow is net positive (VADER sentiment on recent headlines). "
                    "Narrative momentum supports the price action."),
        "neutral": ("News flow is mixed or thin — no strong narrative driving the stock "
                    "in either direction right now."),
        "bearish": ("News flow is net negative. Narrative is working against the price — "
                    "watch for a sentiment turn as a contrarian setup."),
    },
    "statistics": {
        "bullish": ("Risk-adjusted return ratios (Sortino, Calmar, Omega) are healthy — "
                    "this name has been delivering returns in excess of the pain it inflicts."),
        "neutral": ("Risk-adjusted ratios are mediocre — returns and volatility are roughly "
                    "in balance, no excess compensation for the risk taken."),
        "bearish": ("Risk-adjusted ratios are weak — returns have not justified the volatility "
                    "and drawdowns this name has produced."),
    },
    "spectral": {
        "bullish": ("Cyclic decomposition (FFT/wavelet) shows the price in the early phase of "
                    "its dominant cycle — historically a good entry zone."),
        "neutral": ("Cyclic structure is weak or non-stationary — the spectral signal isn't "
                    "providing a strong timing edge right now."),
        "bearish": ("Cyclic decomposition shows the price near the peak of its dominant cycle "
                    "— historically a zone where mean-reversion takes over."),
    },
    "topology": {
        "bullish": ("Topological data analysis (TDA / persistent homology) detects a stable "
                    "cyclic structure consistent with continued price expansion."),
        "neutral": ("TDA shape signal is weak — no strong topological structure to lean on."),
        "bearish": ("Topological analysis detects deteriorating shape stability — the price "
                    "manifold is breaking down, often a precursor to regime change."),
    },
    "risk": {
        "bullish": ("Drawdown profile, tail risk (VaR/CVaR), and Kelly sizing all suggest a "
                    "favorable risk-adjusted setup — position can be sized confidently."),
        "neutral": ("Risk profile is moderate — neither a particular advantage nor a red flag."),
        "bearish": ("Drawdown profile, tail risk, or Kelly sizing flag elevated risk — even if "
                    "the directional view is right, position must be sized down."),
    },
}


def _component_polarity(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score >= 20:
        return "bullish"
    if score <= -20:
        return "bearish"
    return "neutral"


def _slide_component_deep_dive(c: pdf_canvas.Canvas, ticker: str, th: dict[str, Any]) -> None:
    _draw_header(c, ticker, 10)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8.5,
                          textColor=colors.black, leading=11)

    y = PAGE_H - 2.5 * cm
    title = Paragraph("Quant Findings — Component Deep Dive", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, y - 0.8 * cm)

    drv = th.get("drivers", {})
    components = (drv.get("positive", []) + drv.get("negative", [])
                  + drv.get("neutral_or_missing", []))

    if not components:
        no_data = Paragraph("Component data unavailable.", body)
        no_data.wrapOn(c, PAGE_W - 4 * cm, 1 * cm)
        no_data.drawOn(c, 2 * cm, y - 3 * cm)
        _draw_footer(c)
        return

    # Build a one-row-per-component table:
    # [Name + tag] | [Score / Weight / Contribution] | [Plain-English interpretation]
    rows = [["Component", "Polarity", "Score", "Wt", "Contrib", "What it means / Raw signal"]]
    cell_styles = []
    for i, comp in enumerate(components, start=1):
        name = (comp.get("name") or "?").capitalize()
        score = comp.get("score")
        polarity = _component_polarity(score)
        polarity_tag = polarity.upper()
        score_txt = f"{score:+.0f}" if score is not None else "n/a"
        weight = comp.get("weight", 0)
        contrib = comp.get("contribution", 0)
        prose = COMPONENT_PROSE.get(comp.get("name", ""), {}).get(polarity,
                "(no interpretation library entry for this signal)")
        raw = comp.get("detail", "")
        prose_p = Paragraph(f"{prose}<br/><font color='#6b7280' size='7'>"
                            f"<i>Raw: {raw}</i></font>", body)
        rows.append([name, polarity_tag, score_txt, f"{weight:.2f}",
                     f"{contrib:+.1f}", prose_p])
        # Color the polarity cell
        if polarity == "bullish":
            cell_styles.append(("TEXTCOLOR", (1, i), (1, i), GREEN))
            cell_styles.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
        elif polarity == "bearish":
            cell_styles.append(("TEXTCOLOR", (1, i), (1, i), RED))
            cell_styles.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
        else:
            cell_styles.append(("TEXTCOLOR", (1, i), (1, i), GRAY))

    col_widths = [2.5 * cm, 2 * cm, 1.5 * cm, 1.2 * cm, 1.8 * cm, PAGE_W - 13 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    base_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, GRAY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(base_style + cell_styles))
    tw, th_ = t.wrapOn(c, PAGE_W - 4 * cm, PAGE_H - 6 * cm)
    t.drawOn(c, 2 * cm, y - 1.5 * cm - th_)

    _draw_footer(c)





# --- Slide 6: DCF sensitivity heatmap (table-based) ---------------------

def _heatmap_color(v: float, vmin: float, vmax: float) -> colors.Color:
    """Diverging red→blue→green colormap for a heatmap cell."""
    if v is None or vmax == vmin:
        return colors.HexColor("#374151")
    t = max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
    if t < 0.5:
        # Red (#7f1d1d) -> Blue (#3b82f6)
        f = t * 2
        r = int(127 * (1 - f) + 59 * f)
        g = int(29  * (1 - f) + 130 * f)
        b = int(29  * (1 - f) + 246 * f)
    else:
        # Blue (#3b82f6) -> Green (#14532d)
        f = (t - 0.5) * 2
        r = int(59  * (1 - f) + 20 * f)
        g = int(130 * (1 - f) + 83 * f)
        b = int(246 * (1 - f) + 45 * f)
    return colors.Color(r / 255, g / 255, b / 255)


def _slide_sensitivity(c: pdf_canvas.Canvas, ticker: str,
                       val_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 6)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          textColor=colors.black, leading=13)

    title = Paragraph("DCF Sensitivity — Discount Rate × Terminal Growth", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, PAGE_H - 3 * cm)

    sub = Paragraph(
        "Each cell shows the intrinsic value per share at that combination. "
        "Far-apart colors across the grid = your DCF is fragile to a small change "
        "in either assumption.", body)
    sub.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    sub.drawOn(c, 2 * cm, PAGE_H - 4.2 * cm)

    if not val_payload or not val_payload.get("sensitivity"):
        Paragraph("Sensitivity data unavailable.", body).drawOn(c, 2 * cm, PAGE_H - 6 * cm)
        _draw_footer(c)
        return

    sens = val_payload["sensitivity"]
    disc_rates = sorted({c["discount_rate"] for c in sens})
    term_growths = sorted({c["terminal_growth"] for c in sens})
    values = [c["intrinsic_per_share"] for c in sens if c["intrinsic_per_share"] is not None]
    if not values:
        _draw_footer(c)
        return
    vmin, vmax = min(values), max(values)

    # Build the table: row 0 = headers (terminal growths). Column 0 = discount rates.
    header_row = ["r \\ g →"] + [f"{g * 100:+.1f}%" for g in term_growths]
    rows = [header_row]
    cell_styles = []
    for ri, r in enumerate(disc_rates, start=1):
        row = [f"{r * 100:.1f}%"]
        for gi, g in enumerate(term_growths, start=1):
            cell = next((c for c in sens
                         if abs(c["discount_rate"] - r) < 1e-9
                         and abs(c["terminal_growth"] - g) < 1e-9), None)
            v = cell["intrinsic_per_share"] if cell else None
            row.append(f"${v:,.0f}" if v is not None else "n/a")
            if v is not None:
                cell_styles.append(("BACKGROUND", (gi, ri), (gi, ri),
                                    _heatmap_color(v, vmin, vmax)))
                cell_styles.append(("TEXTCOLOR", (gi, ri), (gi, ri), colors.white))
        rows.append(row)

    n_cols = len(header_row)
    col_w = (PAGE_W - 6 * cm) / n_cols
    t = Table(rows, colWidths=[col_w] * n_cols, rowHeights=[1.0 * cm] * len(rows))
    base = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (0, -1), LIGHT),
        ("TEXTCOLOR", (0, 1), (0, -1), NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
    ]
    t.setStyle(TableStyle(base + cell_styles))
    tw, th_ = t.wrapOn(c, PAGE_W - 6 * cm, 12 * cm)
    t.drawOn(c, 3 * cm, PAGE_H - 5.5 * cm - th_)

    # Caption with the diagonal
    if val_payload.get("weighted_intrinsic") is not None:
        wi = val_payload["weighted_intrinsic"]
        cap = Paragraph(
            f"<b>Probability-weighted intrinsic value:</b> ${wi:,.2f}/share. "
            f"Read top-left for the conservative case (high discount, low growth) "
            f"and bottom-right for the aggressive case.", body)
        cap.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
        cap.drawOn(c, 2 * cm, 2 * cm)

    _draw_footer(c)


# --- Slide 8: Tail risk + macro correlations -----------------------------

def _slide_tail_macro(c: pdf_canvas.Canvas, ticker: str,
                      rf_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 8)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10,
                          textColor=colors.black, leading=13)
    sub = ParagraphStyle("sub", parent=styles["BodyText"], fontSize=11,
                         textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=6)

    title = Paragraph("Tail Risk & Macro Correlations", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, PAGE_H - 3 * cm)

    if not rf_payload:
        Paragraph("Risk framework data unavailable.", body).drawOn(c, 2 * cm, PAGE_H - 5 * cm)
        _draw_footer(c)
        return

    # ---- LEFT: Tail risk numbers ----
    left_x = 2 * cm
    col_w = (PAGE_W - 6 * cm) / 2

    Paragraph("Tail Risk (daily, % of position)", sub).wrapAndDraw = None
    sub_p = Paragraph("Tail Risk — Daily Loss Estimates", sub)
    sub_p.wrapOn(c, col_w, 1 * cm)
    sub_p.drawOn(c, left_x, PAGE_H - 5 * cm)

    tr = rf_payload.get("tail_risk") or {}
    tr_rows = [
        ["Metric", "Value", "What it means"],
        ["VaR 95% (historical)", _fmt_pct(tr.get("var_95_historical")),
         "Loss exceeded 5% of trading days"],
        ["VaR 99% (historical)", _fmt_pct(tr.get("var_99_historical")),
         "Loss exceeded 1% of trading days"],
        ["CVaR 95%", _fmt_pct(tr.get("cvar_95")),
         "Average loss when in the 5% tail"],
        ["CVaR 99%", _fmt_pct(tr.get("cvar_99")),
         "Average loss when in the 1% tail"],
        ["VaR 95% (Student-t)", _fmt_pct(tr.get("var_95_student_t")),
         "Parametric estimate (fat tails)"],
        ["Student-t df", f"{tr.get('student_t_df'):.1f}" if tr.get("student_t_df") else "n/a",
         "Lower = fatter tails (df<6 is risky)"],
    ]
    tr_table = Table(tr_rows, colWidths=[3.5 * cm, 2.2 * cm, col_w - 5.7 * cm])
    tr_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, GRAY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    tw, th_ = tr_table.wrapOn(c, col_w, 12 * cm)
    tr_table.drawOn(c, left_x, PAGE_H - 6 * cm - th_)

    # ---- RIGHT: Macro correlations chart ----
    right_x = 2 * cm + col_w + 2 * cm

    sub_r = Paragraph("Macro Correlations (1-year)", sub)
    sub_r.wrapOn(c, col_w, 1 * cm)
    sub_r.drawOn(c, right_x, PAGE_H - 5 * cm)

    macros = rf_payload.get("macro_correlations") or []
    if macros:
        chart_w_px, chart_h_px = col_w, 9 * cm
        d = Drawing(chart_w_px, chart_h_px)
        chart = HorizontalBarChart()
        chart.x = 4 * cm
        chart.y = 0.5 * cm
        chart.width = chart_w_px - 4.5 * cm
        chart.height = chart_h_px - 1.5 * cm
        vals = [m.get("correlation_1y") if m.get("correlation_1y") is not None else 0
                for m in macros]
        chart.data = [vals]
        chart.categoryAxis.categoryNames = [m.get("asset", "?") for m in macros]
        chart.categoryAxis.labels.fontSize = 10
        chart.valueAxis.labels.fontSize = 9
        chart.valueAxis.valueMin = -1
        chart.valueAxis.valueMax = 1
        for i, m in enumerate(macros):
            corr = m.get("correlation_1y")
            color = (GREEN if corr is not None and corr > 0.3 else
                     RED if corr is not None and corr < -0.3 else
                     ACCENT)
            chart.bars[(0, i)].fillColor = color
        chart.bars.strokeColor = colors.white
        d.add(chart)
        d.drawOn(c, right_x, PAGE_H - 6 * cm - chart_h_px)

    # ---- Bottom interpretation strip ----
    interp = (
        "<b>How to read:</b> CVaR is the more honest tail metric — VaR tells you the cutoff, "
        "CVaR tells you the average loss <i>once you're in the tail</i>. SPY correlation &gt;0.7 "
        "means this name is essentially a long-the-market trade. Strong negative TLT correlation "
        "means you're betting against rates as much as on the company."
    )
    interp_p = Paragraph(interp, body)
    interp_p.wrapOn(c, PAGE_W - 4 * cm, 3 * cm)
    interp_p.drawOn(c, 2 * cm, 1.8 * cm)

    _draw_footer(c)


# --- Slide 11: Sentiment trend + Q&A appendix ----------------------------

def _slide_sentiment_qa(c: pdf_canvas.Canvas, ticker: str,
                        sent_payload: dict[str, Any] | None,
                        sp_payload: dict[str, Any] | None) -> None:
    _draw_header(c, ticker, 11)
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], textColor=NAVY,
                       fontSize=18, spaceAfter=8)
    sub = ParagraphStyle("sub", parent=styles["BodyText"], fontSize=11,
                         textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=6)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9,
                          textColor=colors.black, leading=12)

    title = Paragraph("Sentiment & Speaker-Prep Q&amp;A", h)
    title.wrapOn(c, PAGE_W - 4 * cm, 2 * cm)
    title.drawOn(c, 2 * cm, PAGE_H - 3 * cm)

    # ---- LEFT half: sentiment trend chart ----
    left_x = 2 * cm
    col_w = (PAGE_W - 6 * cm) / 2

    Paragraph("News Sentiment — Daily Trend (last 30 days)", sub).wrapOn(c, col_w, 1 * cm)
    sub_l = Paragraph("News Sentiment — Daily Trend (last 30 days)", sub)
    sub_l.wrapOn(c, col_w, 1 * cm)
    sub_l.drawOn(c, left_x, PAGE_H - 4.5 * cm)

    if sent_payload and sent_payload.get("trend"):
        trend = sent_payload["trend"]
        chart_w_px, chart_h_px = col_w, 8 * cm
        d = Drawing(chart_w_px, chart_h_px)
        chart = VerticalBarChart()
        chart.x = 1.2 * cm
        chart.y = 1 * cm
        chart.width = chart_w_px - 1.5 * cm
        chart.height = chart_h_px - 2 * cm
        vals = [t.get("avg_sentiment", 0) for t in trend]
        chart.data = [vals]
        chart.categoryAxis.categoryNames = [
            (t.get("date") or "")[5:] for t in trend  # MM-DD
        ]
        chart.categoryAxis.labels.fontSize = 6
        chart.categoryAxis.labels.angle = 90
        chart.valueAxis.labels.fontSize = 8
        chart.valueAxis.valueMin = -1
        chart.valueAxis.valueMax = 1
        for i, v in enumerate(vals):
            color = (GREEN if v > 0.05 else
                     RED if v < -0.05 else
                     GRAY)
            chart.bars[(0, i)].fillColor = color
        d.add(chart)
        d.drawOn(c, left_x, PAGE_H - 5 * cm - chart_h_px)

        # Sentiment summary line
        score = sent_payload.get("overall_score")
        label = sent_payload.get("overall_label", "—")
        align = sent_payload.get("alignment_with_price", "—")
        ret20 = sent_payload.get("price_return_20d")
        score_txt = f"{score:+.1f}" if score is not None else "n/a"
        ret_txt   = f"{ret20 * 100:+.1f}%" if ret20 is not None else "n/a"
        summary = (f"<b>Overall:</b> {score_txt} ({label}). "
                   f"<b>20d return:</b> {ret_txt}. "
                   f"<b>Tape vs. news:</b> {align}.")
        sum_p = Paragraph(summary, body)
        sum_p.wrapOn(c, col_w, 2 * cm)
        sum_p.drawOn(c, left_x, PAGE_H - 5 * cm - chart_h_px - 1.2 * cm)
    else:
        Paragraph("Sentiment data unavailable.", body).drawOn(c, left_x, PAGE_H - 6 * cm)

    # ---- RIGHT half: Speaker prep Q&A ----
    right_x = 2 * cm + col_w + 2 * cm
    sub_r = Paragraph("PM Q&amp;A — questions to answer before pitching", sub)
    sub_r.wrapOn(c, col_w, 1 * cm)
    sub_r.drawOn(c, right_x, PAGE_H - 4.5 * cm)

    if sp_payload and sp_payload.get("questions"):
        qs = sp_payload["questions"][:5]
        y_cursor = PAGE_H - 5.3 * cm
        for i, q in enumerate(qs, start=1):
            q_text = (q.get("question") or "").strip()
            why    = (q.get("why_it_matters") or "").strip()
            block  = (f"<b>Q{i}.</b> {q_text}<br/>"
                      f"<font color='#6b7280' size='8'><i>{why}</i></font>")
            p = Paragraph(block, body)
            tw, th_ = p.wrapOn(c, col_w, 4 * cm)
            p.drawOn(c, right_x, y_cursor - th_)
            y_cursor -= th_ + 0.3 * cm
    else:
        Paragraph("Q&amp;A data unavailable.", body).drawOn(c, right_x, PAGE_H - 6 * cm)

    _draw_footer(c)


# --- Orchestrator -------------------------------------------------------

def compute(ticker: str) -> PitchDeck:
    ticker = ticker.upper()

    th_result = thesis_mod.compute(ticker)
    if th_result.error:
        return PitchDeck(ticker=ticker,
                         error=f"thesis unavailable: {th_result.error}")
    th = thesis_mod.to_dict(th_result)

    peers_result = _safe(lambda: peers_mod.compute(ticker))
    peers_payload = peers_mod.to_dict(peers_result) if peers_result else None

    rf_result = _safe(lambda: risk_fw_mod.compute(ticker))
    rf_payload = (risk_fw_mod.to_dict(rf_result)
                  if rf_result and not rf_result.error else None)

    val_result = _safe(lambda: valuation_mod.compute(ticker))
    val_payload = (valuation_mod.to_dict(val_result)
                   if val_result and val_result.method != "unavailable" else None)

    sent_result = _safe(lambda: sentiment_mod.compute(ticker))
    sent_payload = (sentiment_mod.to_dict(sent_result)
                    if sent_result and not sent_result.error else None)

    sp_result = _safe(lambda: speaker_prep_mod.compute(ticker))
    sp_payload = (speaker_prep_mod.to_dict(sp_result)
                  if sp_result and not sp_result.error else None)

    td = _safe(lambda: data_mod.load(ticker))

    out_path = OUTPUT_DIR / f"{ticker}_{date.today().strftime('%Y%m%d')}.pdf"
    c = pdf_canvas.Canvas(str(out_path), pagesize=landscape(A4))
    c.setTitle(f"{ticker} — QuantAnalyzer Pitch Deck")
    c.setAuthor("QuantAnalyzer")

    _slide_cover(c, ticker, th)
    c.showPage()
    _slide_price_history(c, ticker, th, td, val_payload)
    c.showPage()
    _slide_thesis(c, ticker, th)
    c.showPage()
    _slide_bull_bear(c, ticker, th, peers_payload, rf_payload)
    c.showPage()
    _slide_valuation(c, ticker, th, peers_payload, val_payload)
    c.showPage()
    _slide_sensitivity(c, ticker, val_payload)
    c.showPage()
    _slide_risk(c, ticker, th, rf_payload)
    c.showPage()
    _slide_tail_macro(c, ticker, rf_payload)
    c.showPage()
    _slide_drivers(c, ticker, th)
    c.showPage()
    _slide_component_deep_dive(c, ticker, th)
    c.showPage()
    _slide_sentiment_qa(c, ticker, sent_payload, sp_payload)
    c.showPage()
    c.save()

    return PitchDeck(ticker=ticker, pdf_path=str(out_path))


def to_dict(p: PitchDeck) -> dict[str, Any]:
    return {
        "ticker": getattr(p, "ticker", None),
        "pdf_path": getattr(p, "pdf_path", None),
        "error": getattr(p, "error", None),
    }
