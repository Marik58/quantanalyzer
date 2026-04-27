/* QuantAnalyzer — Phase 3 Step 2
 *
 * Scope: tab switching + ticker capture + Overview tab wired to
 * /api/thesis and /api/analyze (parallel fetch for current price).
 * Other tabs still show their Step-N placeholder.
 */

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// Shared state — last analyzed ticker + cached payloads, so other tabs
// (Steps 3+) can reuse without re-fetching.
const state = {
  ticker: null,
  thesis: null,
  analyze: null,
  quant: null,
  sentiment: null,
  valuation: null,
  risk: null,
  peers: null,
  report: null,
  reportLoading: false,
  scan: null,
  scanLoading: false,
};

// ---------- Formatters ----------
const fmtUsd = (v) =>
  v == null || isNaN(v) ? "—" : Number(v).toLocaleString(undefined, { style: "currency", currency: "USD" });
const fmtPct = (v, digits = 1) =>
  v == null || isNaN(v) ? "—" : (v * 100).toFixed(digits) + "%";
const fmtNum = (v, digits = 2) =>
  v == null || isNaN(v) ? "—" : Number(v).toFixed(digits);

// ---------- Tab switching ----------
function activateTab(tabName) {
  $$(".tab").forEach((btn) => {
    btn.setAttribute("aria-selected", btn.dataset.tab === tabName ? "true" : "false");
  });
  $$(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${tabName}`);
  });
  try { localStorage.setItem("qa_last_tab", tabName); } catch (_) {}

  // Plotly charts rendered while their panel was display:none have zero
  // measured size; trigger a resize when the tab becomes visible.
  if (window.Plotly) {
    requestAnimationFrame(() => {
      $$(".panel.active .plotly-chart").forEach((div) => {
        if (div._fullLayout) Plotly.Plots.resize(div);
      });
    });
  }

  // Report tab is lazy — fetch on first visit per ticker.
  if (tabName === "report" && state.ticker && !state.report && !state.reportLoading) {
    fetchReport(state.ticker);
  }
}

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

try {
  const last = localStorage.getItem("qa_last_tab");
  if (last && $(`#panel-${last}`)) activateTab(last);
} catch (_) {}

// ---------- Status pill ----------
function setStatus(state, text) {
  const pill = $("#status-pill");
  pill.classList.remove("busy", "ok", "err");
  if (state) pill.classList.add(state);
  pill.querySelector(".status-text").textContent = text;
}

// ---------- API helper ----------
async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// ---------- Overview rendering ----------
function setRecBadge(action, conviction) {
  const badge = $("#ov-badge");
  badge.classList.remove("rec-buy", "rec-hold", "rec-sell", "rec-neutral");
  const a = (action || "").toLowerCase();
  if (a === "buy")        badge.classList.add("rec-buy");
  else if (a === "sell")  badge.classList.add("rec-sell");
  else if (a === "hold")  badge.classList.add("rec-hold");
  else                    badge.classList.add("rec-neutral");
  $("#ov-action").textContent = action || "—";
  $("#ov-conviction").textContent = conviction ? `${conviction} conviction` : "—";
}

function setStat(id, value, polarity = null) {
  const el = $(id);
  el.classList.remove("bull", "bear");
  el.textContent = value;
  if (polarity === "bull") el.classList.add("bull");
  if (polarity === "bear") el.classList.add("bear");
}

function renderOverview(thesis, analyze, quant, sentiment) {
  // ---- Hard-error short-circuit: the ticker is almost certainly bogus ----
  // Trigger when ANY of these fundamental signals are missing/empty.
  const noAnalyze   = !analyze;
  const noPrice     = analyze && analyze.last_price == null;
  const noMarketCap = /market cap unavailable/i.test(thesis.company_overview || "");
  const noQuant     = !quant;
  if (noAnalyze || noPrice || (noMarketCap && noQuant)) {
    const reasons = [];
    if (noAnalyze)   reasons.push("price/analysis endpoint failed");
    if (noPrice)     reasons.push("no current price returned");
    if (noMarketCap) reasons.push("yfinance returned no market cap or sector");
    if (noQuant)     reasons.push("quant-score module failed");
    renderOverviewError(
      `"${thesis.ticker}" doesn't appear to be a valid, tradeable ticker. ` +
      `Diagnostics: ${reasons.join("; ")}.`
    );
    return;
  }

  // Hero
  $("#ov-ticker").textContent = thesis.ticker || "—";
  $("#ov-company").textContent = thesis.company_overview || "—";
  $("#ov-price").textContent = analyze && analyze.last_price != null
    ? fmtUsd(analyze.last_price) : "—";

  // Recommendation badge
  const rec = thesis.recommendation || {};
  setRecBadge(rec.action, rec.conviction);

  // Edge + drivers summary
  $("#ov-edge").textContent = thesis.edge || "—";
  const drv = thesis.drivers || {};
  $("#ov-drivers-summary").textContent = drv.summary || "—";

  // ---- Key Stats ----

  // Quant percentile — from /api/quant-score (proper source)
  if (quant && quant.percentile_score != null) {
    const p = quant.percentile_score;
    const tag = p >= 60 ? "bull" : (p <= 40 ? "bear" : null);
    setStat("#stat-qp",
      `${p.toFixed(0)} / 100 — ${quant.verdict || ""}`, tag);
  } else {
    setStat("#stat-qp", "—");
  }

  // DCF upside — from valuation_summary text
  const valText = thesis.valuation_summary || "";
  const upMatch = valText.match(/([+\-−]?\d+)%\s+(upside|downside)/i);
  if (upMatch) {
    const pct = parseInt(upMatch[1].replace("−", "-"), 10);
    const isUp = upMatch[2].toLowerCase() === "upside";
    const signed = (isUp ? "+" : "-") + Math.abs(pct) + "%";
    setStat("#stat-dcf", signed, isUp ? "bull" : "bear");
  } else {
    setStat("#stat-dcf", "—");
  }

  // Sentiment — from /api/sentiment (proper source)
  if (sentiment && sentiment.overall_score != null) {
    const s = sentiment.overall_score;
    const tag = s > 10 ? "bull" : (s < -10 ? "bear" : null);
    const sign = s >= 0 ? "+" : "";
    setStat("#stat-sent",
      `${sign}${s.toFixed(1)} (${sentiment.overall_label || ""})`, tag);
  } else {
    setStat("#stat-sent", "—");
  }

  // Regime — from /api/analyze (legacy regime classification)
  if (analyze && analyze.regime) {
    setStat("#stat-regime", analyze.regime.label || "—");
  } else setStat("#stat-regime", "—");

  // Risk rating — from /api/analyze
  if (analyze && analyze.risk) {
    const rating = analyze.risk.rating || "";
    const tag = rating === "low" ? "bull" : (rating === "high" ? "bear" : null);
    setStat("#stat-risk", rating || "—", tag);
  } else setStat("#stat-risk", "—");

  // Inputs OK — count of "ok" inputs in thesis.inputs_status
  const ist = thesis.inputs_status || {};
  const okCount = Object.values(ist).filter((v) => v === "ok").length;
  const total = Object.keys(ist).length;
  setStat("#stat-inputs", total ? `${okCount}/${total}` : "—",
    total && okCount === total ? "bull" : (okCount < total / 2 ? "bear" : null));

  // ---- Data-quality warning banner ----
  // Trigger: more than half of thesis input modules failed, OR the company
  // overview can't even resolve a sector/industry.
  const lowQuality = (total > 0 && okCount < Math.ceil(total / 2));
  const looksFake = /n\/a \/ n\/a/i.test(thesis.company_overview || "");
  const warn = $("#ov-warn");
  if (lowQuality || looksFake) {
    const reasons = [];
    if (lowQuality) reasons.push(`only ${okCount}/${total} input modules returned data`);
    if (looksFake) reasons.push("yfinance returned no sector/industry — ticker may not exist");
    $("#ov-warn-msg").textContent =
      reasons.join("; ") + ". Treat conclusions with skepticism.";
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  // Show / hide cards
  $("#overview-empty").classList.add("hidden");
  $("#overview-error").classList.add("hidden");
  $("#overview-content").classList.remove("hidden");
}

function renderOverviewError(msg) {
  $("#ov-error-msg").textContent = msg;
  $("#overview-empty").classList.add("hidden");
  $("#overview-content").classList.add("hidden");
  $("#overview-error").classList.remove("hidden");
}

// ---------- Quant tab rendering ----------
function renderQuant(quant) {
  if (!quant) {
    $("#quant-empty").classList.remove("hidden");
    $("#quant-content").classList.add("hidden");
    return;
  }

  // Top metric tiles
  $("#qs-verdict").textContent     = quant.verdict || "—";
  $("#qs-percentile").textContent  = quant.percentile_score != null
    ? `${quant.percentile_score.toFixed(0)} / 100` : "—";
  $("#qs-directional").textContent = quant.directional_score != null
    ? `${quant.directional_score >= 0 ? "+" : ""}${quant.directional_score.toFixed(1)}` : "—";
  $("#qs-confidence").textContent  = quant.confidence != null
    ? `${quant.confidence.toFixed(0)} / 100` : "—";
  $("#qs-active").textContent      = quant.active_weight != null
    ? `${(quant.active_weight * 100).toFixed(0)}%` : "—";

  // Color the verdict + directional cells
  const v = (quant.verdict || "").toLowerCase();
  $("#qs-verdict").className = (v.includes("buy")) ? "bull"
    : (v.includes("avoid") || v.includes("reduce")) ? "bear" : "";
  $("#qs-directional").className = (quant.directional_score > 10) ? "bull"
    : (quant.directional_score < -10) ? "bear" : "";

  // Components — sorted by contribution descending
  const components = [...(quant.components || [])].map((c) => ({
    ...c,
    contribution: c.score == null ? 0 : c.score * c.weight,
  }));
  components.sort((a, b) => b.contribution - a.contribution);

  // Driver headline (mirror what thesis showed, derived locally)
  const positive = components.filter((c) => c.contribution > 1);
  const negative = components.filter((c) => c.contribution < -1);
  let summary;
  if (positive.length && negative.length) {
    summary = `Pulled UP most by ${positive[0].name} (${positive[0].contribution.toFixed(1)} pts), `
            + `DOWN most by ${negative[negative.length - 1].name} `
            + `(${negative[negative.length - 1].contribution.toFixed(1)} pts).`;
  } else if (positive.length) {
    summary = `All directional signals pulling UP — strongest: ${positive[0].name} (${positive[0].contribution.toFixed(1)} pts).`;
  } else if (negative.length) {
    summary = `All directional signals pulling DOWN — strongest drag: ${negative[negative.length - 1].name} `
            + `(${negative[negative.length - 1].contribution.toFixed(1)} pts).`;
  } else {
    summary = "All quant components are roughly neutral — no dominant driver.";
  }
  $("#qs-summary").textContent = summary;

  // Plotly horizontal bar chart
  const labels = components.map((c) => c.name);
  const values = components.map((c) => c.contribution);
  const colors = values.map((v) =>
    v > 1 ? "#22c55e" : v < -1 ? "#ef4444" : "#6b7280"
  );
  const trace = {
    type: "bar",
    orientation: "h",
    x: values,
    y: labels,
    marker: { color: colors },
    text: values.map((v) => (v >= 0 ? "+" : "") + v.toFixed(1)),
    textposition: "outside",
    textfont: { color: "#e5e7eb", size: 11 },
    hovertemplate: "%{y}: %{x:+.2f} pts<extra></extra>",
  };
  const layout = {
    margin: { l: 90, r: 40, t: 10, b: 30 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif", size: 12 },
    xaxis: {
      zeroline: true, zerolinecolor: "#1f2937", zerolinewidth: 2,
      gridcolor: "#1a2236", color: "#9ca3af", title: "Contribution (pts)",
      range: [-25, 25],
    },
    yaxis: {
      autorange: "reversed",  // largest contribution at top
      color: "#e5e7eb",
    },
    showlegend: false,
  };
  Plotly.newPlot("qs-chart", [trace], layout, { displayModeBar: false, responsive: true });

  // Component details table
  const tbody = $("#qs-tbody");
  tbody.innerHTML = "";
  for (const c of components) {
    const tr = document.createElement("tr");
    const scoreTxt = c.score == null ? "n/a" : (c.score >= 0 ? "+" : "") + c.score.toFixed(0);
    const contribCls = c.contribution > 1 ? "bull num" : c.contribution < -1 ? "bear num" : "num";
    tr.innerHTML = `
      <td>${c.name}</td>
      <td class="num">${scoreTxt}</td>
      <td class="num">${(c.weight * 100).toFixed(0)}%</td>
      <td class="${contribCls}">${(c.contribution >= 0 ? "+" : "") + c.contribution.toFixed(1)}</td>
      <td class="muted-cell">${(c.detail || "").substring(0, 80)}</td>
    `;
    tbody.appendChild(tr);
  }

  // Conflicts panel
  const conflicts = quant.conflicts || [];
  const ul = $("#qs-conflicts");
  ul.innerHTML = "";
  if (conflicts.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No internal conflicts flagged — components are broadly aligned.";
    li.style.color = "var(--text-muted)";
    ul.appendChild(li);
  } else {
    for (const c of conflicts) {
      const li = document.createElement("li");
      li.textContent = c;
      ul.appendChild(li);
    }
  }

  $("#quant-empty").classList.add("hidden");
  $("#quant-content").classList.remove("hidden");
}

// ---------- Valuation tab rendering ----------
function renderValuation(val) {
  if (!val || val.method === "unavailable") {
    $("#valuation-empty").classList.remove("hidden");
    $("#valuation-content").classList.add("hidden");
    if (val && val.error) {
      $("#valuation-empty").querySelector("p").textContent =
        `DCF unavailable: ${val.error}`;
    }
    return;
  }

  const price     = val.current_price;
  const intrinsic = val.weighted_intrinsic;
  const upside    = val.weighted_upside_pct;

  // Top metrics
  $("#val-price").textContent     = fmtUsd(price);
  $("#val-intrinsic").textContent = fmtUsd(intrinsic);

  const upEl = $("#val-upside");
  upEl.classList.remove("bull", "bear");
  if (upside != null) {
    upEl.textContent = (upside >= 0 ? "+" : "") + (upside * 100).toFixed(1) + "%";
    upEl.classList.add(upside > 0 ? "bull" : "bear");
  } else {
    upEl.textContent = "—";
  }

  $("#val-rec").textContent      = val.recommendation || "—";
  $("#val-discount").textContent = val.base_discount_rate != null
    ? (val.base_discount_rate * 100).toFixed(1) + "%" : "—";
  $("#val-beta").textContent     = val.base_beta != null ? val.base_beta.toFixed(2) : "—";

  // Reliability warning
  const warn = $("#val-warn");
  if (val.history && val.history.reliability === "low") {
    $("#val-warn-msg").textContent =
      "Historical free cash flow is erratic for this ticker, so the DCF should be "
      + "treated as directional rather than precise. Lean on peer multiples and "
      + "qualitative judgment instead.";
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  // ---- Bar chart: Bull / Base / Bear intrinsic vs current ----
  const scenMap = {};
  for (const s of (val.scenarios || [])) scenMap[s.name] = s;
  const labels = ["Bear", "Base", "Bull", "Current"];
  const values = [
    scenMap.Bear ? scenMap.Bear.intrinsic_per_share : null,
    scenMap.Base ? scenMap.Base.intrinsic_per_share : null,
    scenMap.Bull ? scenMap.Bull.intrinsic_per_share : null,
    price,
  ];
  const colors = ["#ef4444", "#3b82f6", "#22c55e", "#9ca3af"];
  const bar = {
    type: "bar",
    x: labels, y: values,
    marker: { color: colors },
    text: values.map((v) => v != null ? "$" + v.toFixed(2) : ""),
    textposition: "outside",
    textfont: { color: "#e5e7eb", size: 12 },
    hovertemplate: "%{x}: $%{y:.2f}<extra></extra>",
  };
  Plotly.newPlot("val-bar-chart", [bar], {
    margin: { l: 60, r: 30, t: 30, b: 40 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
    yaxis: { gridcolor: "#1a2236", zerolinecolor: "#1f2937", color: "#9ca3af",
             title: "$ per share" },
    xaxis: { color: "#e5e7eb" },
    showlegend: false,
  }, { displayModeBar: false, responsive: true });

  // ---- Scenarios table ----
  const tbody = $("#val-scenarios-tbody");
  tbody.innerHTML = "";
  for (const name of ["Bull", "Base", "Bear"]) {
    const s = scenMap[name];
    if (!s) continue;
    const a = s.assumptions || {};
    const upCls = s.upside_pct == null ? "num" : s.upside_pct > 0 ? "bull num" : "bear num";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${name}</strong></td>
      <td class="num">${a.initial_growth != null ? (a.initial_growth * 100).toFixed(1) + "%" : "—"}</td>
      <td class="num">${a.terminal_growth != null ? (a.terminal_growth * 100).toFixed(1) + "%" : "—"}</td>
      <td class="num">${a.discount_rate != null ? (a.discount_rate * 100).toFixed(1) + "%" : "—"}</td>
      <td class="num">${fmtUsd(s.intrinsic_per_share)}</td>
      <td class="${upCls}">${s.upside_pct != null ? (s.upside_pct >= 0 ? "+" : "") + (s.upside_pct * 100).toFixed(1) + "%" : "—"}</td>
      <td class="num">${s.margin_of_safety != null ? (s.margin_of_safety * 100).toFixed(1) + "%" : "—"}</td>
    `;
    tbody.appendChild(tr);
  }

  // ---- Sensitivity heatmap ----
  const sens = val.sensitivity || [];
  if (sens.length > 0) {
    const discRates = [...new Set(sens.map((c) => c.discount_rate))].sort((a, b) => a - b);
    const termGrowths = [...new Set(sens.map((c) => c.terminal_growth))].sort((a, b) => a - b);

    // Build z matrix [discount][terminal]
    const z = discRates.map((r) =>
      termGrowths.map((g) => {
        const cell = sens.find((c) =>
          Math.abs(c.discount_rate - r) < 1e-9 &&
          Math.abs(c.terminal_growth - g) < 1e-9);
        return cell ? cell.intrinsic_per_share : null;
      })
    );

    const heatmap = {
      type: "heatmap",
      z: z,
      x: termGrowths.map((g) => (g * 100).toFixed(1) + "%"),
      y: discRates.map((r) => (r * 100).toFixed(1) + "%"),
      colorscale: [
        [0,    "#7f1d1d"], [0.25, "#dc2626"], [0.5, "#3b82f6"],
        [0.75, "#22c55e"], [1.0,  "#14532d"],
      ],
      text: z.map((row) => row.map((v) => v != null ? "$" + v.toFixed(0) : "")),
      texttemplate: "%{text}",
      textfont: { color: "#fff", size: 12 },
      hovertemplate: "discount %{y} · terminal g %{x}<br>intrinsic $%{z:.2f}<extra></extra>",
      colorbar: { tickfont: { color: "#9ca3af" } },
    };
    Plotly.newPlot("val-sensitivity", [heatmap], {
      margin: { l: 80, r: 30, t: 20, b: 50 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      xaxis: { title: "Terminal growth →", color: "#e5e7eb", side: "bottom" },
      yaxis: { title: "Discount rate ↓", color: "#e5e7eb", autorange: "reversed" },
    }, { displayModeBar: false, responsive: true });
  }

  $("#valuation-empty").classList.add("hidden");
  $("#valuation-content").classList.remove("hidden");
}

// ---------- Risk tab rendering ----------
function setRiskTextStat(id, value, polarity = null) {
  const el = $(id);
  el.classList.remove("bull", "bear");
  el.textContent = value;
  if (polarity === "bull") el.classList.add("bull");
  if (polarity === "bear") el.classList.add("bear");
}

function renderRisk(rf) {
  if (!rf || rf.error) {
    $("#risk-empty").classList.remove("hidden");
    $("#risk-content").classList.add("hidden");
    if (rf && rf.error) {
      $("#risk-empty").querySelector("p").textContent =
        `Risk framework unavailable: ${rf.error}`;
    }
    return;
  }

  // ---- Top profile tiles ----
  const label = rf.overall_risk_label || "—";
  const score = rf.overall_risk_score;
  const labelTag = label === "Low" ? "bull"
                 : (label === "High" || label === "Extreme") ? "bear"
                 : null;
  setRiskTextStat("#risk-overall",
    score != null ? `${label} (${score.toFixed(0)}/100)` : label, labelTag);

  setRiskTextStat("#risk-beta",
    rf.beta_vs_spy != null ? rf.beta_vs_spy.toFixed(2) : "—",
    rf.beta_vs_spy != null && rf.beta_vs_spy > 1.3 ? "bear"
      : rf.beta_vs_spy != null && rf.beta_vs_spy < 0.8 ? "bull" : null);

  const dd = rf.drawdown || {};
  setRiskTextStat("#risk-maxdd",
    dd.max_drawdown != null ? (dd.max_drawdown * 100).toFixed(1) + "%" : "—", "bear");
  setRiskTextStat("#risk-curdd",
    dd.current_drawdown != null ? (dd.current_drawdown * 100).toFixed(1) + "%" : "—",
    dd.current_drawdown != null && dd.current_drawdown < -0.1 ? "bear" : null);

  const tr = rf.tail_risk || {};
  setRiskTextStat("#risk-var95",
    tr.var_95_historical != null ? (tr.var_95_historical * 100).toFixed(2) + "%" : "—", "bear");

  const k = rf.kelly || {};
  setRiskTextStat("#risk-halfkelly",
    k.half_kelly != null ? (k.half_kelly * 100).toFixed(1) + "%" : "—", null);

  // ---- Stress chart + table ----
  const stress = rf.stress_scenarios || [];
  if (stress.length > 0) {
    const trace = {
      type: "bar",
      x: stress.map((s) => s.name),
      y: stress.map((s) => s.estimated_impact != null ? s.estimated_impact * 100 : null),
      marker: {
        color: stress.map((s) =>
          s.estimated_impact == null ? "#6b7280"
            : s.estimated_impact < -0.2 ? "#7f1d1d"
            : s.estimated_impact < 0    ? "#dc2626"
            : "#22c55e"
        ),
      },
      text: stress.map((s) => s.estimated_impact != null
        ? (s.estimated_impact * 100).toFixed(1) + "%" : "n/a"),
      textposition: "outside",
      textfont: { color: "#e5e7eb", size: 11 },
      hovertemplate: "%{x}: %{y:+.1f}%<extra></extra>",
    };
    Plotly.newPlot("risk-stress-chart", [trace], {
      margin: { l: 60, r: 30, t: 30, b: 70 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      yaxis: { gridcolor: "#1a2236", zerolinecolor: "#1f2937", color: "#9ca3af",
               title: "Estimated impact (%)" },
      xaxis: { color: "#e5e7eb", tickangle: -25 },
      showlegend: false,
    }, { displayModeBar: false, responsive: true });

    const tbody = $("#risk-stress-tbody");
    tbody.innerHTML = "";
    for (const s of stress) {
      const mddTxt = s.market_drawdown != null
        ? (s.market_drawdown * 100).toFixed(1) + "%" : "n/a";
      const impTxt = s.estimated_impact != null
        ? (s.estimated_impact * 100).toFixed(1) + "%" : "n/a";
      const impCls = s.estimated_impact != null && s.estimated_impact < 0
        ? "bear num" : "num";
      const tr_ = document.createElement("tr");
      tr_.innerHTML = `
        <td><strong>${s.name}</strong></td>
        <td class="muted-cell">${s.period || ""}</td>
        <td class="num">${mddTxt}</td>
        <td class="${impCls}">${impTxt}</td>
        <td class="muted-cell">${s.method || ""}</td>
      `;
      tbody.appendChild(tr_);
    }
  }

  // ---- Drawdown chart ----
  if (rf.drawdown) {
    const ddData = [
      { label: "Max drawdown",          v: rf.drawdown.max_drawdown },
      { label: "Current (vs 1Y high)",  v: rf.drawdown.current_drawdown },
      { label: "Worst 3-month",         v: rf.drawdown.worst_3m },
      { label: "Worst 6-month",         v: rf.drawdown.worst_6m },
    ];
    const ddTrace = {
      type: "bar",
      orientation: "h",
      y: ddData.map((d) => d.label),
      x: ddData.map((d) => d.v != null ? d.v * 100 : 0),
      marker: { color: "#ef4444" },
      text: ddData.map((d) => d.v != null ? (d.v * 100).toFixed(1) + "%" : "n/a"),
      textposition: "outside",
      textfont: { color: "#e5e7eb", size: 11 },
      hovertemplate: "%{y}: %{x:.2f}%<extra></extra>",
    };
    Plotly.newPlot("risk-dd-chart", [ddTrace], {
      margin: { l: 170, r: 60, t: 20, b: 40 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      xaxis: { gridcolor: "#1a2236", zerolinecolor: "#1f2937", color: "#9ca3af",
               title: "% from prior peak" },
      yaxis: { color: "#e5e7eb", autorange: "reversed" },
      showlegend: false,
    }, { displayModeBar: false, responsive: true });
  }

  // ---- Tail risk tiles ----
  const fmtTr = (v) => v != null ? (v * 100).toFixed(2) + "%" : "—";
  $("#tr-var95h").textContent  = fmtTr(tr.var_95_historical);
  $("#tr-var99h").textContent  = fmtTr(tr.var_99_historical);
  $("#tr-cvar95").textContent  = fmtTr(tr.cvar_95);
  $("#tr-cvar99").textContent  = fmtTr(tr.cvar_99);
  $("#tr-var95t").textContent  = fmtTr(tr.var_95_student_t);
  $("#tr-tdf").textContent     = tr.student_t_df != null ? tr.student_t_df.toFixed(2) : "—";

  // ---- Macro correlations chart ----
  const macros = rf.macro_correlations || [];
  if (macros.length > 0) {
    const macroTrace = {
      type: "bar",
      orientation: "h",
      y: macros.map((m) => `${m.asset} — ${m.label}`),
      x: macros.map((m) => m.correlation_1y != null ? m.correlation_1y : 0),
      marker: {
        color: macros.map((m) =>
          m.correlation_1y == null ? "#6b7280"
            : m.correlation_1y > 0.3 ? "#22c55e"
            : m.correlation_1y < -0.3 ? "#ef4444"
            : "#3b82f6"
        ),
      },
      text: macros.map((m) => m.correlation_1y != null ? m.correlation_1y.toFixed(2) : "n/a"),
      textposition: "outside",
      textfont: { color: "#e5e7eb", size: 11 },
      hovertemplate: "%{y}: corr %{x:.2f}<br>%{customdata}<extra></extra>",
      customdata: macros.map((m) => m.interpretation || ""),
    };
    Plotly.newPlot("risk-macro-chart", [macroTrace], {
      margin: { l: 220, r: 60, t: 10, b: 40 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      xaxis: { gridcolor: "#1a2236", zerolinecolor: "#1f2937", zerolinewidth: 2,
               color: "#9ca3af", range: [-1, 1] },
      yaxis: { color: "#e5e7eb" },
      showlegend: false,
    }, { displayModeBar: false, responsive: true });
  }

  // ---- Kelly tiles ----
  $("#k-winrate").textContent = k.win_rate != null
    ? (k.win_rate * 100).toFixed(1) + "%" : "—";
  $("#k-avgwin").textContent  = k.avg_win  != null
    ? (k.avg_win * 100).toFixed(2) + "%" : "—";
  $("#k-avgloss").textContent = k.avg_loss != null
    ? (k.avg_loss * 100).toFixed(2) + "%" : "—";
  $("#k-wlratio").textContent = k.win_loss_ratio != null
    ? k.win_loss_ratio.toFixed(2) : "—";
  $("#k-full").textContent    = k.kelly_fraction != null
    ? (k.kelly_fraction * 100).toFixed(1) + "%" : "—";
  $("#k-half").textContent    = k.half_kelly != null
    ? (k.half_kelly * 100).toFixed(1) + "%" : "—";
  $("#k-rec").textContent     = k.recommendation || "—";

  $("#risk-empty").classList.add("hidden");
  $("#risk-content").classList.remove("hidden");
}

// ---------- Peers tab rendering ----------
function renderPeers(peers) {
  if (!peers || (!peers.target_row && (!peers.peer_rows || peers.peer_rows.length === 0))) {
    $("#peers-empty").classList.remove("hidden");
    $("#peers-content").classList.add("hidden");
    return;
  }

  // Top tiles
  const score = peers.relative_value_score;
  const label = peers.relative_value_label || "—";
  const scoreEl = $("#peers-score");
  scoreEl.classList.remove("bull", "bear");
  if (score != null) {
    scoreEl.textContent = `${score.toFixed(0)} / 100`;
    if (score >= 60) scoreEl.classList.add("bull");
    else if (score <= 40) scoreEl.classList.add("bear");
  } else {
    scoreEl.textContent = "—";
  }

  const labelEl = $("#peers-label");
  labelEl.classList.remove("bull", "bear");
  labelEl.textContent = label;
  if (/cheap|attract|underval/i.test(label)) labelEl.classList.add("bull");
  else if (/expens|overval|weak/i.test(label)) labelEl.classList.add("bear");

  $("#peers-group").textContent = peers.group || "—";
  $("#peers-count").textContent = peers.peers_used ? peers.peers_used.length : 0;
  $("#peers-status").textContent = peers.status_note || "";

  // Per-metric formatting — multiples are raw decimals, rates are percents
  const PEER_FMT = {
    pe:        (v) => v.toFixed(2),
    ps:        (v) => v.toFixed(2),
    ev_ebitda: (v) => v.toFixed(2),
    rev_grow:  (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%",
    gross_m:   (v) => (v * 100).toFixed(1) + "%",
    mom_6m:    (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%",
  };
  const fmtMetric = (m, v) => v == null ? "—" : (PEER_FMT[m] || ((x) => x.toFixed(2)))(v);

  // ---- Build comparison table ----
  const metricOrder  = peers.metric_order  || [];
  const metricLabels = peers.metric_labels || {};
  const target       = peers.target_row    || {};
  const peerRows     = peers.peer_rows     || [];

  // Header row
  const theadRow = $("#peers-thead-row");
  theadRow.innerHTML = "<th>Ticker</th>";
  for (const m of metricOrder) {
    const th = document.createElement("th");
    th.textContent = metricLabels[m] || m;
    th.classList.add("num");
    theadRow.appendChild(th);
  }

  // Body rows — target first (highlighted), then peers
  const tbody = $("#peers-tbody");
  tbody.innerHTML = "";
  const allRows = [{ ...target, _isTarget: true }, ...peerRows];
  for (const row of allRows) {
    const tr = document.createElement("tr");
    if (row._isTarget) tr.style.background = "rgba(59, 130, 246, 0.10)";
    let cells = `<td><strong>${row.ticker || "?"}${row._isTarget ? " ★" : ""}</strong></td>`;
    for (const m of metricOrder) {
      // Real shape: row.metrics[m] = { value, rank, percentile, status }
      const mv = row.metrics ? row.metrics[m] : null;
      const v = mv ? mv.value : null;
      // Color the target's cells based on percentile (best in peer set = green)
      let cls = "num";
      if (row._isTarget && mv && mv.percentile != null) {
        if (mv.percentile >= 67) cls = "bull num";
        else if (mv.percentile <= 33) cls = "bear num";
      }
      cells += `<td class="${cls}">${fmtMetric(m, v)}</td>`;
    }
    tr.innerHTML = cells;
    tbody.appendChild(tr);
  }

  // ---- Percentile chart — target's percentile across each metric ----
  // (Mixed-scale metrics like P/E and revenue growth can't share a y-axis;
  // percentile is the meaningful comparison.)
  const targetMetrics = target.metrics || {};
  const chartLabels = [];
  const chartValues = [];
  const chartColors = [];
  for (const m of metricOrder) {
    const mv = targetMetrics[m];
    if (!mv || mv.percentile == null) continue;
    chartLabels.push(metricLabels[m] || m);
    chartValues.push(mv.percentile);
    chartColors.push(
      mv.percentile >= 67 ? "#22c55e"
        : mv.percentile <= 33 ? "#ef4444"
        : "#6b7280"
    );
  }

  if (chartLabels.length > 0) {
    const trace = {
      type: "bar",
      orientation: "h",
      y: chartLabels,
      x: chartValues,
      marker: { color: chartColors },
      text: chartValues.map((v) => v.toFixed(0)),
      textposition: "outside",
      textfont: { color: "#e5e7eb", size: 11 },
      hovertemplate: "%{y}: percentile %{x:.0f} / 100<extra></extra>",
    };
    Plotly.newPlot("peers-chart", [trace], {
      margin: { l: 130, r: 50, t: 20, b: 40 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      xaxis: {
        gridcolor: "#1a2236", zerolinecolor: "#1f2937", color: "#9ca3af",
        range: [0, 110], title: "Target's percentile vs peer set (100 = best)",
      },
      yaxis: { color: "#e5e7eb", autorange: "reversed" },
      shapes: [{
        type: "line", x0: 50, x1: 50, y0: -0.5, y1: chartLabels.length - 0.5,
        line: { color: "#6b7280", width: 1, dash: "dot" },
      }],
      showlegend: false,
    }, { displayModeBar: false, responsive: true });
  }

  $("#peers-empty").classList.add("hidden");
  $("#peers-content").classList.remove("hidden");
}

// ---------- Sentiment tab rendering ----------
function renderSentiment(s) {
  if (!s || s.method === "unavailable") {
    $("#sentiment-empty").classList.remove("hidden");
    $("#sentiment-content").classList.add("hidden");
    if (s && s.error) {
      $("#sentiment-empty").querySelector("p").textContent =
        `Sentiment unavailable: ${s.error}`;
    }
    return;
  }

  // ---- Snapshot tiles ----
  const score = s.overall_score;
  const scoreEl = $("#sent-score");
  scoreEl.classList.remove("bull", "bear");
  if (score != null) {
    scoreEl.textContent = (score >= 0 ? "+" : "") + score.toFixed(1);
    if (score > 15) scoreEl.classList.add("bull");
    else if (score < -15) scoreEl.classList.add("bear");
  } else {
    scoreEl.textContent = "—";
  }

  const labelEl = $("#sent-label");
  labelEl.classList.remove("bull", "bear");
  labelEl.textContent = s.overall_label || "—";
  if (s.overall_label === "bullish") labelEl.classList.add("bull");
  else if (s.overall_label === "bearish") labelEl.classList.add("bear");

  $("#sent-count").textContent = s.headline_count != null ? s.headline_count : "—";

  const ret20 = s.price_return_20d;
  const ret20El = $("#sent-ret20");
  ret20El.classList.remove("bull", "bear");
  if (ret20 != null) {
    ret20El.textContent = (ret20 >= 0 ? "+" : "") + (ret20 * 100).toFixed(1) + "%";
    if (ret20 > 0.02) ret20El.classList.add("bull");
    else if (ret20 < -0.02) ret20El.classList.add("bear");
  } else {
    ret20El.textContent = "—";
  }

  const align = s.alignment_with_price || "—";
  const alignEl = $("#sent-align");
  alignEl.classList.remove("bull", "bear");
  alignEl.textContent = align;
  if (align === "aligned") alignEl.classList.add("bull");
  else if (align === "conflicted") alignEl.classList.add("bear");

  $("#sent-method").textContent = s.method || "—";

  // ---- Trend chart ----
  const trend = s.trend || [];
  if (trend.length > 0) {
    const dates = trend.map((t) => t.date);
    const vals  = trend.map((t) => t.avg_sentiment);
    const counts = trend.map((t) => t.headline_count);

    // Color bars by sign
    const colors = vals.map((v) =>
      v > 0.05 ? "#22c55e" : v < -0.05 ? "#ef4444" : "#6b7280"
    );

    const trace = {
      type: "bar",
      x: dates,
      y: vals,
      marker: { color: colors },
      hovertemplate: "%{x}<br>sentiment: %{y:+.2f}<br>%{customdata} headline(s)<extra></extra>",
      customdata: counts,
    };
    Plotly.newPlot("sent-trend-chart", [trace], {
      margin: { l: 50, r: 30, t: 20, b: 50 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#e5e7eb", family: "-apple-system, Segoe UI, Roboto, sans-serif" },
      xaxis: { color: "#9ca3af", tickangle: -45, gridcolor: "#1a2236" },
      yaxis: { color: "#9ca3af", gridcolor: "#1a2236", zerolinecolor: "#1f2937",
               zerolinewidth: 2, range: [-1, 1], title: "Avg compound score (-1..+1)" },
      showlegend: false,
    }, { displayModeBar: false, responsive: true });
  } else {
    Plotly.purge("sent-trend-chart");
    $("#sent-trend-chart").innerHTML =
      '<p class="muted" style="padding:20px">No trend data available.</p>';
  }

  // ---- Headlines list ----
  const list = $("#sent-headlines");
  list.innerHTML = "";
  const headlines = s.headlines || [];
  if (headlines.length === 0) {
    list.innerHTML = '<p class="muted">No recent headlines returned by yfinance.</p>';
  } else {
    for (const h of headlines.slice(0, 20)) {
      const div = document.createElement("div");
      div.className = "headline " + (
        h.label === "positive" ? "bull"
          : h.label === "negative" ? "bear"
          : ""
      );
      const sign = h.compound >= 0 ? "+" : "";
      const safeTitle = (h.title || "(untitled)")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const safePub = (h.publisher || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const link = h.link || "#";
      const ageHrs = h.age_hours != null ? h.age_hours : null;
      const ageTxt = ageHrs == null ? ""
        : ageHrs < 1   ? `${(ageHrs * 60).toFixed(0)}m ago`
        : ageHrs < 24  ? `${ageHrs.toFixed(1)}h ago`
        : `${(ageHrs / 24).toFixed(1)}d ago`;
      div.innerHTML = `
        <div class="h-score">${sign}${(h.compound || 0).toFixed(2)}</div>
        <div class="h-body">
          <div class="h-title"><a href="${link}" target="_blank" rel="noopener noreferrer">${safeTitle}</a></div>
          <div class="h-meta">${safePub}${ageTxt ? " · " + ageTxt : ""}</div>
        </div>
      `;
      list.appendChild(div);
    }
  }

  $("#sentiment-empty").classList.add("hidden");
  $("#sentiment-content").classList.remove("hidden");
}

// ---------- Report tab rendering ----------
async function fetchReport(ticker) {
  state.reportLoading = true;
  $("#report-empty").classList.add("hidden");
  $("#report-error").classList.add("hidden");
  $("#report-content").classList.add("hidden");
  $("#report-loading").classList.remove("hidden");
  setStatus("busy", `Building report for ${ticker}…`);

  try {
    const r = await fetchJSON(`/api/report/${ticker}`);
    state.report = r;
    renderReport(r, ticker);
    setStatus("ok", `${ticker} loaded`);
  } catch (err) {
    $("#report-loading").classList.add("hidden");
    $("#report-error-msg").textContent = err.message;
    $("#report-error").classList.remove("hidden");
    setStatus("err", `Report error: ${err.message}`);
  } finally {
    state.reportLoading = false;
  }
}

function renderReport(r, ticker) {
  if (!r || !r.report_markdown) {
    $("#report-loading").classList.add("hidden");
    $("#report-error-msg").textContent = "Report came back empty.";
    $("#report-error").classList.remove("hidden");
    return;
  }

  // Meta line
  const wc = r.word_count != null ? `${r.word_count.toLocaleString()} words` : "";
  const sec = (r.sections || []).length;
  $("#report-meta").textContent = `${wc} · ${sec} sections · ticker ${r.ticker || ticker}`;

  // PDF download link
  $("#report-pdf-btn").setAttribute("href", `/api/pitch-deck/${ticker}`);
  $("#report-pdf-btn").setAttribute("download", `${ticker}_pitch_deck.pdf`);

  // Render markdown
  const md = r.report_markdown;
  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: false, headerIds: false });
    $("#report-markdown").innerHTML = marked.parse(md);
  } else {
    // Fallback: show as preformatted text if marked.js failed to load
    $("#report-markdown").innerHTML = `<pre>${md.replace(/[<>&]/g, (c) =>
      ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]))}</pre>`;
  }

  $("#report-loading").classList.add("hidden");
  $("#report-empty").classList.add("hidden");
  $("#report-error").classList.add("hidden");
  $("#report-content").classList.remove("hidden");
}

// Regenerate button — clear cached report and re-fetch
$("#report-refresh").addEventListener("click", () => {
  if (!state.ticker) return;
  state.report = null;
  fetchReport(state.ticker);
});

// ---------- Analyze action ----------
async function analyzeTicker(ticker) {
  if (!ticker) return;
  setStatus("busy", `Loading ${ticker}…`);
  state.ticker = ticker;
  state.thesis = state.analyze = state.quant = state.sentiment
    = state.valuation = state.risk = state.peers = state.report = null;
  state.reportLoading = false;

  // Switch to Overview tab on submit
  activateTab("overview");

  // Seven parallel fetches — all upstream-cached, so usually fast.
  const [thesisRes, analyzeRes, quantRes, sentimentRes,
         valuationRes, riskRes, peersRes] = await Promise.allSettled([
    fetchJSON(`/api/thesis/${ticker}`),
    fetchJSON(`/api/analyze/${ticker}`),
    fetchJSON(`/api/quant-score/${ticker}`),
    fetchJSON(`/api/sentiment/${ticker}`),
    fetchJSON(`/api/valuation/${ticker}`),
    fetchJSON(`/api/risk-framework/${ticker}`),
    fetchJSON(`/api/peers/${ticker}`),
  ]);

  if (thesisRes.status === "rejected") {
    setStatus("err", `Error: ${thesisRes.reason.message}`);
    renderOverviewError(thesisRes.reason.message);
    return;
  }

  state.thesis    = thesisRes.value;
  state.analyze   = analyzeRes.status   === "fulfilled" ? analyzeRes.value   : null;
  state.quant     = quantRes.status     === "fulfilled" ? quantRes.value     : null;
  state.sentiment = sentimentRes.status === "fulfilled" ? sentimentRes.value : null;
  state.valuation = valuationRes.status === "fulfilled" ? valuationRes.value : null;
  state.risk      = riskRes.status      === "fulfilled" ? riskRes.value      : null;
  state.peers     = peersRes.status     === "fulfilled" ? peersRes.value     : null;

  renderOverview(state.thesis, state.analyze, state.quant, state.sentiment);
  renderQuant(state.quant);
  renderValuation(state.valuation);
  renderRisk(state.risk);
  renderPeers(state.peers);
  renderSentiment(state.sentiment);
  setStatus("ok", `${ticker} loaded`);
}

// ---------- Watchlist scan modal ----------
function openScanModal() {
  $("#scan-modal").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  if (!state.scan && !state.scanLoading) fetchScan();
}

function closeScanModal() {
  $("#scan-modal").classList.add("hidden");
  document.body.style.overflow = "";
}

async function fetchScan(force = false) {
  if (state.scanLoading) return;
  if (state.scan && !force) {
    renderScan(state.scan);
    return;
  }
  state.scanLoading = true;
  $("#scan-loading").classList.remove("hidden");
  $("#scan-error").classList.add("hidden");
  $("#scan-table-wrap").classList.add("hidden");

  try {
    const data = await fetchJSON("/api/watchlist/scan");
    state.scan = data;
    renderScan(data);
  } catch (err) {
    $("#scan-loading").classList.add("hidden");
    $("#scan-error-msg").textContent = err.message;
    $("#scan-error").classList.remove("hidden");
  } finally {
    state.scanLoading = false;
  }
}

function renderScan(data) {
  const rows = (data && data.results) || [];
  $("#scan-meta").textContent = rows.length
    ? `${rows.length} ticker(s) ranked by opportunity score`
    : "No results returned by scan endpoint.";

  const tbody = $("#scan-tbody");
  tbody.innerHTML = "";
  rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.dataset.ticker = r.ticker;
    const action = (r.action || "").toUpperCase();
    const actionCls = action === "BUY"  ? "action-cell action-buy"
                    : action === "SELL" ? "action-cell action-sell"
                    : "action-cell action-hold";
    const price = r.last_price != null
      ? "$" + r.last_price.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : "—";
    const opp = r.opportunity != null ? r.opportunity.toFixed(0) : "—";
    const qs  = r.quant_score;
    const qsPct     = qs && qs.percentile != null ? qs.percentile.toFixed(0) : "—";
    const qsVerdict = qs && qs.verdict ? qs.verdict : "—";
    const name = (r.name || "").substring(0, 32);
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td><strong>${r.ticker}</strong></td>
      <td class="muted-cell">${name}</td>
      <td class="num">${price}</td>
      <td class="${actionCls}">${action || "—"}</td>
      <td class="num">${opp}</td>
      <td class="num">${qsPct}</td>
      <td>${qsVerdict}</td>
      <td>${r.regime || "—"}</td>
      <td>${r.risk || "—"}</td>
    `;
    tr.addEventListener("click", () => {
      closeScanModal();
      tickerInput.value = r.ticker;
      analyzeTicker(r.ticker);
    });
    tbody.appendChild(tr);
  });

  $("#scan-loading").classList.add("hidden");
  $("#scan-error").classList.add("hidden");
  $("#scan-table-wrap").classList.remove("hidden");
}

$("#scan-btn").addEventListener("click", openScanModal);
$("#scan-refresh").addEventListener("click", () => fetchScan(true));
document.querySelectorAll("[data-modal-close]").forEach((el) =>
  el.addEventListener("click", closeScanModal));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#scan-modal").classList.contains("hidden")) {
    closeScanModal();
  }
});

// ---------- Form wiring ----------
const tickerForm  = $("#ticker-form");
const tickerInput = $("#ticker-input");

tickerForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const t = tickerInput.value.trim().toUpperCase();
  if (t) analyzeTicker(t);
});

setStatus(null, "Ready — type a ticker");
