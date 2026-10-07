"""Single test runner — asserts shape & range invariants for every analysis module.

Unlike the 18 `scripts/test_*.py` (which only *print*), this *asserts* and exits
non-zero on any failure, so it can gate signal-semantics changes. It loads one
ticker (AAPL) + SPY ONCE and reuses them across modules, so the whole suite is a
handful of yfinance fetches, not one per module.

Run from the repo root with the venv active:

    .venv\\Scripts\\python.exe scripts\\run_all_tests.py            # fast per-ticker modules
    .venv\\Scripts\\python.exe scripts\\run_all_tests.py --full     # + slow walk-forward

Exit code 0 = all green, 1 = at least one module failed its invariants.
"""
from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252, which cannot print the arrows/glyphs
# in module output. Force UTF-8 so the scripts run anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

from backend.analysis import (  # noqa: E402
    backtest as backtest_mod,
    catalyst as catalyst_mod,
    data as data_mod,
    distribution as dist_mod,
    indicators as ind_mod,
    manifold as manifold_mod,
    peers as peers_mod,
    regime as regime_mod,
    regime_hmm as regime_hmm_mod,
    risk as risk_mod,
    sentiment as sentiment_mod,
    signals as signals_mod,
    spectral as spectral_mod,
    statistics as stats_mod,
    topology as topology_mod,
    valuation as valuation_mod,
)
from backend.analysis import quant_score as quant_score_mod  # noqa: E402
from backend.analysis import score_backtest as score_bt_mod  # noqa: E402
from backend.analysis import crisis as crisis_mod  # noqa: E402
from backend.analysis import factors as factors_mod  # noqa: E402
from backend.analysis import universe as universe_mod  # noqa: E402
from backend.analysis import macro as macro_mod  # noqa: E402
from backend.analysis import whatif as whatif_mod  # noqa: E402
from backend.analysis import glossary as glossary_mod  # noqa: E402
from backend import db as db_mod  # noqa: E402
from backend import edgar as edgar_mod  # noqa: E402
from backend import cik_map as cik_mod  # noqa: E402
from backend import agent_context as actx_mod  # noqa: E402
from backend.analysis import pit_data as pit_mod  # noqa: E402
from backend.analysis import screens as screens_mod  # noqa: E402
from backend import ledger as ledger_mod  # noqa: E402
from backend import model_cards as cards_mod  # noqa: E402
from backend import paper as paper_mod  # noqa: E402
from backend import twins as twins_mod  # noqa: E402
from backend import usage as usage_mod  # noqa: E402
from backend import game as game_mod  # noqa: E402

TICKER = "AAPL"
_FAILURES: list[str] = []
_REAL_DB_PATH = db_mod.DB_PATH


