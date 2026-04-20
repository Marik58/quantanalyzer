const $ = (sel) => document.querySelector(sel);
const fmtUsd = (v) => v == null ? "—" : v.toLocaleString(undefined, { style: "currency", currency: "USD" });
const fmtPct = (v, digits = 1) => v == null || isNaN(v) ? "—" : (v * 100).toFixed(digits) + "%";
const fmtNum = (v, digits = 2) => v == null || isNaN(v) ? "—" : Number(v).toFixed(digits);

const REGIME_LABEL = {
  uptrend: "Uptrend", downtrend: "Downtrend", ranging: "Ranging",
  breakout_up: "Breakout ↑", breakout_down: "Breakout ↓",
};

function setLoading(on) { $("#loading").classList.toggle("hidden", !on); }

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

function renderSummary(data) {
  const s = data.signal;
  const r = data.risk;
  const name = data.info.shortName || data.info.longName || data.ticker;
  $("#summary-card").innerHTML = `
    <div>
      <div class="ticker">${data.ticker}</div>
      <div class="name">${name}</div>
    </div>
    <div>
      <div class="label">Last price</div>
      <div class="value">${fmtUsd(data.last_price)}</div>
    </div>
    <div>
      <div class="label">Signal</div>
      <div class="value"><span class="badge ${s.action}">${s.action}</span></div>
      <div class="name">Composite ${s.composite >= 0 ? "+" : ""}${s.composite.toFixed(1)}</div>
    </div>
    <div>
      <div class="label">Confidence</div>
      <div class="value">${s.confidence.toFixed(0)}%</div>
    </div>
    <div>
      <div class="label">Risk</div>
      <div class="value"><span class="badge ${r.rating}">${r.rating.toUpperCase()}</span></div>
      <div class="name">${REGIME_LABEL[data.regime.label] || data.regime.label}</div>
    </div>
  `;
}

function renderFactors(data) {
  const rows = data.signal.factors.map(f => `
    <div class="factor-row">
      <div class="name">${f.name}</div>
      <div class="score" style="color:${f.score >= 0 ? 'var(--green)' : 'var(--red)'}">
        ${f.score >= 0 ? "+" : ""}${f.score.toFixed(2)}
      </div>
      <div class="explain">${f.explanation}</div>
    </div>
  `).join("");
  $("#factors").innerHTML = `<h3>Signal inputs</h3>${rows}`;
}

function renderDistribution(data) {
  const d = data.distribution;
  $("#distribution").innerHTML = `
    <h3>Return distribution (2y)</h3>
    <div class="kv"><span class="k">Annualized Sharpe</span><span class="v">${fmtNum(d.sharpe_annual)}</span></div>
    <div class="kv"><span class="k">Daily mean</span><span class="v">${fmtPct(d.mean_daily, 3)}</span></div>
    <div class="kv"><span class="k">Daily stdev</span><span class="v">${fmtPct(d.stdev_daily, 2)}</span></div>
    <div class="kv"><span class="k">Skew</span><span class="v">${fmtNum(d.skew)}</span></div>
    <div class="kv"><span class="k">Excess kurtosis</span><span class="v">${fmtNum(d.kurtosis)}</span></div>
    <div class="kv"><span class="k">Value-at-Risk 95%</span><span class="v">${fmtPct(d.var_95, 2)}</span></div>
    <div class="kv"><span class="k">Value-at-Risk 99%</span><span class="v">${fmtPct(d.var_99, 2)}</span></div>
    <div class="kv"><span class="k">Latest day z-score</span><span class="v">${fmtNum(d.last_return_z)}</span></div>
  `;
}

