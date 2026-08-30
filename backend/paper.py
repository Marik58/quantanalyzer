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


def place_trade(ticker: str, side: str, qty: float) -> dict[str, Any]:
    """Validate + execute a market order at the latest close. Raises TradeError."""
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        raise TradeError("side must be 'buy' or 'sell'")
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise TradeError("qty must be a number")
    if not (qty > 0) or qty > 1e9:
        raise TradeError("qty must be positive (and sane)")

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
        db.paper_record_trade(ticker, "buy", qty, price)
        db.paper_set_cash(cash - cost)
    else:
        held = positions.get(ticker, {}).get("qty", 0.0)
        if qty > held + 1e-6:
            raise TradeError(
                f"Cannot sell {qty:g} {ticker} — the account holds {held:g}. "
                f"(No shorting in paper mode.)")
        db.paper_record_trade(ticker, "sell", qty, price)
        db.paper_set_cash(cash + cost)

    return {
        "status": "filled",
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": round(price, 2),
        "value": round(cost, 2),
    }


def reset() -> None:
    db.paper_reset()