# --- assertion helpers --------------------------------------------------------
def req(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def finite(x, name: str) -> None:
    req(isinstance(x, (int, float)), f"{name} must be numeric, got {type(x).__name__}")
    req(math.isfinite(float(x)), f"{name} must be finite, got {x}")


def in_range(x, lo, hi, name: str) -> None:
    finite(x, name)
    req(lo <= x <= hi, f"{name}={x} out of range [{lo}, {hi}]")


def nonempty_dict(d, name: str) -> None:
    req(isinstance(d, dict) and len(d) > 0, f"{name} must be a non-empty dict")


def has_explanations(payload: dict) -> None:
    if "explanations" in payload:
        nonempty_dict(payload["explanations"], "explanations")


# --- module tests -------------------------------------------------------------
# Each takes the shared context dict and asserts. Raising = fail.
def t_test_isolation(ctx) -> None:
    """Tests must never touch real data: paper/game tests reset their tables."""
    req(not db_mod.IS_PG, "tests must not run against Postgres")
    req(db_mod.DB_PATH != _REAL_DB_PATH, "tests are pointed at the real database")
    req("quantanalyzer-test-" in str(db_mod.DB_PATH), "tests should use a throwaway DB")


def t_data(ctx) -> None:
    td = ctx["td"]
    req(td is not None, "data.load returned None")
    req(not td.history.empty, "history is empty")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        req(col in td.history.columns, f"history missing '{col}' column")
    finite(td.last_price, "last_price")
    req(td.last_price > 0, "last_price must be positive")


def t_indicators(ctx) -> None:
    df = ind_mod.compute_all(ctx["td"].history)
    for col in ("SMA50", "SMA200", "RSI14", "MACD_HIST", "VOL30"):
        req(col in df.columns, f"indicators missing '{col}'")
    rsi = df["RSI14"].dropna()
    req(not rsi.empty, "RSI14 all-NaN")
    in_range(float(rsi.min()), 0, 100, "RSI14.min")
    in_range(float(rsi.max()), 0, 100, "RSI14.max")


def t_signals(ctx) -> None:
    sig = signals_mod.compute(ctx["df_ready"], ctx["bench_df"])
    in_range(sig.composite, -100, 100, "signal.composite")
    in_range(sig.confidence, 0, 100, "signal.confidence")
    req(isinstance(sig.action, str) and sig.action, "signal.action empty")
    req(isinstance(sig.factors, list) and len(sig.factors) >= 1, "signal.factors empty")
    for f in sig.factors:
        in_range(f.score, -1.0, 1.0, f"factor '{f.name}'.score")


def t_regime(ctx) -> None:
    reg = regime_mod.classify(ctx["df_ready"])
    req(isinstance(reg.label, str) and reg.label, "regime.label empty")
    finite(reg.strength, "regime.strength")


def t_risk(ctx) -> None:
    rsk = risk_mod.rate(ctx["close"])
    req(isinstance(rsk.rating, str) and rsk.rating, "risk.rating empty")
    finite(rsk.annualized_vol, "risk.annualized_vol")
    req(rsk.annualized_vol >= 0, "risk.annualized_vol negative")
    in_range(rsk.max_drawdown_1y, -1.0, 0.0, "risk.max_drawdown_1y")


def t_distribution(ctx) -> None:
    d = dist_mod.compute(ctx["close"])
    finite(d.stdev_daily, "dist.stdev_daily")
    req(d.stdev_daily >= 0, "dist.stdev_daily negative")
    for nm in ("mean_daily", "skew", "kurtosis", "var_95", "var_99",
               "sharpe_annual", "last_return_z"):
        finite(getattr(d, nm), f"dist.{nm}")


def t_backtest(ctx) -> None:
    bt = backtest_mod.run(ctx["td"].history, benchmark_df=ctx["bench_df"])
    finite(bt.signal_return, "backtest.signal_return")
    finite(bt.buyhold_return, "backtest.buyhold_return")
    in_range(bt.hit_rate, 0.0, 1.0, "backtest.hit_rate")
    req(isinstance(bt.n_trades, int) and bt.n_trades >= 0, "backtest.n_trades invalid")
    finite(bt.sharpe_signal, "backtest.sharpe_signal")
    # SPY benchmark supplied → alpha must be populated and consistent
    req(bt.spy_return is not None, "backtest.spy_return None despite benchmark")
    req(abs(bt.alpha_vs_spy - (bt.signal_return - bt.spy_return)) < 1e-9,
        "backtest.alpha_vs_spy != signal_return - spy_return")


def t_quant_score(ctx) -> None:
    r = quant_score_mod.compute(TICKER)
    payload = quant_score_mod.to_dict(r)
    req(isinstance(r.verdict, str) and r.verdict, "quant_score.verdict empty")
    in_range(r.directional_score, -100, 100, "quant_score.directional_score")
    in_range(r.percentile_score, 0, 100, "quant_score.percentile_score")
    in_range(r.confidence, 0, 100, "quant_score.confidence")
    nonempty_dict(payload, "quant_score payload")
    has_explanations(payload)


def _compute_todict(mod, *args) -> None:
    """Generic: compute(...) returns non-None, to_dict yields non-empty dict."""
    r = mod.compute(*args)
    req(r is not None, f"{mod.__name__}.compute returned None")
    payload = mod.to_dict(r)
    nonempty_dict(payload, f"{mod.__name__} payload")
    has_explanations(payload)


def t_peers(ctx) -> None:
    _compute_todict(peers_mod, TICKER)


def t_sentiment(ctx) -> None:
    _compute_todict(sentiment_mod, TICKER, ctx["close"])


def t_news_feed(ctx) -> None:
    """Headlines actually arrive. An empty feed once silently blanked the
    Sentiment tab and the news archive for weeks."""
    import time as _time
    raw = sentiment_mod._fetch_raw_news(TICKER)
    req(len(raw) >= 3, f"news feed returned {len(raw)} items for {TICKER}")
    items = [sentiment_mod._normalize(r) for r in raw]
    items = [i for i in items if i]
    req(len(items) >= 3 and all(i["title"] for i in items), "headlines failed to normalize")
    newest = max(i["ts"] for i in items)
    req(_time.time() - newest < 30 * 86400, "newest headline is over 30 days old")


def t_statistics(ctx) -> None:
    _compute_todict(stats_mod, ctx["close"], ctx["bench_close"])


def t_spectral(ctx) -> None:
    _compute_todict(spectral_mod, ctx["close"])


def t_topology(ctx) -> None:
    _compute_todict(topology_mod, ctx["close"])


def t_manifold(ctx) -> None:
    h = ctx["td"].history
    _compute_todict(manifold_mod, h["Close"], h["High"], h["Low"])


def t_regime_hmm(ctx) -> None:
    _compute_todict(regime_hmm_mod, ctx["close"])


def t_valuation(ctx) -> None:
    _compute_todict(valuation_mod, TICKER)


def t_catalyst(ctx) -> None:
    _compute_todict(catalyst_mod, TICKER)


def t_whatif(ctx) -> None:
    r = whatif_mod.compute(TICKER)
    req(r.error is None, f"whatif error: {r.error}")
    req(len(r.horizons) >= 1, "whatif produced no horizons")
    for h in r.horizons:
        finite(h.final_value, f"{h.label}.final_value")
        req(h.final_value > 0, f"{h.label}.final_value must be positive")
        in_range(h.max_drawdown_pct, -100.0, 0.0, f"{h.label}.max_drawdown_pct")
        finite(h.cagr_pct, f"{h.label}.cagr_pct")
    d = r.to_dict()
    req(len(d["series"]["dates"]) == len(d["series"]["ticker_value"]),
        "series dates/values length mismatch")
    if d["series"]["spy_value"]:
        req(len(d["series"]["spy_value"]) == len(d["series"]["dates"]),
            "spy series length mismatch")
    nonempty_dict(d["explanations"], "whatif explanations")


def t_score_backtest(ctx) -> None:  # slow: walk-forward, only with --full
    r = score_bt_mod.compute([TICKER, "MSFT", "GOOGL"], lookback_years=1, fwd_days=21)
    req(r is not None, "score_backtest returned None")


def t_glossary(ctx) -> None:
    d = glossary_mod.get_glossary()
    req(d["term_count"] == len(d["terms"]) >= 25, "glossary too small")
    req(set(t["category"] for t in d["terms"]) == set(d["categories"]),
        "category mismatch between terms and CATEGORIES")
    ids = [t["id"] for t in d["terms"]]
    req(len(ids) == len(set(ids)), "duplicate glossary ids")
    for term in d["terms"]:
        for k in ("id", "term", "category", "appears_in",
                  "definition", "intuition", "limits"):
            req(bool(term.get(k)), f"glossary entry {term.get('id')} missing {k}")


def t_news_archive(ctx) -> None:
    """Headline archive: stores, de-duplicates, and reports coverage."""
    db_mod.init()
    before = db_mod.news_archive_stats()["headlines"]
    rows = [{"ticker": "TEST", "published_ts": 1700000000, "headline": "Unit test headline",
             "publisher": "pytest", "url": "", "fingerprint": "unit-test-fp-1",
             "sentiment": 0.5}]
    added = db_mod.news_archive_add(rows)
    req(added == 1, f"expected 1 insert, got {added}")
    again = db_mod.news_archive_add(rows)
    req(again == 0, f"duplicate should not be stored, got {again}")
    stats = db_mod.news_archive_stats()
    req(stats["headlines"] == before + 1, "archive count wrong")
    got = db_mod.news_archive_for("TEST")
    req(got and got[0]["headline"] == "Unit test headline", "archive read-back failed")
    db_mod.execute("DELETE FROM news_archive WHERE ticker = ?", ("TEST",))


def t_factors(ctx) -> None:
    """Fama-French adjustment, checked against cases with known answers."""
    cov = factors_mod.coverage()
    req(cov["rows"] > 10000, "factor history looks too short")
    req(len(cov["factors"]) == 6, "expected 5 FF factors plus momentum")

    f = factors_mod.load_factors()
    # returns are decimals, not percent: daily moves should be small
    req(float(f["Mkt-RF"].abs().max()) < 0.5, "factor values look like percent, not decimals")
    req(float(f["Mkt-RF"].std()) < 0.05, "daily market factor dispersion implausible")

    dates = [d.strftime("%Y-%m-%d") for d in f.index[-700::21]]
    w = factors_mod.window_returns(dates, 21)
    req(len(w) >= 20, "window_returns produced too few rows")

    # 1) A strategy that IS the momentum factor must show beta 1 and no alpha.
    pure = {d: float(w.loc[d, "Mom"]) for d in w.index}
    fit1 = factors_mod.fit(pure, 21)
    req(fit1 is not None, "fit returned nothing for the momentum replica")
    req(abs(fit1.betas["Mom"] - 1.0) < 0.01, f"momentum beta should be 1, got {fit1.betas['Mom']}")
    req(abs(fit1.alpha_annualized) < 0.01, f"momentum replica should have ~0 alpha, got {fit1.alpha_annualized}")
    req(fit1.r_squared > 0.99, "momentum replica should be fully explained")

    # 2) A constant edge uncorrelated with the factors must show real alpha.
    fake = {d: 0.01 for d in w.index}
    fit2 = factors_mod.fit(fake, 21)
    req(fit2 is not None and fit2.alpha_t > 2.0,
        f"a genuine edge should be significant, t={fit2.alpha_t if fit2 else None}")
    req(fit2.alpha_annualized > 0.05, "a 1%/period edge should annualize above 5%")

    # 3) Too few periods must return None rather than a fragile fit.
    req(factors_mod.fit({d: 0.01 for d in list(w.index)[:5]}, 21) is None,
        "fit should refuse a tiny sample")


def t_macro(ctx) -> None:
    """Live macro inputs, with an honest fallback when FRED is unreachable."""
    rf = macro_mod.risk_free_rate()
    in_range(rf.value, 0.0, 0.25, "risk_free_rate")
    req(rf.source in ("FRED", "fallback"), "unknown macro source")
    if rf.is_live:
        req(rf.as_of is not None, "a live value must carry its observation date")
        req(rf.source == "FRED", "live values come from FRED")
    else:
        req(abs(rf.value - macro_mod.FALLBACK_RISK_FREE) < 1e-9,
            "a non-live value must be the documented fallback")
    snap = macro_mod.snapshot()
    req("risk_free_rate" in snap and "vix" in snap, "snapshot payload incomplete")


def t_universe(ctx) -> None:
    """Point-in-time S&P 500 membership — the survivorship-bias fix."""
    info = universe_mod.stats()
    req(info["tickers_ever"] > 1000, "membership history looks too small")
    req(400 < info["current_members"] < 600, "current member count implausible")

    members = universe_mod.members_on("2023-08-31")
    req(450 < len(members) < 550, f"expected ~503 members, got {len(members)}")
    req("AAPL" in members, "AAPL should be an index member in 2023")

    # names that left the index must still appear in the historical pool
    gone = universe_mod.leavers_between("2023-08-31", "2026-08-31")
    req(len(gone) > 20, f"expected dozens of leavers, got {len(gone)}")
    pool = universe_mod.members_between("2023-08-31", "2026-08-31")
    req(len(pool) > len(universe_mod.members_on("2026-08-31")),
        "the historical pool must be larger than today's membership")
    req(gone <= pool, "leavers must be inside the historical pool")

    # a company that left is a member BEFORE its removal and not after
    sample_gone = sorted(gone)[0]
    req(sample_gone in universe_mod.members_on("2023-08-31"),
        f"{sample_gone} should be a member at the window start")
    req(sample_gone not in universe_mod.members_on("2026-08-31"),
        f"{sample_gone} should not be a member at the window end")

    req(universe_mod.to_yahoo("BRK.B") == "BRK-B", "share-class symbols must map to Yahoo style")

    fn = universe_mod.membership_filter(["AAPL", "MSFT"])
    req(fn("2023-08-31") == {"AAPL", "MSFT"}, "membership filter should intersect the sample")

    picks = universe_mod.sample_members(10, as_of="2023-08-31", seed=1)
    req(len(picks) == 10 and len(set(picks)) == 10, "sample should return 10 distinct tickers")
    req(picks == universe_mod.sample_members(10, as_of="2023-08-31", seed=1),
        "sampling must be reproducible for a given seed")


def t_crisis(ctx) -> None:
    """Crisis event studies: point-in-time VaR breaches and regime timing."""
    windows = crisis_mod.list_windows()
    req(len(windows) >= 4, "expected at least four crisis windows")
    s = crisis_mod.compute("SPY", windows[0]["id"])
    req(s.error is None, f"crisis study failed: {s.error}")
    req(s.n_days > 5, "window should contain trading days")
    req(len(s.series) >= s.n_days, "series should cover the window plus context")
    in_range(s.max_drawdown_pct, -100.0, 0.0, "max_drawdown_pct")
    req(s.var_breaches >= 0 and s.var_breaches_expected > 0, "VaR accounting wrong")
    req(s.var_breaches <= s.n_days, "more breaches than days")
    # every breach must be a day whose return is below its own prior-year VaR
    for d in s.series:
        if d.breach:
            req(d.var_pct is not None and d.ret_pct < d.var_pct,
                f"{d.date} flagged a breach but {d.ret_pct} >= {d.var_pct}")
    nonempty_dict(s.explanations, "crisis explanations")
    bad = crisis_mod.compute("SPY", "not_a_window")
    req(bad.error is not None, "unknown window should error")


def t_crisis_rounds(ctx) -> None:
    """Game rounds restricted to crisis windows."""
    db_mod.init()
    game_mod.reset()
    r = game_mod.new_round(seed=1000, mode="crisis")
    g = game_mod.submit_guess(r["round_id"], "long", 60)
    req(g["reveal"]["crisis"], "a crisis round must name its window")
    names = {w["name"] for w in crisis_mod.list_windows()}
    req(g["reveal"]["crisis"] in names, "unknown crisis label on the round")
    try:
        game_mod.new_round(mode="nonsense")
        req(False, "bad mode accepted")
    except game_mod.GameError:
        pass
    game_mod.reset()


def t_backtest_rigor(ctx) -> None:
    """Multiple-testing correction, the trials ledger, and cost accounting."""
    # Benjamini-Hochberg against a hand-computable case
    q = score_bt_mod._benjamini_hochberg([0.01, 0.02, 0.03, 0.50, 0.90])
    expected = [0.05, 0.05, 0.05, 0.625, 0.9]
    for got, want in zip(q, expected):
        req(abs(got - want) < 1e-6, f"BH q-value {got} != {want}")
    req(score_bt_mod._benjamini_hochberg([]) == [], "BH should handle an empty list")
    # monotone: sorted inputs give non-decreasing q-values
    qs = score_bt_mod._benjamini_hochberg([0.001, 0.2, 0.4, 0.8])
    req(all(a <= b + 1e-9 for a, b in zip(qs, qs[1:])), "BH q-values must not decrease")

    # trials ledger round-trip
    db_mod.init()
    before = len(db_mod.backtest_trials(500))
    tid = db_mod.record_backtest_trial({
        "label": "unit-test", "universe": "AAA,BBB", "n_tickers": 2,
        "lookback_years": 1, "fwd_days": 21, "cost_bps": 10.0,
        "n_observations": 10, "n_months": 5, "date_start": "2024-01-01",
        "date_end": "2024-06-01", "ic_mean": 0.01, "ic_t_stat": 0.5,
        "ir_annualized": 0.1, "pooled_ic": 0.02, "ls_mean_net": -0.001})
    rows = db_mod.backtest_trials(500)
    req(len(rows) == before + 1, "trial was not recorded")
    req(rows[0]["id"] == tid and rows[0]["label"] == "unit-test", "ledger row wrong")
    req(score_bt_mod.DEFAULT_COST_BPS > 0, "a default trading cost should be set")


def t_ledger(ctx) -> None:
    """Prediction ledger: sealing, validation, and grading against a synthetic
    calendar with known answers (no network)."""
    from datetime import date as _date

    db_mod.init()
    days = pd.bdate_range("2026-01-02", periods=60).strftime("%Y-%m-%d").tolist()
    closes = {
        "SPY": pd.Series([100 * 1.001 ** i for i in range(60)], index=days),
        "WIN": pd.Series([50 * 1.003 ** i for i in range(60)], index=days),
        "LOSE": pd.Series([80 * 0.999 ** i for i in range(60)], index=days),
        "GONE": pd.Series([20.0] * 10, index=days[:10]),   # stops trading on day 10
        "HALT": pd.Series([30 * 1.002 ** i for i in range(60) if i != 1],
                          index=[d for i, d in enumerate(days) if i != 1]),   # halted on entry day
    }

    def fetch(tickers, start, end):
        return {t: closes[t][(closes[t].index >= start) & (closes[t].index < end)]
                for t in tickers if t in closes}

    real_today = ledger_mod._today
    try:
        ledger_mod._today = lambda: _date(2026, 1, 2)
        pool = ledger_mod.record_pool("test pool", "2026-01-02", ["WIN", "LOSE", "GONE", "SNAP"])
        req(ledger_mod.record_pool("test pool", "2026-01-02", ["SNAP", "GONE", "LOSE", "WIN"]) == pool,
            "the same pool must get the same id")

        def call(subject, stance, p, **kw):
            return ledger_mod.record_call(
                agent_id="test-agent", charter_version="v1", model_id="rules",
                subject=subject, as_of="2026-01-02", horizon_days=20,
                output={"stance": stance, "p_beat_market": p},
                packet={"subject": subject, "rsi": float("nan"), "n": pd.Series([1]).iloc[0]},
                source_tag="unit-test", pool_id=pool, **kw)

        c_win = call("WIN", "positive", 0.7)
        c_lose = call("LOSE", "negative", 0.3)
        c_gone = call("GONE", "positive", 0.6)
        c_snap = call("SNAP", "positive", None)
        c_trap = call("WIN", "positive", 0.9, is_trap=True)
        c_halt = ledger_mod.record_call(agent_id="halt-agent", charter_version="v1", model_id="rules",
                                        subject="HALT", as_of="2026-01-02", horizon_days=20,
                                        output={}, packet={"subject": "HALT"})

        # every invalid call is rejected
        for kw in ({"as_of": "2026-01-05"},                       # after the recording date
                   {"horizon_days": 0},
                   {"output": {"stance": "bullish"}},
                   {"output": {"p_beat_market": 70}},             # percent, not probability
                   {"agent_id": ""},
                   {"pool_id": "no-such-pool"}):
            args = dict(agent_id="test-agent", charter_version="v1", model_id="rules",
                        subject="WIN", as_of="2026-01-02", horizon_days=20,
                        output={}, packet={})
            args.update(kw)
            try:
                ledger_mod.record_call(**args)
                req(False, f"invalid call accepted: {kw}")
            except ledger_mod.LedgerError:
                pass

        # packets are cleaned, stored once, and read back exactly
        got = ledger_mod.get_call(c_win)
        req(got["packet"] == {"subject": "WIN", "rsi": None, "n": 1}, "packet not cleaned/stored")
        req(db_mod.query("SELECT COUNT(*) FROM ledger_packets WHERE packet_hash = ?",
                         (got["packet_hash"],))[0][0] == 1, "packet stored twice")
        req(got["recorded_on"] == "2026-01-02" and got["grade"] is None, "call fields wrong")
        req("SPY" in ledger_mod.watched_tickers() and "SNAP" in ledger_mod.watched_tickers(),
            "watched tickers must include the benchmark and the pool")

        # nothing is due before the horizon has passed
        ledger_mod._today = lambda: _date(2026, 1, 20)
        s = ledger_mod.grade_due(fetch)
        req(s["open"] == 5 and s["not_due"] == 5 and s["graded"] == 0, f"early grading: {s}")

        # snapshots: SNAP has no live prices but did a 2-for-1 split and paid a dividend
        snap_rows = {d: (100.0, 0.0, 0.0) for d in days[:5]}
        snap_rows.update({d: (50.0, 0.0, 0.0) for d in days[5:21]})
        snap_rows[days[5]] = (50.0, 0.0, 2.0)       # split on day 6
        snap_rows[days[10]] = (50.0, 1.0, 0.0)      # $1/share dividend on day 11
        snap_rows.update({d: (60.0, 0.0, 0.0) for d in days[21:30]})
        bars = pd.DataFrame({"close": [v[0] for v in snap_rows.values()],
                             "adj_close": [v[0] for v in snap_rows.values()],
                             "dividend": [v[1] for v in snap_rows.values()],
                             "split": [v[2] for v in snap_rows.values()]},
                            index=list(snap_rows.keys()))
        ledger_mod._today = lambda: _date(2026, 3, 27)
        r = ledger_mod.snapshot_prices(["SNAP"], lookback_days=120,
                                       fetcher=lambda t, a, b: {"SNAP": bars})
        req(r["rows_added"] == 30, f"expected 30 snapshot rows, got {r}")
        req(ledger_mod.snapshot_prices(["SNAP"], lookback_days=120,
                                       fetcher=lambda t, a, b: {"SNAP": bars})["rows_added"] == 0,
            "snapshots must not be stored twice")

        s = ledger_mod.grade_due(fetch)
        req(s["graded"] == 3 and s["graded_snapshot"] == 1 and s["needs_review"] == 1, f"{s}")
        h = ledger_mod.get_call(c_halt, with_packet=False)["grade"]
        req(h["entry_date"] == days[2] and abs(h["bench_return"] - (1.001 ** 19 - 1)) < 1e-9,
            "a stock halted on entry day must be compared with the market over the same days")
        w = ledger_mod.get_call(c_win, with_packet=False)["grade"]
        req(w["entry_date"] == days[1] and w["exit_date"] == days[21],
            "entry must be the first trading day after the call; exit 20 days later")
        req(abs(w["total_return"] - (1.003 ** 20 - 1)) < 1e-9, "total return wrong")
        req(abs(w["bench_return"] - (1.001 ** 20 - 1)) < 1e-9, "benchmark return wrong")
        req(w["beat_market"] == 1 and abs(w["brier"] - 0.09) < 1e-9, "beat/brier wrong")
        lo = ledger_mod.get_call(c_lose, with_packet=False)["grade"]
        req(lo["beat_market"] == 0 and abs(lo["brier"] - 0.09) < 1e-9, "losing call graded wrong")
        sn = ledger_mod.get_call(c_snap, with_packet=False)["grade"]
        req(sn["status"] == "graded_snapshot" and abs(sn["total_return"] - 0.22) < 1e-9,
            f"split/dividend walk wrong: {sn['total_return']}")   # (2*60 + 2*1)/100 - 1
        req(sn["brier"] is None, "no probability, no Brier score")
        gn = ledger_mod.get_call(c_gone, with_packet=False)["grade"]
        req(gn["status"] == "needs_review", "a stock that stopped trading must be flagged")
        req(ledger_mod.get_call(c_trap, with_packet=False)["grade"] is None,
            "trap calls are never graded")

        # final grades are immutable; a delisted stock gets a manual final return
        ledger_mod._write_grade(c_win, "needs_review", None, None, None, None, None, None)
        req(ledger_mod.get_call(c_win, with_packet=False)["grade"]["status"] == "graded",
            "a final grade was overwritten")
        try:
            ledger_mod.grade_manually(c_gone, -1.0, "short", fetcher=fetch)
            req(False, "a manual grade needs a real explanation")
        except ledger_mod.LedgerError:
            pass
        ledger_mod.grade_manually(c_gone, -1.0, "bankrupt; shares cancelled (test)", fetcher=fetch)
        gn = ledger_mod.get_call(c_gone, with_packet=False)["grade"]
        req(gn["status"] == "graded_manual" and gn["total_return"] == -1.0, "manual grade wrong")
        try:
            ledger_mod.grade_manually(c_gone, 0.0, "second attempt (test)", fetcher=fetch)
            req(False, "a final grade was replaced by a manual one")
        except ledger_mod.LedgerError:
            pass

        # failed audits stay in the record, flagged; traps never count
        ledger_mod.set_audit_status(c_lose, "failed", "cited a number not in its packet")
        tr = ledger_mod.track_record("test-agent")
        req(tr["calls"] == 4 and tr["graded"] == 4 and tr["failed_audit"] == 1, f"{tr}")
        req(abs(tr["hit_rate"] - 0.5) < 1e-9, f"hit rate wrong: {tr['hit_rate']}")
        req(ledger_mod.grade_due(fetch)["open"] == 0, "everything should be closed")
    finally:
        ledger_mod._today = real_today


def t_trend_twin(ctx) -> None:
    """The Trend twin seals one call per stock per week, with its full evidence."""
    import tempfile
    from datetime import timedelta as _td

    db_mod.init()
    td, bench = ctx["td"], data_mod.TickerData("SPY", ctx["bench_df"], {})
    last = td.history.index[-1].date()
    stale = data_mod.TickerData("OLD", td.history.set_axis(td.history.index - pd.Timedelta(days=30)), {})
    short = data_mod.TickerData("SHORT", td.history.tail(230), {})   # a recent listing, like Q
    loader = {"SPY": bench, "AAA": td, "BBB": td, "OLD": stale, "SHORT": short}.get

    real_today = ledger_mod._today
    try:
        ledger_mod._today = lambda: last + _td(days=1)
        s = twins_mod.record_trend_twin(["AAA", "BBB", "OLD", "NONE", "SHORT"], loader=loader)
        req(s["recorded"] == 2, f"expected 2 calls, got {s}")
        reasons = {k["ticker"]: k["reason"] for k in s["skipped"]}
        req("stale" in reasons.get("OLD", "") and "no price" in reasons.get("NONE", ""),
            f"stale and missing data must be skipped, got {reasons}")
        req("incomplete" in reasons.get("SHORT", ""),
            f"a signal with an uncomputable factor must not be sealed (Q, 2026-10-05): {reasons}")
        again = twins_mod.record_trend_twin(["AAA", "BBB"], loader=loader)
        req(again["recorded"] == 0 and again["already_done"] == 2, "twin called twice in a week")

        calls = ledger_mod.list_calls("trend_twin")
        req(len(calls) == 2, "twin calls not in the ledger")
        c = ledger_mod.get_call(calls[0]["call_id"])
        req(c["output"]["stance"] in ledger_mod.STANCES, "twin stance invalid")
        req(c["output"]["action"] in ("BUY", "HOLD", "SELL"), "twin action missing")
        req(c["as_of"] == last.isoformat() and c["horizon_days"] == 20, "twin call fields wrong")
        req(len(c["packet"]["closes"]) == len(td.history), "packet must hold the full price history")
        bench_packet = ledger_mod.get_packet(c["packet"]["benchmark_packet"])
        req(bench_packet and bench_packet["ticker"] == "SPY", "benchmark evidence not stored")
        pool = ledger_mod.get_pool(c["pool_id"])
        req(pool and set(pool["tickers"]) == {"AAA", "BBB", "NONE", "OLD", "SHORT"}, "pool not recorded")
        again_from_evidence = twins_mod.reproduce_trend_twin(c["packet"])
        req(again_from_evidence["action"] == c["output"]["action"],
            "the sealed twin call can't be reproduced from its stored evidence")
        req(abs(again_from_evidence["composite"] - c["output"]["composite"]) <= 0.5,
            "re-computed composite drifted from the sealed one")
    finally:
        ledger_mod._today = real_today

    # the tracking list is created once, then never changes
    with tempfile.TemporaryDirectory(prefix="quantanalyzer-test-") as tmp:
        path = Path(tmp) / "tracking.json"
        first = twins_mod.tracking_list(path)
        req(len(first["tickers"]) == twins_mod.TRACKING_SIZE, "tracking list size wrong")
        req(twins_mod.tracking_list(path) == first, "tracking list must stay fixed")


def t_model_card_rules(ctx) -> None:
    """Every card's outlook rule, checked against hand-computed answers."""
    bo = cards_mod.business_outlook   # (dcf_upside, reliable, applicable, peer_label, growth, margin)
    req(bo(0.30, True, True, "cheap / attractive", 0.10, 0.20)[:2] == ("up", "medium"), "cheap+cheap+healthy")
    req(bo(-0.30, True, True, "expensive / weak", 0.10, 0.20)[:2] == ("down", "medium"), "expensive+expensive")
    req(bo(0.30, True, True, "expensive / weak", 0.10, 0.20)[:2] == ("flat", "low"), "lenses cancel out")
    req(bo(0.30, False, True, "fair", 0.10, 0.20)[:2] == ("flat", "low"), "an unreliable DCF must not vote")
    req(bo(-0.66, True, True, "fair", 0.10, 0.20)[:2] == ("flat", "low"),
        "a DCF more than 50% from the price must not vote (it called 9 of 10 large caps overvalued)")
    req(bo(-0.66, True, True, None, 0.10, 0.20)[:2] == (None, None), "if nothing can vote, no outlook")
    req(bo(0.30, True, False, None, 0.10, 0.20)[:2] == (None, None), "a DCF that doesn't fit (banks) must not vote")
    req(bo(0.30, True, True, "cheap / attractive", -0.05, -0.10)[0] == "flat", "an unhealthy business can't be 'up'")
    req(bo(None, False, False, None, None, None)[:2] == (None, None), "no data, no outlook")

    # headlines must name the company: Yahoo's feed mixes in other companies' stories
    H = lambda title: type("H", (), {"title": title})()
    heads = [H("Apple's App Store growth rebounds"), H("Marvell stock surges after outlook"),
             H("Pineapple prices jump"), H("Why AAPL slipped today"), H("Nvidia, Apple and Microsoft rally"),
             H("aapl lowercase is not a ticker")]
    kept = [h.title for h in cards_mod.relevant_headlines(heads, "AAPL", "Apple Inc.")]
    req(kept == ["Apple's App Store growth rebounds", "Why AAPL slipped today",
                 "Nvidia, Apple and Microsoft rally"], f"headline filter wrong: {kept}")
    req(cards_mod.company_keywords("GE", "General Electric Company") == ["General Electric"],
        "a generic first word ('General') must not count on its own")
    req(cards_mod.company_keywords("KO", "The Coca-Cola Company") == ["Coca-Cola"], "suffix stripping wrong")

    # every outlook can be recomputed from the evidence packet alone
    ofp = cards_mod.outlook_from_packet
    req(ofp({"model_id": "trend", "fields": {"trend_score": 30.0}})[:2] == ("up", "low"), "trend from packet")
    req(ofp({"model_id": "trend", "fields": {"trend_score": -80.0}})[:2] == ("down", "medium"), "trend cap")
    req(ofp({"model_id": "news", "fields": {"mood_score": 40.0, "headlines_relevant": 6}})[:2] == ("up", "low"),
        "news from packet")
    req(ofp({"model_id": "business", "fields": {"dcf_upside": 0.3, "revenue_growth": 0.1,
                                                "operating_margin": 0.2},
             "inputs": {"dcf_reliable": True, "dcf_applicable": True,
                        "peer_label": "cheap / attractive"}})[:2] == ("up", "medium"), "business from packet")
    req(ofp({"model_id": "resilience", "fields": {}})[:2] == (None, None), "resilience never forecasts")

    no = cards_mod.news_outlook
    req(no(40, 10) == ("up", "low") and no(-30, 10) == ("down", "low") and no(10, 10) == ("flat", "low"),
        "news thresholds wrong")
    req(no(40, 3) == (None, None), "too few headlines must give no outlook")

    ts = cards_mod.trend_strength
    req(ts(30) == "low" and ts(-60) == "medium" and ts(95) == "medium",
        "strength must be capped below 'high' for unproven models")

    # resilience: market -50% peak to trough; stock -30%, back to its start 10 days after the trough
    days = pd.bdate_range("2007-10-09", "2009-06-30")
    trough_i = days.get_indexer([pd.Timestamp("2009-03-09")])[0]
    mkt = pd.Series([100 - 50 * min(i, trough_i) / trough_i for i in range(len(days))], index=days)
    stk = pd.Series([100 - 30 * i / trough_i if i <= trough_i else
                     min(100.0, 70 + 3 * (i - trough_i)) for i in range(len(days))], index=days)
    r = cards_mod.decline_stats(stk, mkt, {"id": "gfc", "name": "GFC",
                                           "peak": "2007-10-09", "trough": "2009-03-09"})
    req(abs(r["stock_return"] + 0.30) < 1e-9 and abs(r["market_return"] + 0.50) < 1e-9,
        f"decline returns wrong: {r}")
    req(abs(r["max_drawdown"] + 0.30) < 1e-9 and r["recovery_days"] == 10, f"drawdown/recovery wrong: {r}")
    late = stk[stk.index > pd.Timestamp("2008-06-01")]
    req(cards_mod.decline_stats(late, mkt, {"id": "x", "name": "x", "peak": "2007-10-09",
                                            "trough": "2009-03-09"}) is None,
        "a stock listed after the peak has no history for that decline")
    tz_stk = stk.copy()
    tz_stk.index = tz_stk.index.tz_localize("America/New_York")
    req(cards_mod._naive(tz_stk).index[-1] == stk.index[-1], "timezone stripping shifted the dates")

    rets = pd.Series([0.01 * (((i * 7919) % 13) - 6) / 6 for i in range(600)])  # -1%..+1% daily
    market = (1 + rets).cumprod()
    double = (1 + 2 * rets).cumprod()
    req(abs(cards_mod.beta(double, market) - 2.0) < 1e-6, "a stock moving 2x the market has beta 2")
    mi = pd.date_range("2018-01-31", periods=96, freq="ME")
    m_rets = pd.Series([0.03 * (((i * 7) % 11) - 5) / 5 for i in range(96)], index=mi)
    req(abs(cards_mod.monthly_beta((1 + 2 * m_rets).cumprod(), (1 + m_rets).cumprod()) - 2.0) < 1e-6,
        "monthly beta of a 2x stock must be 2")
    s1 = cards_mod.board_summary([cards_mod.ModelCard("x", "X", "", "", "flat", None, ""),
                                  cards_mod.ModelCard("y", "Y", "", "", None, None, "")])["text"]
    req(s1.startswith("Only 1 model"), f"singular summary wrong: {s1}")

    card = lambda o: cards_mod.ModelCard("x", "X", "", "", o, None, "")
    req("All 2" in cards_mod.board_summary([card("up"), card("up"), card(None)])["text"], "agreement text")
    s = cards_mod.board_summary([card("up"), card("down"), card("flat")])
    req(s["counts"] == {"up": 1, "flat": 1, "down": 1} and s["with_outlook"] == 3, "summary counts wrong")
    saved = cards_mod.BUILDERS["news"]
    try:
        cards_mod.BUILDERS["news"] = lambda t: 1 / 0
        bad = cards_mod.safe_card("news", "AAPL")
        req(bad.error and bad.outlook is None, "a failing model must become an 'unavailable' card")
    finally:
        cards_mod.BUILDERS["news"] = saved


def t_model_calls_ledger(ctx) -> None:
    """Rule models seal weekly calls with their packets; no outlook, no call."""
    from datetime import date as _date

    db_mod.init()

    def fake(ticker):
        if ticker == "NOVIEW":
            return cards_mod.ModelCard("news", "News", "", "", None, None, "Too few headlines",
                                       subject=ticker, model_version="news-v1", as_of="2026-01-02")
        card = cards_mod.ModelCard("news", "News", "", "", None, None, "", subject=ticker,
                                   model_version="news-v1", as_of="2026-01-02",
                                   evidence=[cards_mod.Evidence("Headline mood", "+40", "", "mood_score", 40.0),
                                             cards_mod.Evidence("Headlines", "6", "", "headlines_relevant", 6)])
        return cards_mod._finish(card)

    real_today = ledger_mod._today
    try:
        ledger_mod._today = lambda: _date(2026, 1, 2)
        s = cards_mod.record_model_calls("news", ["AAA", "NOVIEW"], build=fake)
        req(s["recorded"] == 1 and len(s["skipped"]) == 1, f"model calls wrong: {s}")
        again = cards_mod.record_model_calls("news", ["AAA", "NOVIEW"], build=fake)
        req(again["recorded"] == 0 and again["already_done"] == 1, "a model was called twice in a week")
        c = ledger_mod.list_calls("news_model")[0]
        full = ledger_mod.get_call(c["call_id"])
        req(full["output"]["stance"] == "positive" and full["horizon_days"] == 20, "model call fields wrong")
        req(full["charter_version"] == "news-v1", "the model version must be sealed with the call")
        recomputed = cards_mod.outlook_from_packet(full["packet"])[:2]
        req(recomputed == (full["output"]["outlook"], full["output"]["strength"]),
            "a sealed call must be re-checkable from its packet")
    finally:
        ledger_mod._today = real_today


def t_model_cards_live(ctx) -> None:
    """All four cards build for a real stock, with honest labels and real lessons."""
    glossary_ids = {t["id"] for t in glossary_mod.get_glossary()["terms"]}
    html = (Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
    for model_id in cards_mod.BUILDERS:
        c = cards_mod.safe_card(model_id, TICKER)
        req(c.error is None, f"{model_id} card failed: {c.error}")
        req(c.outlook in (*cards_mod.OUTLOOKS, None), f"{model_id} outlook invalid")
        req(c.strength != "high", f"{model_id} claims high strength without a proven record")
        req(c.track_record and c.track_record.status in ("tested", "untested", "not_a_forecast"),
            f"{model_id} has no track record label")
        req(c.evidence and c.headline and c.caveats, f"{model_id} card is incomplete")
        req(set(c.lessons) <= glossary_ids and c.lessons, f"{model_id} links to a missing lesson")
        req(f'data-tab="{c.deep_dive}"' in html, f"{model_id} deep-dive tab doesn't exist")
        p = c.packet()
        req(p["subject"] == TICKER and p["model_version"] and p["as_of"], f"{model_id} packet header incomplete")
        req(p["fields"] and all(isinstance(k, str) and k for k in p["fields"]), f"{model_id} has no named fields")
        req(cards_mod.outlook_from_packet(p)[:2] == (c.outlook, c.strength),
            f"{model_id}: the outlook can't be reproduced from its own packet")
    res = cards_mod.safe_card("resilience", TICKER)
    req(len([e for e in res.evidence if "vs market" in e.value]) >= 4,
        "AAPL lived through at least four of the five declines")
    biz = {e.label: e.value for e in cards_mod.safe_card("business", TICKER).evidence}
    req(biz["Revenue growth"] != "n/a" and biz["Operating margin"] != "n/a",
        "the Business card lost its growth/margin data (it once read only n/a)")


def t_edgar_parsing(ctx) -> None:
    """SEC facts: first-filed values only, year-long periods only, renamed concepts
    merged by earliest filing, different measures kept apart, and no future data."""
    import os as _os

    U = lambda rows: {"units": {"USD": rows}}
    facts = {"facts": {"us-gaap": {
        "Revenues": U([
            {"start": "2017-10-01", "end": "2018-09-29", "val": 100, "form": "10-K", "filed": "2018-11-05"},
            {"start": "2018-07-01", "end": "2018-09-29", "val": 30, "form": "10-K", "filed": "2018-11-05"}]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": U([
            {"start": "2017-10-01", "end": "2018-09-29", "val": 101, "form": "10-K", "filed": "2019-10-31"},
            {"start": "2018-09-30", "end": "2019-09-28", "val": 110, "form": "10-K", "filed": "2019-10-31"},
            {"start": "2018-09-30", "end": "2019-09-28", "val": 111, "form": "10-K", "filed": "2020-10-30"},
            {"start": "2018-09-30", "end": "2019-09-28", "val": 999, "form": "10-Q", "filed": "2019-08-01"}]),
        "StockholdersEquity": U([{"end": "2019-09-28", "val": 50, "form": "10-K", "filed": "2019-10-31"}]),
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": U([
            {"end": "2019-09-28", "val": 55, "form": "10-K", "filed": "2019-10-30"},
            {"end": "2020-09-26", "val": 60, "form": "10-K", "filed": "2020-10-30"}]),
    }}}
    rev = edgar_mod.annual_values(facts, "revenue")
    req([(r["end"], r["value"]) for r in rev] == [("2018-09-29", 100.0), ("2019-09-28", 110.0)],
        f"revenue must be first-filed, year-long, from annual reports: {rev}")
    req(rev[0]["filed"] == "2018-11-05" and rev[0]["concept"] == "Revenues",
        "a renamed concept must not move a number's first-public date later")
    req([r["end"] for r in edgar_mod.annual_values(facts, "revenue", as_of="2019-01-01")] == ["2018-09-29"],
        "as_of must hide numbers filed later")
    req(edgar_mod.annual_values(facts, "revenue", as_of="2018-11-01") == [],
        "nothing is known before the first filing")
    eq = edgar_mod.annual_values(facts, "equity")
    req([(r["end"], r["value"]) for r in eq] == [("2019-09-28", 50.0), ("2020-09-26", 60.0)],
        f"different measures: use the fallback only where the main concept is missing: {eq}")

    saved = _os.environ.get("SEC_USER_AGENT")
    try:
        _os.environ["SEC_USER_AGENT"] = "no email here"
        try:
            edgar_mod.user_agent()
            req(False, "a User-Agent without a contact email must be refused")
        except edgar_mod.EdgarError:
            pass
    finally:
        if saved is None:
            _os.environ.pop("SEC_USER_AGENT", None)
        else:
            _os.environ["SEC_USER_AGENT"] = saved