function renderRisk(data) {
  const r = data.risk;
  const reg = data.regime;
  $("#risk").innerHTML = `
    <h3>Risk &amp; regime</h3>
    <div class="kv"><span class="k">Risk rating</span><span class="v"><span class="badge ${r.rating}">${r.rating.toUpperCase()}</span></span></div>
    <div class="kv"><span class="k">Annualized vol (30d)</span><span class="v">${fmtPct(r.annualized_vol, 0)}</span></div>
    <div class="kv"><span class="k">Max drawdown (1y)</span><span class="v">${fmtPct(r.max_drawdown_1y, 0)}</span></div>
    <div class="kv"><span class="k">Regime</span><span class="v">${REGIME_LABEL[reg.label] || reg.label}</span></div>
    <div class="kv"><span class="k">Regime strength</span><span class="v">${(reg.strength * 100).toFixed(0)}%</span></div>
    <p class="muted" style="margin-top:10px">${reg.description}</p>
  `;
}

function renderBacktest(data) {
  const b = data.backtest;
  const delta = b.signal_return - b.buyhold_return;
  const color = delta >= 0 ? "var(--green)" : "var(--red)";
  $("#backtest").innerHTML = `
    <h3>Signal backtest (≤2y)</h3>
    <div class="kv"><span class="k">Following signal</span><span class="v" style="color:${b.signal_return >= 0 ? 'var(--green)' : 'var(--red)'}">${fmtPct(b.signal_return)}</span></div>
    <div class="kv"><span class="k">Buy &amp; hold</span><span class="v">${fmtPct(b.buyhold_return)}</span></div>
    <div class="kv"><span class="k">Excess return</span><span class="v" style="color:${color}">${fmtPct(delta)}</span></div>
    <div class="kv"><span class="k">Hit rate (long days)</span><span class="v">${fmtPct(b.hit_rate, 0)}</span></div>
    <div class="kv"><span class="k">Sharpe (signal)</span><span class="v">${fmtNum(b.sharpe_signal)}</span></div>
    <div class="kv"><span class="k">Regime changes</span><span class="v">${b.n_trades}</span></div>
  `;
}

function renderReport(data) {
  // Minimal markdown handling: paragraphs, bold, italic, bullet lines
  const md = data.report;
  const html = md.split(/\n\n+/).map(block => {
    if (/^\s*-\s/m.test(block)) {
      const items = block.split(/\n/).filter(l => l.trim().startsWith("- "))
        .map(l => "<li>" + inline(l.replace(/^\s*-\s/, "")) + "</li>").join("");
      return "<ul>" + items + "</ul>";
    }
    return "<p>" + inline(block) + "</p>";
  }).join("");
  $("#report").innerHTML = `<h3>Research report</h3>${html}`;
}
function inline(s) {
  return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/\*(.+?)\*/g, "<em>$1</em>")
          .replace(/_(.+?)_/g, "<em>$1</em>");
}

