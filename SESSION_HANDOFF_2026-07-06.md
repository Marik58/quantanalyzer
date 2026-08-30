# Session Handoff — 2026-07-06

**For:** the next chat / session picking up QuantAnalyzer.
**From:** senior-quant code review + "Rigor Sitting #1".
**Read first:** this file, then [PROJECT_STATUS.md](PROJECT_STATUS.md). Older docs
([HANDOFF.md](HANDOFF.md), [NEXT_SESSION.md](NEXT_SESSION.md), [FUNDING_PROPOSAL.md](FUNDING_PROPOSAL.md))
describe the *funded* $500–$1,000 roadmap; the plan below is the **$0–$100 path** toward the
expanded product vision (deep fundamentals, news, historical what-if, paper trading, education).

---

## 0. Ground rules (do not skip)

- **yfinance only** — no paid API keys yet.
- **Windows host, no C++ toolchain** — deps must ship wheels or be pure Python.
- **Incremental** — one module at a time, test/approve before the next.
- **Sign-off required** before modifying `backend/main.py`, `backend/analysis/data.py`, or
  `backend/analysis/signals.py`. New files are fine. Other files: show the diff, then apply.
- **Run procedure** (do NOT use `run.bat`):
  ```
  cd c:\Users\marik\VSCode\quantanalyzer
  .venv\Scripts\activate
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
  ```
  Wait for "Application startup complete." Startup is slow (~10s, heavy imports); ~10s/ticker compute.
- Quick module smoke test without the server:
  `.venv\Scripts\python.exe -c "import backend.analysis.quant_score as q; print(q.compute('AAPL').verdict)"`

---

## 1. What this session did

### 1a. Full code review (grounded in the actual code, app run live)
Verdict: strong **solo-student prototype**, NOT "institutional-grade" (yfinance caps data quality).
Real strengths: explainability everywhere, hardened data layer, honest point-in-time backtest,
graceful weight-renormalization, conflict flags. See §3 for the ranked list of weaknesses with
`file:line` so the next chat doesn't re-derive them.

### 1b. Rigor Sitting #1 — SHIPPED and verified
Goal: make the performance story honest and benchmark-relative before adding features.

**Docs — IR claim downgraded everywhere** (was headlined as "IR ≈ +0.33"; it is **not
statistically meaningful** — cross-sectional IC on 3 correlated mega-cap names is a 3-point rank
correlation). Edited:
- [PROJECT_STATUS.md](PROJECT_STATUS.md) (line ~76)
- [REVIEW_PROMPT.md](REVIEW_PROMPT.md) (line ~55)
- [NEXT_SESSION.md](NEXT_SESSION.md) (line ~92)
- [FUNDING_PROPOSAL.md](FUNDING_PROPOSAL.md) (exec summary + §3.4) — sponsor-facing, now honest.

**Code — reconciled the per-ticker backtest with the live signal + added SPY benchmark:**
- [backend/analysis/backtest.py](backend/analysis/backtest.py):
  - Composite now uses `signals.py` weights (Trend 0.35 / Momentum 0.30 / Vol 0.15) renormalized
    over the 3 factors present (÷0.80), replacing the arbitrary 0.45/0.40/0.15. RSI overbought/
    oversold clamps now match `signals.py` exactly. → the backtest finally measures the SAME
    strategy the Overview tab shows.
  - `run()` takes optional `benchmark_df`; `BacktestResult` gains `spy_return` + `alpha_vs_spy`
    (both default `None`, so all existing callers still work).
- [backend/main.py](backend/main.py): passes `benchmark_df=bench_df` into `run()`; analyze
  payload's `backtest` block now includes `spy_return` and `alpha_vs_spy`.
- [backend/analysis/report.py](backend/analysis/report.py): "Backtest sanity check" paragraph now
  reads "signal vs buy-hold vs SPY (± alpha)" and states it is **in-sample**.

**Verification (live, this session):** AAPL → signal +4.1% vs buy-hold +53.6% vs SPY +42.3%,
**alpha −38.2%**. i.e. the timing signal badly trails just holding — now visible instead of hidden.
No-benchmark path returns `None/None` (backward compatible). Report paragraph renders correctly.

> ⚠️ Finding worth acting on: the reconciled signal underperforms buy-hold AND SPY on AAPL over
> ~2y. Check the rest of the watchlist — the "signal" may be net-negative alpha across the board,
> which would reframe the whole product toward *diagnostics + education* rather than *timing calls*.

---

## 2. Next steps (recommended order — each is one sitting)

### Immediate (finish hardening, then start visible features)
1. **Watchlist alpha check (30 min, net-new script).** Run the reconciled `backtest.run` with SPY
   across all 14 watchlist names; tabulate signal vs buy-hold vs SPY + alpha. Decide whether the
   timing signal earns its place or should be reframed as one input among many. **Do this first —
   it may change the roadmap.**
2. **Single test runner (net-new, mechanical).** `scripts/run_all_tests.py` that imports each
   module, runs one ticker, and *asserts* shape/ranges (the 18 `scripts/test_*.py` only print).
   Needed as a safety net before changing any signal semantics.
