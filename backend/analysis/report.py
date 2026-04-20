"""Plain-English research report assembled from the analysis outputs."""
from __future__ import annotations

from backend.analysis.backtest import BacktestResult
from backend.analysis.distribution import DistributionStats
from backend.analysis.regime import Regime
from backend.analysis.risk import RiskRating
from backend.analysis.signals import Signal


REGIME_BLURB = {
    "uptrend": "in a sustained uptrend",
    "downtrend": "in a sustained downtrend",
    "ranging": "moving sideways without a clear directional bias",
    "breakout_up": "breaking out above its recent range to the upside",
    "breakout_down": "breaking down below its recent range",
}


def build(
    ticker: str, last_price: float, info: dict,
    signal: Signal, regime: Regime, risk: RiskRating,
    dist: DistributionStats, backtest: BacktestResult,
) -> str:
    name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector") or "—"
    pe = info.get("trailingPE")
    pe_str = f"trailing P/E of {pe:.1f}" if isinstance(pe, (int, float)) else "no trailing P/E available"

    paragraphs: list[str] = []

    paragraphs.append(
        f"**{ticker} — {name}** is currently trading near ${last_price:,.2f}. "
        f"It sits in the {sector} sector with {pe_str}. The current quantitative read is "
        f"**{signal.action}** with a composite score of {signal.composite:+.1f}/100 "
        f"and a confidence of {signal.confidence:.0f}%."
    )

    paragraphs.append(
        f"**Regime.** Price action is {REGIME_BLURB.get(regime.label, regime.label)}. "
        f"{regime.description}"
    )

    factor_lines = "\n".join(f"- *{f.name}* ({f.score:+.2f}): {f.explanation}" for f in signal.factors)
    paragraphs.append(f"**What's driving the signal.**\n{factor_lines}")

    paragraphs.append(
        f"**Risk profile.** Rated **{risk.rating.upper()}**. {risk.notes} "
        f"Annualized Sharpe over the last ~2 years sits at {dist.sharpe_annual:+.2f}."
    )

    skew_word = "negatively skewed (more frequent large drops)" if dist.skew < -0.3 else (
        "positively skewed (more frequent large gains)" if dist.skew > 0.3 else "approximately symmetric")
    fat_tail = "fat-tailed (sharper-than-normal moves common)" if dist.kurtosis > 1 else "close to normal-tailed"
    paragraphs.append(
        f"**Return distribution.** Daily returns are {skew_word} and {fat_tail}. "
        f"At the 5% tail, a single-day loss of {dist.var_95:.2%} or worse is historically possible; "
        f"at the 1% tail, that worsens to {dist.var_99:.2%}. "
        f"The most recent session moved {dist.last_return_z:+.1f} standard deviations from the mean."
    )

    bh_word = "outperformed" if backtest.signal_return > backtest.buyhold_return else "underperformed"
    paragraphs.append(
        f"**Backtest sanity check.** Following this signal mechanically over the last ~2 years would have "
        f"returned {backtest.signal_return:+.1%} vs {backtest.buyhold_return:+.1%} for buy-and-hold "
        f"({bh_word}), with {backtest.n_trades} regime changes and a "
        f"{backtest.hit_rate:.0%} hit rate on long days (Sharpe {backtest.sharpe_signal:+.2f}). "
        f"This is a sanity check on the signal's recent behavior, not a guarantee of forward returns."
    )

    paragraphs.append(
        "_Not financial advice — quantitative inputs only. Combine with fundamentals and your own judgement._"
    )

    return "\n\n".join(paragraphs)
