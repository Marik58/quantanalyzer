"""Paper trading — simulated portfolio marked to market with live prices.

Educational scaffolding, not a broker simulator: market orders only, filled
at the latest close from data.load, no margin, no shorting, no costs. The
point is to let a student act on the app's analysis and then live with a
position — the part of investing no diagnostic tab can teach.

Accounting: average-cost basis. Sells realize (price - avg_cost) * qty;
buys re-average. Positions and realized P&L are derived from the trade log
on every read, so the log is the single source of truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend import db
from backend.analysis import data as data_mod

MAX_TICKERS = 50           # sanity cap on distinct open positions
MIN_QTY = 1e-6

# Reflection requirements. The mobile-apps study (Liu et al. 2025) found that
# removing friction raised trend-chasing with no performance gain, and its
# authors recommend prompts that make people stop and think. These minimums
# are deliberately small — enough to force a sentence, not enough to annoy.
MIN_THESIS_CHARS = 15
MIN_EXIT_CHARS = 5
NUDGE_1M_MOVE = 10.0       # |1-month move| beyond this raises the prompt

REVIEW_OPTIONS = [
    "Thesis was right, timing was wrong",
    "Thesis was wrong",
    "I did not follow my exit rule",
    "Right, but for a reason I did not expect",
    "Right, for the stated reason",
]


@dataclass
class Position:
    ticker: str
    qty: float
    avg_cost: float
    last_price: float | None = None
    market_value: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_pct: float | None = None


@dataclass
class Portfolio:
    cash: float
    positions: list[Position] = field(default_factory=list)
    realized_pl: float = 0.0
    unrealized_pl: float = 0.0
    journal: list[dict[str, Any]] = field(default_factory=list)
    total_equity: float = 0.0          # cash + market value of positions
    total_pl: float = 0.0              # equity - starting cash
    starting_cash: float = db.PAPER_STARTING_CASH
    n_trades: int = 0
    explanations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TradeError(ValueError):
    """User-correctable trade rejection (bad qty, not enough cash/shares)."""


def _replay_trades() -> tuple[dict[str, dict[str, float]], float, int]:
    """Rebuild positions {ticker: {qty, avg_cost}} + realized P&L from the log."""
    positions: dict[str, dict[str, float]] = {}
    realized = 0.0
    trades = db.paper_trades()
    for t in trades:
        tick, side, qty, price = t["ticker"], t["side"], t["qty"], t["price"]
        pos = positions.setdefault(tick, {"qty": 0.0, "avg_cost": 0.0})
        if side == "buy":
            total_cost = pos["qty"] * pos["avg_cost"] + qty * price
            pos["qty"] += qty
            pos["avg_cost"] = total_cost / pos["qty"] if pos["qty"] > 0 else 0.0
        else:  # sell
            realized += (price - pos["avg_cost"]) * qty
            pos["qty"] -= qty
        if pos["qty"] <= MIN_QTY:
            positions.pop(tick, None)
    return positions, realized, len(trades)


def get_portfolio() -> Portfolio:
    raw, realized, n_trades = _replay_trades()
    cash = db.paper_cash()
    pf = Portfolio(cash=round(cash, 2), realized_pl=round(realized, 2),
                   n_trades=n_trades)

    total_mv = 0.0
    total_unreal = 0.0
    for tick, p in sorted(raw.items()):
        pos = Position(ticker=tick, qty=round(p["qty"], 4),
                       avg_cost=round(p["avg_cost"], 4))
        td = data_mod.load(tick)
        if td is not None:
            last = td.last_price
            mv = p["qty"] * last
            unreal = (last - p["avg_cost"]) * p["qty"]
            pos.last_price = round(last, 2)
            pos.market_value = round(mv, 2)
            pos.unrealized_pl = round(unreal, 2)
            pos.unrealized_pl_pct = (round((last / p["avg_cost"] - 1.0) * 100.0, 2)
                                     if p["avg_cost"] > 0 else None)
            total_mv += mv
            total_unreal += unreal
        pf.positions.append(pos)

    pf.unrealized_pl = round(total_unreal, 2)
    pf.total_equity = round(cash + total_mv, 2)
    pf.total_pl = round(pf.total_equity - pf.starting_cash, 2)

    pl_pct = (pf.total_pl / pf.starting_cash) * 100.0
    pf.journal = journal()
    pf.explanations = {
        "overview": (
            f"Paper account: ${pf.total_equity:,.0f} total equity "
            f"(${pf.cash:,.0f} cash + {len(pf.positions)} position(s)) — "
            f"{pl_pct:+.1f}% vs the ${pf.starting_cash:,.0f} start."
        ),
        "how_it_works": (
            "Orders fill at the latest close — no spreads, slippage, or costs, "
            "which flatters every result. Realized P&L uses average-cost basis; "
            "unrealized is marked to the latest price on each refresh."
        ),
        "how_to_use": (
            "Before each trade, write down WHY (which tab convinced you) and "
            "what would make you exit. The gap between your plan and what you "
            "actually do when the position moves is the real lesson here."
        ),
    }
    return pf


def precheck(ticker: str) -> dict[str, Any]:
    """What the order form shows before the trade: price, recent move, and a nudge."""
    ticker = ticker.upper().strip()
    td = data_mod.load(ticker)
    if td is None:
        raise TradeError(f"No price data for '{ticker}' — check the symbol.")
    close = td.history["Close"].dropna()
    ret_1m = (float(close.iloc[-1] / close.iloc[-22] - 1.0) * 100.0
              if len(close) > 22 else None)
    nudge = None
    if ret_1m is not None and abs(ret_1m) >= NUDGE_1M_MOVE:
        if ret_1m > 0:
            nudge = (f"{ticker} is up {ret_1m:.1f}% in the past month. Is this trade "
                     f"based on your analysis, or on the move itself?")
        else:
            nudge = (f"{ticker} is down {abs(ret_1m):.1f}% in the past month. Are you "
                     f"buying a thesis, or catching a falling knife?")
    return {"ticker": ticker, "last_price": round(td.last_price, 2),
            "ret_1m_pct": None if ret_1m is None else round(ret_1m, 1),
            "nudge": nudge, "review_options": REVIEW_OPTIONS}


def place_trade(ticker: str, side: str, qty: float,
                thesis: str = "", exit_rule: str = "",
                source_tab: str = "") -> dict[str, Any]:
    """Validate + execute a market order at the latest close. Raises TradeError.

    Buys must carry a thesis, an exit rule, and the tab that convinced you;
    sells must say why. The trade is recorded with them so the journal can ask
    afterwards whether the thesis actually played out.
    """
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        raise TradeError("side must be 'buy' or 'sell'")
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise TradeError("qty must be a number")
    if not (qty > 0) or qty > 1e9:
        raise TradeError("qty must be positive (and sane)")

    thesis, exit_rule, source_tab = thesis.strip(), exit_rule.strip(), source_tab.strip()
    if side == "buy":
        if len(thesis) < MIN_THESIS_CHARS:
            raise TradeError(
                f"Say why in at least {MIN_THESIS_CHARS} characters. Writing the thesis "
                f"before the trade is the point of paper trading.")
        if len(exit_rule) < MIN_EXIT_CHARS:
            raise TradeError("Add an exit rule — the price or condition that ends this trade.")
        if not source_tab:
            raise TradeError("Pick which tab convinced you.")
    elif len(thesis) < MIN_EXIT_CHARS:
        raise TradeError("Say why you are closing this position.")

    ticker = ticker.upper().strip()
    td = data_mod.load(ticker)
    if td is None:
        raise TradeError(f"No price data for '{ticker}' — check the symbol.")
    price = td.last_price
    cost = qty * price

    positions, _, _ = _replay_trades()
    cash = db.paper_cash()

    if side == "buy":
        if cost > cash + 1e-6:
            raise TradeError(
                f"Not enough cash: {qty:g} × ${price:,.2f} = ${cost:,.2f}, "
                f"but the account has ${cash:,.2f}.")
        if ticker not in positions and len(positions) >= MAX_TICKERS:
            raise TradeError(f"Position limit ({MAX_TICKERS} tickers) reached.")
        db.paper_record_trade(ticker, "buy", qty, price, thesis, exit_rule, source_tab)
        db.paper_set_cash(cash - cost)
    else:
        held = positions.get(ticker, {}).get("qty", 0.0)
        if qty > held + 1e-6:
            raise TradeError(
                f"Cannot sell {qty:g} {ticker} — the account holds {held:g}. "
                f"(No shorting in paper mode.)")
        db.paper_record_trade(ticker, "sell", qty, price, thesis, exit_rule, source_tab)
        db.paper_set_cash(cash + cost)

    return {
        "status": "filled",
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": round(price, 2),
        "value": round(cost, 2),
    }


def journal() -> list[dict[str, Any]]:
    """Every trade with its stated reason, newest first, flagged if it needs a review."""
    trades = db.paper_trades()
    out: list[dict[str, Any]] = []
    for t in trades:
        needs_review = (t["side"] == "sell" and not t["review"])
        out.append({**t, "needs_review": needs_review})
    return list(reversed(out))


def record_review(trade_id: int, review: str) -> dict[str, Any]:
    review = (review or "").strip()
    if review not in REVIEW_OPTIONS:
        raise TradeError("Pick one of the listed outcomes.")
    ids = {t["id"] for t in db.paper_trades()}
    if trade_id not in ids:
        raise TradeError(f"Trade {trade_id} not found.")
    db.paper_set_review(trade_id, review)
    return {"status": "saved", "trade_id": trade_id, "review": review}


def reset() -> None:
    db.paper_reset()