def t_edgar_live(ctx) -> None:
    """Apple's real SEC filings (cached for a week under data/edgar/)."""
    s = edgar_mod.statements("AAPL", metrics=["revenue", "net_income", "equity"])
    rev = {r["end"]: r for r in s["revenue"]}
    req(len(rev) >= 15, f"expected 15+ years of Apple revenue, got {len(rev)}")
    req(rev["2024-09-28"]["value"] == 391_035_000_000 and rev["2024-09-28"]["filed"] == "2024-11-01",
        "Apple FY2024 revenue must match its 10-K filed 2024-11-01")
    req(all(r["filed"] > r["end"] for r in s["revenue"]), "a number can't be filed before its period ends")
    known = edgar_mod.annual_values(edgar_mod.company_facts("AAPL"), "revenue", as_of="2024-10-15")
    req(known[-1]["end"] == "2023-09-30", "on 2024-10-15 the FY2024 report wasn't public yet")
    try:
        edgar_mod.cik_for("ZZZZQQ")
        req(False, "an unknown ticker must raise")
    except edgar_mod.EdgarError:
        pass


def t_cik_map_rules(ctx) -> None:
    """The company-identity checker: distinctive names, names in use at the time,
    and a text-search hit can't win against real evidence (no network)."""
    ns = cik_mod.name_similarity
    req(ns("Alexion Pharmaceuticals", "Ra Pharmaceuticals, Inc.") == 0.0,
        "sharing a generic word ('Pharmaceuticals') is not a name match")
    req(ns("Allergan", "Allergan plc") == 1.0 and ns("Dow Chemical Company", "DOW CHEMICAL CO /DE/") == 1.0,
        "suffixes and state markers must not block a match")
    jci = {"name": "Johnson Controls International plc", "formerNames": [
        {"name": "TYCO INTERNATIONAL LTD", "from": "2010-03-08", "to": "2014-11-14"},
        {"name": "ADT LIMITED", "from": "1995-02-15", "to": "1997-07-08"}]}
    during = cik_mod.names_during(jci, "2012-10-02", "2016-05-02")
    req("ADT LIMITED" not in during and "TYCO INTERNATIONAL LTD" in during,
        f"only names in use during the membership count: {during}")

    req(ns("Casey's", "CASEYS GENERAL STORES INC") == 1.0 and ns("U.S. Bancorp", "US BANCORP") == 1.0
        and ns("ExxonMobil", "EXXON MOBIL CORP") == 1.0 and ns("VF Corporation", "V F CORP") == 1.0
        and ns("CR Bard", "BARD C R INC /NJ/") == 1.0, "apostrophes, dots, spaced initials, run-together names")

    C = cik_mod.Candidate
    former, current = cik_mod.Row("XYZ", "2012-01-01", "2018-01-01"), cik_mod.Row("XYZ", "2012-01-01", None)

    def cand(cik, sources, cov, name, names=None):
        return C(cik, set(sources), sec_name=f"Co{cik}", coverage=cov, name_match=name,
                 first_10k="2012-03-01", last_10k="2017-03-01", window_names=names or [f"Co{cik}"])

    d = cik_mod.decide(former, [cand(1, {"sec_search_name", "sec_search_ticker"}, 1.0, 1.0)])
    req(d["status"] == "verified" and d["cik"] == "1", f"two sources + name + filings = verified: {d}")
    d = cik_mod.decide(former, [cand(1, {"membership_continuity", "sec_search_ticker"}, 1.0, None),
                                cand(2, {"sec_search_ticker"}, 1.0, None)])
    req(d["cik"] == "1", f"a ticker-search-only hit must not beat a documented ticker change: {d}")
    d = cik_mod.decide(former, [cand(1, {"membership_continuity"}, 1.0, None)])
    req(d["status"] == "unresolved",
        "joining the index the day another left is a replacement, not a rename (ACS -> Urban Outfitters)")
    d = cik_mod.decide(former, [cand(1, {"sec_search_name"}, 0.9, 1.0), cand(2, {"sec_search_name"}, 0.6, 1.0)])
    req(d["status"] in ("split", "conflict") and not d["cik"], "two named companies -> review, not a guess")
    d = cik_mod.decide(former, [cand(1, {"sec_search_ticker"}, 1.0, None)])
    req(d["status"] == "unresolved" and not d["cik"],
        "a lone ticker-search hit is never used (CBS once matched W.R. Berkley this way)")
    d = cik_mod.decide(former, [cand(1, {"sec_tickers", "sec_search_ticker"}, 1.0, None)])
    req(d["status"] == "unresolved",
        "for a gone ticker, today's owner of the ticker proves nothing (BBT now belongs to another bank)")
    d = cik_mod.decide(former, [cand(1, {"sec_tickers"}, 0.1, None)])
    req(d["status"] == "unresolved", "no annual reports in the window -> unresolved")
    d = cik_mod.decide(current, [cand(7, {"sec_tickers", "wikipedia_current"}, 1.0, 0.0)])
    req(d["status"] == "verified" and d["cik"] == "7",
        "when the SEC list and Wikipedia agree on the ID, a brand name (IBM) needn't match")
    d = cik_mod.decide(former, [cand(1, {"sec_search_name"}, 1.0, 1.0, ["Discover Financial Services"]),
                                cand(2, {"sec_search_name"}, 1.0, 1.0, ["Discover Card Execution Note Trust"])],
                       known_name="Discover Financial")
    req(d["cik"] == "1", f"parent beats subsidiary only by a clearly closer name: {d}")
    d = cik_mod.decide(former, [cand(1, {"sec_search_name"}, 1.0, 1.0, ["DU PONT E I DE NEMOURS & CO"]),
                                cand(2, {"sec_search_name"}, 1.0, 1.0, ["DUPONT FABROS TECHNOLOGY"])],
                       known_name="DuPont")
    req(not d["cik"], "no clear name winner -> review, never a guess")


