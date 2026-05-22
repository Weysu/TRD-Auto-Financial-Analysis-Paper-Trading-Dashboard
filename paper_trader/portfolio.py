"""
paper_trader.portfolio
======================
Bot-aware portfolio manager.  Wraps the SQLite persistence layer
(``paper_trader.db``) to provide cash-flow aware buy / sell / summary
operations, plus automatic stop-loss / take-profit monitoring.

Every ``Portfolio`` instance is bound to a single ``BotConfig`` and
operates exclusively on that bot's rows in the database.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from paper_trader import db  # noqa: E402
from paper_trader.bots import BotConfig  # noqa: E402

logger = logging.getLogger(__name__)


class Portfolio:
    """Manages cash, open positions, and trade history for one paper-trading bot."""

    def __init__(self, bot_config: BotConfig) -> None:
        from paper_trader.bots import BOTS  # local import avoids circular at module level
        self._cfg: BotConfig = bot_config
        db.init_db(BOTS)
        portfolio = db.get_portfolio(bot_config.bot_id)
        self._initial_capital: float = portfolio.get(
            "initial_capital", bot_config.initial_capital
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bot_id(self) -> str:
        """Identifier of the bot this portfolio belongs to."""
        return self._cfg.bot_id

    @property
    def cash(self) -> float:
        """Current available cash, read fresh from the database each access."""
        return db.get_portfolio(self._cfg.bot_id).get("current_capital", 0.0)

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
        positions = db.get_open_positions(self._cfg.bot_id)
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
        cash               : float
        equity             : float
        total_return_pct   : float
        num_open_positions : int
        num_closed_trades  : int
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
            "num_open_positions": len(db.get_open_positions(self._cfg.bot_id)),
            "num_closed_trades": len(db.get_trade_history(self._cfg.bot_id)),
        }

    def check_stop_loss_take_profit(
        self, current_prices: dict[str, float]
    ) -> list[dict[str, Any]]:
        """
        Check every open position against the bot's stop-loss and take-profit levels.

        Parameters
        ----------
        current_prices:
            Mapping of ``symbol → current price``.  Positions whose symbol is
            absent from the dict are skipped (price unknown).

        Returns
        -------
        list[dict] — one entry per triggered position, with keys:
            ``position_id`` (int), ``symbol`` (str),
            ``reason`` (``"stop_loss"`` | ``"take_profit"``),
            ``current_price`` (float).
        """
        triggered: list[dict[str, Any]] = []
        positions = db.get_open_positions(self._cfg.bot_id)

        for pos in positions:
            symbol: str = pos["symbol"]
            current_price = current_prices.get(symbol)
            if current_price is None or current_price != current_price:  # None or NaN
                continue

            entry: float = pos["entry_price"]
            if entry <= 0:
                continue

            change_pct: float = (current_price - entry) / entry

            if change_pct <= -self._cfg.stop_loss_pct:
                triggered.append(
                    {
                        "position_id": pos["id"],
                        "symbol": symbol,
                        "reason": "stop_loss",
                        "current_price": current_price,
                    }
                )
            elif change_pct >= self._cfg.take_profit_pct:
                triggered.append(
                    {
                        "position_id": pos["id"],
                        "symbol": symbol,
                        "reason": "take_profit",
                        "current_price": current_price,
                    }
                )

        return triggered

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
                "[%s] buy(%s): insufficient cash  available=%.2f  required=%.2f",
                self._cfg.bot_id,
                symbol,
                self.cash,
                cost,
            )
            return False

        position_id = db.open_position(
            self._cfg.bot_id, symbol, source, price, shares, strategy
        )
        if position_id == -1:
            return False

        db.update_capital(self._cfg.bot_id, self.cash - cost)
        logger.info(
            "[%s] BUY  %-12s  shares=%.6f  @%.4f  cost=%.2f",
            self._cfg.bot_id,
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
        reason: str = "signal",
    ) -> dict[str, Any]:
        """
        Close an open position at ``price`` and credit the proceeds to cash.

        Parameters
        ----------
        reason:
            Exit reason — ``"signal"``, ``"stop_loss"``, or ``"take_profit"``.

        Returns
        -------
        The closed trade dict, or ``{}`` if the position is not found.
        """
        trade = db.close_position(position_id, price, reason)
        if not trade:
            return {}

        proceeds = price * trade["shares"]
        db.update_capital(self._cfg.bot_id, self.cash + proceeds)
        logger.info(
            "[%s] SELL %-12s  shares=%.6f  @%.4f  pnl=%.2f (%.2f%%)  reason=%s",
            self._cfg.bot_id,
            symbol,
            trade["shares"],
            price,
            trade["pnl"],
            trade["pnl_pct"],
            reason,
        )
        return trade