function renderChart(c) {
  const traces = [
    {
      x: c.dates, open: c.open, high: c.high, low: c.low, close: c.close,
      type: "candlestick", name: c.ticker,
      increasing: { line: { color: "#2ecc71" } },
      decreasing: { line: { color: "#ff5b6b" } },
    },
    { x: c.dates, y: c.sma50,  type: "scatter", mode: "lines", name: "SMA 50",
      line: { color: "#4f8cff", width: 1.5 } },
    { x: c.dates, y: c.sma200, type: "scatter", mode: "lines", name: "SMA 200",
      line: { color: "#f5c542", width: 1.5 } },
    { x: c.dates, y: c.bb_high, type: "scatter", mode: "lines", name: "BB upper",
      line: { color: "#3a4860", width: 1, dash: "dot" } },
    { x: c.dates, y: c.bb_low,  type: "scatter", mode: "lines", name: "BB lower",
      line: { color: "#3a4860", width: 1, dash: "dot" } },
  ];
  const layout = {
    paper_bgcolor: "#131a26", plot_bgcolor: "#131a26",
    font: { color: "#e7ecf3" },
    margin: { l: 50, r: 20, t: 24, b: 30 },
    xaxis: { rangeslider: { visible: false }, gridcolor: "#243049" },
    yaxis: { gridcolor: "#243049" },
    legend: { orientation: "h", y: 1.08 },
    height: 420,
  };
  Plotly.newPlot("chart", traces, layout, { displayModeBar: false, responsive: true });

  const rsiTrace = [
    { x: c.dates, y: c.rsi, type: "scatter", mode: "lines", name: "RSI 14",
      line: { color: "#a78bfa" } },
  ];
  const rsiLayout = {
    paper_bgcolor: "#131a26", plot_bgcolor: "#131a26",
    font: { color: "#e7ecf3" },
    margin: { l: 50, r: 20, t: 24, b: 30 }, height: 200,
    yaxis: { range: [0, 100], gridcolor: "#243049" },
    xaxis: { gridcolor: "#243049" },
    shapes: [
      { type: "line", x0: c.dates[0], x1: c.dates[c.dates.length - 1], y0: 70, y1: 70,
        line: { color: "#ff5b6b", dash: "dot", width: 1 } },
      { type: "line", x0: c.dates[0], x1: c.dates[c.dates.length - 1], y0: 30, y1: 30,
        line: { color: "#2ecc71", dash: "dot", width: 1 } },
    ],
    showlegend: false,
  };
  Plotly.newPlot("rsi-chart", rsiTrace, rsiLayout, { displayModeBar: false, responsive: true });
}

async function analyzeTicker(ticker) {
  ticker = (ticker || "").trim().toUpperCase();
  if (!ticker) return;
  setLoading(true);
  try {
    const [data, chart] = await Promise.all([
      fetchJSON(`/api/analyze/${encodeURIComponent(ticker)}`),
      fetchJSON(`/api/chart/${encodeURIComponent(ticker)}`),
    ]);
    $("#empty-state").classList.add("hidden");
    $("#results").classList.remove("hidden");
    renderSummary(data);
    renderChart(chart);
    renderFactors(data);
    renderDistribution(data);
    renderRisk(data);
    renderBacktest(data);
    renderReport(data);
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    alert("Couldn't analyze " + ticker + ": " + e.message);
  } finally {
    setLoading(false);
  }
}

async function scanWatchlist() {
  setLoading(true);
  try {
    const data = await fetchJSON("/api/watchlist/scan");
    const head = `<div class="wl-row head">
      <div>#</div><div>Ticker</div><div>Price</div>
      <div>Signal</div><div>Opportunity</div>
      <div class="col-hide">Confidence</div><div class="col-hide">Risk</div>
    </div>`;
    const rows = data.results.map((r, i) => `
      <div class="wl-row" data-ticker="${r.ticker}">
        <div class="num">${i + 1}</div>
        <div><div class="ticker">${r.ticker}</div><div class="muted">${r.name}</div></div>
        <div class="opp">${fmtUsd(r.last_price)}</div>
        <div><span class="badge ${r.action}">${r.action}</span></div>
        <div>
          <div class="opp">${r.opportunity.toFixed(1)}</div>
          <div class="opp-bar"><span style="width:${Math.max(2, r.opportunity)}%"></span></div>
        </div>
        <div class="col-hide">${r.confidence.toFixed(0)}%</div>
        <div class="col-hide"><span class="badge ${r.risk}">${r.risk.toUpperCase()}</span></div>
      </div>
    `).join("");
    $("#watchlist-results").innerHTML = head + rows;
    document.querySelectorAll("#watchlist-results .wl-row[data-ticker]").forEach(el => {
      el.addEventListener("click", () => analyzeTicker(el.dataset.ticker));
    });
  } catch (e) {
    alert("Scan failed: " + e.message);
  } finally {
    setLoading(false);
  }
}

$("#ticker-form").addEventListener("submit", (e) => {
  e.preventDefault();
  analyzeTicker($("#ticker-input").value);
});
$("#scan-btn").addEventListener("click", scanWatchlist);