def t_cik_map_live(ctx) -> None:
    """Two real traps: a reused ticker (ADT 2012-2016 was ADT Corp, not today's ADT)
    and a rename (FB is Meta). Uses cached SEC and Wikipedia data after the first run."""
    want = {("ADT", "2012-10-02"): "1546640", ("FB", "2013-12-23"): "1326801"}
    rows = [r for r in cik_mod.load_membership() if (r.ticker, r.start) in want]
    req(len(rows) == 2, "test rows missing from the membership data")
    for r in cik_mod.build(rows=rows):
        req(r["status"] == "verified" and r["cik"] == want[(r["ticker"], r["start"])],
            f"{r['ticker']} mapped wrong: {r}")


def t_pit_data_rules(ctx) -> None:
    """Point-in-time inputs: split-safe market value, no look-ahead, delisting flagged."""
    import numpy as np
    days = pd.bdate_range("2020-01-01", "2020-03-31")
    raw = pd.Series(np.where(days < pd.Timestamp("2020-02-03"), 100.0, 50.0), index=days)
    px = pd.DataFrame({"Close": [50.0] * len(days), "AdjClose": [50.0] * len(days), "Splits": 0.0}, index=days)
    px.loc[pd.Timestamp("2020-02-03"), "Splits"] = 2.0          # 2-for-1: Yahoo's Close is already halved
    true_cap = lambda t: (1e9 if t < pd.Timestamp("2020-02-03") else 2e9) * raw[t]   # noqa: E731
    for t in (pd.Timestamp("2020-01-20"), pd.Timestamp("2020-03-02")):
        for shares, filed in ((1e9, "2020-01-15"), (2e9, "2020-02-20")):
            if filed > t.strftime("%Y-%m-%d"):
                continue
            got = pit_mod.market_cap(shares, filed, px, t)
            req(abs(got - true_cap(t)) < 1, f"market value wrong across a split: {got} vs {true_cap(t)} on {t}")

    def row(end, val, filed, start=None):
        return {"start": start or f"{int(end[:4])}-01-01", "end": end, "val": val, "filed": filed,
                "form": "10-K", "accn": filed}
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        row("2013-12-31", 80, "2015-02-20"), row("2014-12-31", 100, "2015-02-20"),
        row("2014-12-31", 110, "2016-02-19"),                       # later restatement: must be ignored
        row("2015-12-31", 130, "2016-02-19")]}}}}}
    fu = pit_mod.Fundamentals(facts)
    f = fu.as_of("2016-02-19")
    req(f and f["fy_end"] == "2014-12-31", f"used a report on the day it was filed (look-ahead): {f}")
    f = fu.as_of("2016-02-20")
    req(f["revenue"] == 130 and f["revenue_1"] == 100, f"prior year must be the FIRST-filed value: {f}")
    req(fu.as_of("2018-01-01") is None, "a two-year-old annual report must count as stale")

    # Last-resort revenue label: used only when no total-revenue label covers the year.
    goods = lambda end, val, filed: {"start": f"{int(end[:4]) - 1}-12-31" if end[5:] != "12-31" else f"{end[:4]}-01-01",
                                     "end": end, "val": val, "filed": filed, "form": "10-K"}   # noqa: E731
    lockheed = {"facts": {"us-gaap": {
        "SalesRevenueNet": {"units": {"USD": [goods("2017-12-31", 51.0, "2018-02-08")]}},
        "SalesRevenueGoodsNet": {"units": {"USD": [goods("2017-12-31", 43.9, "2018-02-08")]}}}}}
    req([r["value"] for r in edgar_mod.annual_values(lockheed, "revenue")] == [51.0],
        "goods-only sales must never replace total revenue (Lockheed Martin 2017)")
    gis = {"facts": {"us-gaap": {
        "SalesRevenueGoodsNet": {"units": {"USD": [goods("2016-12-31", 16.6, "2017-06-29")]}}}}}
    req([r["value"] for r in edgar_mod.annual_values(gis, "revenue")] == [16.6],
        "with no total-revenue label, goods sales are the revenue (General Mills before 2018)")

    short = px.loc[:"2020-03-10"]
    r, ended = pit_mod.period_return(short, pd.Timestamp("2020-02-28"), pd.Timestamp("2020-03-31"))
    req(ended and r is not None and abs(r) < 1e-12, "a stock that stops trading mid-month is flagged")
    cal = pd.bdate_range("2020-01-01", "2020-03-11")
    req(pit_mod.month_ends(cal, "2020-01-01")[-1] == pd.Timestamp("2020-02-28"),
        "an unfinished month is not a month-end")


