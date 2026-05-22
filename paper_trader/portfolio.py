"""
paper_trader.portfolio
======================
Portfolio manager.  Wraps the SQLite persistence layer (``paper_trader.db``)
to provide cash-flow aware buy / sell / summary operations.

The class is intentionally thin: all state lives in the database so the
engine and the Streamlit monitor share a consistent view without in-process
synchronisation.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Ensure the project root is in sys.path so that ``paper_trader.db`` is
# importable regardless of how this module is invoked.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from paper_trader import db  # noqa: E402  (path setup must come first)

logger = logging.getLogger(__name__)


class Portfolio:
    """Manages cash, open positions, and trade history for the paper trader."""

    def __init__(self, initial_capital: float = 10_000.0) -> None:
        db.init_db(initial_capital)
        portfolio = db.get_portfolio()
        self._initial_capital: float = portfolio.get("initial_capital", initial_capital)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        """Current available cash, read fresh from the database each access."""
        return db.get_portfolio().get("current_capital", 0.0)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def can_buy(self, price: float, shares: float) -> bool:
        """Return ``True`` if the current cash balance covers ``price * shares``."""
        return price * shares <= self.cash

    def get_equity(self, current_prices: dict[str, float]) -> float:
        """
        Return total portfolio equity: cash + mark-to-market open positions.

        Parameters
        ----------
        current_prices:
            Mapping of ``symbol → current price``.  Positions whose symbol
            is absent are valued at their original entry price.
        """
        positions = db.get_open_positions()
        mtm: float = sum(
            current_prices.get(p["symbol"], p["entry_price"]) * p["shares"]
            for p in positions
        )
        return self.cash + mtm

    def get_summary(self, current_prices: dict[str, float]) -> dict[str, Any]:
        """
        Return a high-level portfolio snapshot.

        Keys
        ----
        cash               : float — current cash balance.
        equity             : float — cash + open-position mark-to-market.
        total_return_pct   : float — % return relative to initial capital.
        num_open_positions : int   — count of currently open positions.
        num_closed_trades  : int   — count of fully closed trades.
        """
        equity = self.get_equity(current_prices)
        total_return_pct: float = (
            (equity - self._initial_capital) / self._initial_capital * 100.0
            if self._initial_capital > 0
            else 0.0
        )
        return {
            "cash": self.cash,
            "equity": equity,
            "total_return_pct": total_return_pct,
            "num_open_positions": len(db.get_open_positions()),
            "num_closed_trades": len(db.get_trade_history()),
        }

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def buy(
        self,
        symbol: str,
        source: str,
        price: float,
        shares: float,
        strategy: str,
    ) -> bool:
        """
        Open a new long position and deduct the cost from cash.

        Returns ``True`` on success, ``False`` if funds are insufficient or
        the database write fails.
        """
        cost = price * shares
        if not self.can_buy(price, shares):
            logger.warning(
                "buy(%s): insufficient cash  available=%.2f  required=%.2f",
                symbol,
                self.cash,
                cost,
            )
            return False

        position_id = db.open_position(symbol, source, price, shares, strategy)
        if position_id == -1:
            return False

        db.update_capital(self.cash - cost)
        logger.info(
            "BUY  %-12s  shares=%.6f  @%.4f  cost=%.2f",
            symbol,
            shares,
            price,
            cost,
        )
        return True

    def sell(
        self,
        position_id: int,
        symbol: str,
        price: float,
    ) -> dict[str, Any]:
        """
        Close an open position at ``price`` and credit the proceeds to cash.

        Returns the closed trade dict, or ``{}`` if the position is not found.
        """
        trade = db.close_position(position_id, price)
        if not trade:
            return {}

        proceeds = price * trade["shares"]
        db.update_capital(self.cash + proceeds)
        logger.info(
            "SELL %-12s  shares=%.6f  @%.4f  pnl=%.2f (%.2f%%)",
            symbol,
            trade["shares"],
            price,
            trade["pnl"],
            trade["pnl_pct"],
        )
        return trade