3. **Split momentum out of the "valuation" component (needs sign-off — changes score output).**
   `peers.relative_value_score` currently blends 6-month momentum with cheapness and feeds the
   *valuation* slot of the Quant Score → double-counts technical + labels momentum-driven names as
   "cheap." Fix after the test runner exists so regressions are caught. See §3 item 4.

### Then — cheap net-new features (all free on yfinance), in this order
4. **Historical "what-if" / growth-of-$10k** — new `whatif.py` + endpoint + tab. Growth of $X,
   CAGR, max drawdown, vs-SPY. Pure reuse of `data.load`; reuses the SPY-benchmark plumbing from
   this session. *Highest-ROI new feature.*
5. **News panel (display-only)** — `sentiment.py` already fetches + normalizes yfinance news
   (both formats). Surface the raw headlines in their own tab, decoupled from the VADER score.
6. **Paper trading** — new SQLite tables (positions / cash / trades) alongside `db.py`;
   mark-to-market via `data.load`. Split across two sittings (schema+trades, then P&L dashboard).
7. **Education / glossary layer** — harvest the `explanations` dicts every module already emits into
   a glossary + inline "what is this?" tooltips. Mostly frontend/content.

### Paid, only if a ~$100 budget opens up
- **Best single spend:** 1–3 months of **Financial Modeling Prep** (~$22/mo), used to bulk-download
  and cache historical **point-in-time fundamentals + analyst estimates** for the watchlist into
  SQLite, then cancel. This is the ONE thing yfinance can't do and it unblocks an honest
  valuation-inclusive backtest. Verify current pricing before buying.
- Ongoing-cheap alt: **Tiingo** (~$10/mo, prices+news). **Finnhub** free tier already beats
  yfinance for news. Skip Alpha Vantage / Marketstack for this use case.
- **LLM:** ~$10–20 Anthropic credit; wire thesis/report/speaker-prep to fall back to templates when
  no key is set. Claude Haiku 4.5 for per-ticker narrative, Sonnet for the final note. Confirm
  current per-token pricing at build time.
- **Hosting:** Render free tier is fine for a demo; ~$7/mo only if always-on is needed.

---

## 3. Known weaknesses NOT yet fixed (ranked, with locations)

1. **IR/IC still statistically inconclusive** — the *claim* is fixed in docs, but the underlying
   test needs a broad, diverse universe to mean anything. `score_backtest.py:288` (needs ≥3 names;
   watchlist is one sector). Don't quote the number as skill.
2. **Everything is in-sample** — signal weights/thresholds hand-set and evaluated on the same
   names/period (`signals.py:115`, `backtest.py`). No train/test split. Not lookahead, but not
   proven edge either.
3. **`backtest.py` weight mismatch — FIXED this session** (kept here for history).
4. **"Valuation" component double-counts momentum** — `peers.py:66-74` mixes momentum into the
   relative-value score; fed to `quant_score.py:121-135`. → correlates valuation with technical and
   mislabels momentum names as "cheap." (Next-step item 3 above.)
5. **DCF anchors on a single latest-FCF year** — `valuation.py:459`; CAGR from as few as 2 points
   (`valuation.py:179`). Use a 2–3yr average FCF base.
6. **Sentiment is thin** — yfinance `.news` (`sentiment.py:96`) often sparse/empty; VADER
   mis-scores research language (`sentiment.py:318`). Fine as a widget, weak as a 0.10 signal.
7. **Peer sets can collapse** — null yfinance fields dropped (`peers.py:165`); single-valid-peer
   returns percentile 100 (`peers.py:196`). Guard tiny valid-N.
8. **Engineering:** blanket `except Exception` hides real bugs (all `quant_score.py` wrappers) —
   log them; global handler leaks `str(exc)` to client (`main.py` exception handler); duplicated
   legacy frontend (`*.legacy.*`); HMM refits per request so regime labels can flip run-to-run.

---

## 4. Repo map (project files only; ignore `.venv/`)

- `backend/main.py` — FastAPI app, ~25 endpoints (async wrappers over sync compute fns).
- `backend/analysis/` — one module per capability: `data` (yfinance wrapper), `indicators`,
  `signals`, `backtest`, `report`, `distribution`, `regime`, `regime_hmm`, `statistics`,
  `spectral`, `topology`, `manifold`, `risk`, `risk_framework`, `peers`, `sentiment`,
  `quant_score` (aggregator), `score_backtest` (walk-forward), `valuation` (DCF), `catalyst`,
  `thesis`, `speaker_prep`, `report_writer`, `pitch_deck`.
- `backend/db.py` (SQLite watchlist), `backend/cache.py` (disk pickle cache w/ TTL).
- `frontend/` — `index.html` + `app.js` (tabbed Plotly UI); `*.legacy.*` = old single-page (dead).
- `scripts/test_*.py` — 18 manual smoke scripts (print-based, no asserts → see next-step item 2).
- Convention per module: `compute() -> dataclass -> to_dict() -> endpoint`.