def _screen_month(date, extra=None):
    """Ten synthetic stocks; only G1 and G2 should pass the growth screen."""
    base = {"revenue": 120.0, "revenue_1": 100.0, "revenue_3": 60.0, "operating_income": 24.0,
            "operating_income_1": 20.0, "operating_cash_flow": 30.0, "net_income": 15.0, "capex": 5.0,
            "equity": 50.0, "total_assets": 200.0, "shares": 100.0, "shares_1": 100.0, "mcap": 300.0,
            "missing": "", "spy_next": 0.0}
    rows = []
    for name, change in [("G1", {}), ("G2", {"mcap": 360.0}),
                         ("SLOW", {"revenue_1": 115.0}),                 # 4% growth
                         ("ONEYEAR", {"revenue_3": 110.0}),              # 3-year growth too low
                         ("BURN", {"operating_cash_flow": -1.0}),
                         ("SQUEEZE", {"operating_income": 10.0}),        # margin 20% -> 8%
                         ("DILUTE", {"shares": 110.0}),                  # +10% shares
                         ("PRICEY", {"mcap": 5000.0}),                   # top-10% price/sales
                         ("FLAT1", {"revenue": 100.0}), ("FLAT2", {"revenue": 101.0})]:
        r = {**base, **change, **(extra or {}), "date": date, "ticker": name, "cik": hash(name) % 10**6}
        rows.append(r)
    return pd.DataFrame(rows)


def t_screens_rules(ctx) -> None:
    """Each growth rule bites; a planted edge is found; no edge isn't invented; costs apply."""
    import numpy as np
    g = screens_mod.add_ratios(_screen_month("2015-01-30"))
    picked = set(g.loc[screens_mod.growth_screen(g, screens_mod.RULES["growth-v1"]), "ticker"])
    req(picked == {"G1", "G2"}, f"growth screen picked {picked}")

    typo = _screen_month("2015-01-30")
    typo.loc[typo["ticker"] == "FLAT1", "revenue_1"] = 0.1            # filed in thousands by mistake
    typo.loc[typo["ticker"] == "DILUTE", ["shares", "shares_1"]] = [0.11, 100.0]   # 99.9% "buyback"
    g = screens_mod.add_ratios(typo)
    picked = set(g.loc[screens_mod.growth_screen(g, screens_mod.RULES["growth-v1"]), "ticker"])
    req(picked == {"G1", "G2"}, f"a scale typo must not pass as growth or a buyback: {picked}")
    req(int(g["data_guarded"].sum()) >= 2, "guarded ratios are counted")

    rng = np.random.default_rng(7)
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2012-01-31", periods=120, freq="BME")]
    def panel(edge):
        frames = []
        for d in dates:
            m = pd.concat([_screen_month(d)] * 3, ignore_index=True)
            m["ticker"] = [f"{t}{i // 10}" for i, t in enumerate(m["ticker"])]
            m["cik"] = range(len(m))
            m["ret_next"] = rng.normal(0.01, 0.06, len(m)) + np.where(m["ticker"].str.startswith("G"), edge, 0.0)
            frames.append(m)
        return pd.concat(frames, ignore_index=True)
    with_edge = screens_mod.monthly_returns(panel(0.02), "growth-v1")
    req(screens_mod._t(with_edge["excess"]) > 3, "a planted +2%/month edge must be found")
    req((with_edge["turnover"].iloc[1:] == 0).all() and with_edge["net"].iloc[0] < with_edge["gross"].iloc[0],
        "same picks every month: no turnover after the first; the first purchase pays a cost")
    no_edge = screens_mod.monthly_returns(panel(0.0), "growth-v1")
    req(abs(screens_mod._t(no_edge["excess"])) < 3, "no planted edge: the test must not invent one")


def t_screens_live(ctx) -> None:
    """Real data, two traps: Apple's 2020 4-for-1 split (market value must stay ~$2T)
    and FB, whose prices live under META. Uses cached SEC and Yahoo data after one run."""
    rows = [m for m in pit_mod.membership() if (m.ticker, m.end) in (("AAPL", None), ("FB", "2022-06-09"))]
    req(len(rows) == 2, f"test rows missing: {rows}")
    panel, cov = pit_mod.build_panel(start="2020-06-30", members=rows)
    def cap(t, d):
        r = panel[(panel["ticker"] == t) & (panel["date"] == d)]
        return float(r["mcap"].iloc[0]) if len(r) and r["missing"].iloc[0] == "" else None
    a = cap("AAPL", "2020-09-30")
    req(a and 1.6e12 < a < 2.4e12, f"Apple's market value on 2020-09-30 should be about $2.0T, got {a}")
    req(panel.loc[panel["ticker"] == "FB", "symbol"].iloc[0] == "META", "FB must be priced as META")
    f = cap("FB", "2021-06-30")
    req(f and 0.8e12 < f < 1.2e12, f"Facebook's market value on 2021-06-30 should be about $1.0T, got {f}")


def t_agent_context(ctx) -> None:
    """Memory boxes: locked layers first, templates add nothing, a real edit makes a new
    version, a comment edit doesn't, and nothing private is in the public context folder."""
    import re
    import shutil
    import tempfile
    for agent_id in actx_mod.AGENTS:
        c = actx_mod.load(agent_id)
        titles = [t for t, _ in c.layers]
        req(titles[:3] == ["House rules (locked)", f"Your charter: {c.name} (locked)", "Precedence"],
            f"{agent_id}: locked layers must come first: {titles}")
        req(len(c.layers[1][1]) > 200, f"{agent_id}: charter section missing or too short")
    req(actx_mod.load("bull-advocate").version != actx_mod.load("bear-advocate").version,
        "Bull and Bear share a charter section but must know which side they are")
    with tempfile.TemporaryDirectory() as tmp:
        boxes = Path(tmp) / "agents"
        shutil.copytree(actx_mod.BOXES, boxes)
        notes = boxes / "growth-hunter" / "notes.md"
        base = actx_mod.load("growth-hunter", boxes=boxes)
        notes.write_text(notes.read_text(encoding="utf-8").replace("e.g.", "for example"), encoding="utf-8")
        req(actx_mod.load("growth-hunter", boxes=boxes).version == base.version,
            "editing only a guidance comment must not change the agent's version")
        notes.write_text(notes.read_text(encoding="utf-8") + "\nWatch customer concentration.\n",
                         encoding="utf-8")
        edited = actx_mod.load("growth-hunter", boxes=boxes)
        req(edited.version != base.version and "Watch customer concentration." in edited.text(),
            "a real note must reach the agent and make a new version")
        req(edited.text().index("Precedence") < edited.text().index("Watch customer concentration."),
            "notes come after the precedence rule")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for path in (actx_mod.ROOT / "context").rglob("*"):
        if path.is_file() and path.suffix in (".md", ".json", ".csv"):
            req(not email.search(path.read_text(encoding="utf-8", errors="ignore")),
                f"an email address is in the public context folder: {path}")


def t_usage(ctx) -> None:
    """Anonymous usage log: validates input, stores nothing personal, summarizes."""
    db_mod.init()
    usage_mod.record("sess-aaaaaaaa", "page_view")
    usage_mod.record("sess-aaaaaaaa", "tab_open", "game")
    usage_mod.record("sess-aaaaaaaa", "tab_open", "game")
    usage_mod.record("sess-bbbbbbbb", "tab_open", "learn")
    usage_mod.record("sess-bbbbbbbb", "analyze", "nvda", {"from": "search"})
    for bad in (("short", "page_view", ""),                       # session id too short
                ("sess-aaaaaaaa", "hack", ""),                     # unknown event
                ("sess-aaaaaaaa", "tab_open", "<script>"),         # unsafe target
                ("sess-aaaaaaaa", "tab_open", "x" * 65)):          # target too long
        try:
            usage_mod.record(*bad)
            req(False, f"bad usage event accepted: {bad}")
        except usage_mod.UsageError:
            pass
    try:
        usage_mod.record("sess-aaaaaaaa", "page_view", "", {"blob": "x" * 2000})
        req(False, "oversized meta accepted")
    except usage_mod.UsageError:
        pass
    s = usage_mod.summary(30)
    req(s["events"] == 5 and s["sessions"] == 2, f"usage counts wrong: {s}")
    req(s["top_tabs"][0] == {"name": "game", "count": 2}, "top tab wrong")
    req(s["top_tickers"] == [{"name": "NVDA", "count": 1}], "tickers should be upper-cased")
    req(len(s["by_day"]) == 1 and s["by_day"][0]["sessions"] == 2, "by-day summary wrong")
    cols = {r[1] for r in db_mod.query("PRAGMA table_info(usage_events)")}
    req(cols == {"id", "ts", "session_id", "event", "target", "meta"},
        f"usage_events must not gain personal columns: {cols}")


def t_api_lab(ctx) -> None:
    """Usage endpoint validates input; Lab data is closed to other computers
    unless the right ADMIN_TOKEN is given."""
    import asyncio as _asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from backend import main as main_mod  # db.init() runs on the throwaway DB

    def from_host(host):
        return SimpleNamespace(client=SimpleNamespace(host=host))

    def status_of(coro) -> int:
        try:
            _asyncio.run(coro)
            return 200
        except HTTPException as exc:
            return exc.status_code

    run = _asyncio.run
    req(run(main_mod.usage_event("sess-cccccccc", "tab_open", "learn"))["status"] == "ok",
        "valid usage event rejected")
    req(status_of(main_mod.usage_event("bad", "tab_open", "")) == 400, "bad session id accepted")
    req(status_of(main_mod.usage_event("sess-cccccccc", "drop_table", "")) == 400,
        "unknown event accepted")

    saved = main_mod.ADMIN_TOKEN
    try:
        main_mod.ADMIN_TOKEN = ""
        s = run(main_mod.usage_summary(from_host("127.0.0.1"), 30, ""))
        req(s["events"] >= 1, "local admin summary should work without a token")
        req(status_of(main_mod.usage_summary(from_host("203.0.113.5"), 30, "")) == 403,
            "another computer read admin data with no token configured")
        req(status_of(main_mod.ledger_overview(from_host("203.0.113.5"), "", 10)) == 403,
            "another computer read the ledger with no token configured")
        led = run(main_mod.ledger_overview(from_host("::1"), "", 10))
        req("agents" in led and "calls" in led, "ledger overview payload incomplete")

        main_mod.ADMIN_TOKEN = "s3cret-test-token"
        req(status_of(main_mod.usage_summary(from_host("127.0.0.1"), 30, "wrong")) == 403,
            "a wrong token was accepted")
        req(status_of(main_mod.usage_summary(from_host("203.0.113.5"), 30,
                                             "s3cret-test-token")) == 200,
            "the right token should open the Lab from anywhere")
    finally:
        main_mod.ADMIN_TOKEN = saved


def t_paper(ctx) -> None:
    # Full lifecycle against the local DB; leaves the account reset.
    db_mod.init()
    paper_mod.reset()
    r = paper_mod.place_trade(TICKER, "buy", 5,
                              thesis="Regime is Bull and relative strength is top quintile",
                              exit_rule="sell below the 50-day MA", source_tab="Quant")
    req(r["status"] == "filled" and r["price"] > 0, "buy did not fill")
    pf = paper_mod.get_portfolio()
    req(len(pf.positions) == 1 and abs(pf.positions[0].qty - 5) < 1e-9,
        "position not recorded")
    req(abs(pf.cash - (db_mod.PAPER_STARTING_CASH - r["value"])) < 0.01,
        "cash not debited correctly")
    paper_mod.place_trade(TICKER, "sell", 5, thesis="Closing the position")
    pf = paper_mod.get_portfolio()
    req(not pf.positions, "position not closed after full sell")
    try:
        paper_mod.place_trade(TICKER, "sell", 1, thesis="closing out")
        req(False, "oversell was not rejected")
    except paper_mod.TradeError:
        pass
    # reflection is mandatory on buys
    for kw in ({}, {"thesis": "too short"}, {"thesis": "a" * 20, "exit_rule": "stop at -8%"}):
        try:
            paper_mod.place_trade(TICKER, "buy", 1, **kw)
            req(False, f"buy accepted without reflection: {kw}")
        except paper_mod.TradeError:
            pass
    pc = paper_mod.precheck(TICKER)
    req("last_price" in pc and "nudge" in pc, "precheck payload incomplete")
    paper_mod.reset()
    pf = paper_mod.get_portfolio()
    req(pf.cash == db_mod.PAPER_STARTING_CASH and pf.n_trades == 0,
        "reset did not restore starting state")


def t_game(ctx) -> None:
    import json as _json
    db_mod.init()
    game_mod.reset()
    r = game_mod.new_round(seed=7)
    blob = _json.dumps({k: v for k, v in r.items() if k != "round_id"})
    for tick in db_mod.DEFAULT_WATCHLIST:
        req(f'"{tick}"' not in blob.upper(), f"game payload leaks ticker {tick}")
    req(r["prices"][0] == 100.0, "game chart not rebased to 100")
    req("date" not in blob.lower(), "game payload leaks dates")
    g = game_mod.submit_guess(r["round_id"], "long", 80)
    req(g["pnl_pct"] is not None and g["correct"] in (0, 1), "guess not scored")
    req(bool(g["reveal"]["ticker"]), "reveal missing ticker")
    try:
        game_mod.submit_guess(r["round_id"], "long", 80)
        req(False, "double answer accepted")
    except game_mod.GameError:
        pass
    s = game_mod.get_stats()
    req(s["rounds"] == 1 and s["decisions"] == 1, "stats wrong")
    h = game_mod.get_habits()
    req(h["rounds"] == 1 and h["decided"] == 1, "habits counts wrong")
    req(isinstance(h["explanations"], dict) and len(h["explanations"]) == 3,
        "habits should explain all three measures")
    for k in ("trend_chasing", "overconfidence_gap", "pass_discipline"):
        req(k in h, f"habits missing {k}")
    game_mod.reset()


FAST_TESTS = [
    ("test_isolation", t_test_isolation),
    ("data", t_data),
    ("indicators", t_indicators),
    ("signals", t_signals),
    ("regime", t_regime),
    ("risk", t_risk),
    ("distribution", t_distribution),
    ("backtest", t_backtest),
    ("quant_score", t_quant_score),
    ("peers", t_peers),
    ("sentiment", t_sentiment),
    ("news_feed", t_news_feed),
    ("statistics", t_statistics),
    ("spectral", t_spectral),
    ("topology", t_topology),
    ("manifold", t_manifold),
    ("regime_hmm", t_regime_hmm),
    ("valuation", t_valuation),
    ("catalyst", t_catalyst),
    ("whatif", t_whatif),
    ("glossary", t_glossary),
    ("paper", t_paper),
    ("game", t_game),
    ("backtest_rigor", t_backtest_rigor),
    ("factors", t_factors),
    ("macro", t_macro),
    ("news_archive", t_news_archive),
    ("universe", t_universe),
    ("crisis", t_crisis),
    ("crisis_rounds", t_crisis_rounds),
    ("ledger", t_ledger),
    ("trend_twin", t_trend_twin),
    ("usage", t_usage),
    ("api_lab", t_api_lab),
    ("model_card_rules", t_model_card_rules),
    ("model_calls_ledger", t_model_calls_ledger),
    ("model_cards_live", t_model_cards_live),
    ("edgar_parsing", t_edgar_parsing),
    ("edgar_live", t_edgar_live),
    ("cik_map_rules", t_cik_map_rules),
    ("cik_map_live", t_cik_map_live),
    ("pit_data_rules", t_pit_data_rules),
    ("screens_rules", t_screens_rules),
    ("screens_live", t_screens_live),
    ("agent_context", t_agent_context),
]
SLOW_TESTS = [("score_backtest", t_score_backtest)]


def main(argv: list[str]) -> int:
    full = "--full" in argv
    print(f"Test database: {db_mod.use_throwaway_database()} (real data is never touched)")
    print(f"Loading shared context ({TICKER} + SPY)...")
    td = data_mod.load(TICKER)
    if td is None:
        print(f"FATAL: could not load {TICKER}. Network / yfinance down?")
        return 1
    bench_td = data_mod.load("SPY")
    bench_df = bench_td.history if bench_td else None
    df = ind_mod.compute_all(td.history)
    df_ready = df.dropna(subset=["SMA200", "MACD_HIST", "VOL30"])
    ctx = {
        "td": td,
        "close": td.history["Close"],
        "bench_df": bench_df,
        "bench_close": bench_df["Close"] if bench_df is not None else None,
        "df_ready": df_ready,
    }

    tests = FAST_TESTS + (SLOW_TESTS if full else [])
    if not full:
        print(f"(skipping {len(SLOW_TESTS)} slow walk-forward test; pass --full to include)\n")

    passed = 0
    for name, fn in tests:
        try:
            fn(ctx)
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as exc:
            _FAILURES.append(name)
            print(f"  [FAIL] {name}: {exc}")
            if not isinstance(exc, AssertionError):
                traceback.print_exc()

    print(f"\n{passed}/{len(tests)} modules passed.")
    if _FAILURES:
        print(f"FAILED: {', '.join(_FAILURES)}")
        return 1
    print("All green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
