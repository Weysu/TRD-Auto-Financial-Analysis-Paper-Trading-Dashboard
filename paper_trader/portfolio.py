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
import math
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
            current_prices.get(p["symbol"], p["entry_price"])
            * (p.get("shares_remaining") or p["shares"])
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

    def check_exits(
        self, current_prices: dict[str, float]
    ) -> list[dict[str, Any]]:
        """
        Check every open position for stop-loss, trailing-stop, and multi-level
        take-profit exits.

        Side effects
        ------------
        * Updates ``highest_price`` in the database for any new high seen.
        * Marks TP levels as hit (``tpN_hit``) and moves the dynamic SL
          when a take-profit threshold is crossed.

        The actual partial/full close (trade record + cash update) is
        performed later by the caller via :meth:`sell`.

        Parameters
        ----------
        current_prices:
            Mapping of ``symbol → current price``.  Positions whose symbol
            is absent are skipped.

        Returns
        -------
        list[dict] — one entry per triggered exit (a position may contribute
        multiple entries when several TP levels fire in the same cycle).
        Keys: ``position_id`` (int), ``symbol`` (str),
        ``shares_to_close`` (float), ``reason`` (str),
        ``current_price`` (float), ``pnl`` (float), ``pnl_pct`` (float).
        """
        results: list[dict[str, Any]] = []
        positions = db.get_open_positions(self._cfg.bot_id)
        tp_levels = self._cfg.take_profit_levels

        for pos in positions:
            symbol: str = pos["symbol"]
            current_price = current_prices.get(symbol)
            if current_price is None or math.isnan(current_price):
                continue

            entry: float = pos["entry_price"]
            if entry <= 0:
                continue

            pos_id: int = pos["id"]
            shares_remaining: float = pos.get("shares_remaining") or pos["shares"]

            # ── 1. Update highest price ───────────────────────────────────
            highest: float = pos.get("highest_price") or entry
            if current_price > highest:
                db.update_highest_price(pos_id, current_price)
                highest = current_price

            current_sl_price: float = (
                pos.get("current_sl_price") or entry * (1.0 - self._cfg.stop_loss_pct)
            )

            # ── 2. Trailing stop (last TP with target_pct=="trailing_5pct") ──
            # Only fires when all preceding fixed TPs have been hit.
            trailing_triggered = False
            if tp_levels and tp_levels[-1].get("target_pct") == "trailing_5pct":
                n_fixed = len(tp_levels) - 1
                all_prev_hit: bool = all(
                    pos.get(f"tp{i + 1}_hit", 0) for i in range(n_fixed)
                )
                if all_prev_hit:
                    trailing_trigger: float = highest * 0.95
                    if current_price <= trailing_trigger:
                        trailing_triggered = True
                        pnl = (current_price - entry) * shares_remaining
                        pnl_pct = (current_price - entry) / entry * 100.0
                        results.append(
                            {
                                "position_id":   pos_id,
                                "symbol":        symbol,
                                "shares_to_close": shares_remaining,
                                "reason":        "trailing_stop",
                                "current_price": current_price,
                                "pnl":           pnl,
                                "pnl_pct":       pnl_pct,
                            }
                        )

            if trailing_triggered:
                continue

            # ── 3. Stop loss ──────────────────────────────────────────────
            if current_price <= current_sl_price:
                pnl = (current_price - entry) * shares_remaining
                pnl_pct = (current_price - entry) / entry * 100.0
                results.append(
                    {
                        "position_id":   pos_id,
                        "symbol":        symbol,
                        "shares_to_close": shares_remaining,
                        "reason":        "stop_loss",
                        "current_price": current_price,
                        "pnl":           pnl,
                        "pnl_pct":       pnl_pct,
                    }
                )
                continue

            # ── 4. Take-profit levels ─────────────────────────────────────
            # Exclude trailing placeholder from fixed-TP checks.
            n_fixed_tps: int = (
                len(tp_levels) - 1
                if tp_levels and tp_levels[-1].get("target_pct") == "trailing_5pct"
                else len(tp_levels)
            )
            running_remaining = shares_remaining

            for i, tp in enumerate(tp_levels[:n_fixed_tps]):
                tp_col = f"tp{i + 1}_hit"
                if pos.get(tp_col, 0):
                    continue  # already hit

                target_pct = tp.get("target_pct", 0.0)
                if not isinstance(target_pct, (int, float)):
                    continue  # skip non-numeric (e.g., "trailing_5pct")

                tp_price: float = entry * (1.0 + float(target_pct))
                if current_price < tp_price:
                    break  # levels are ordered ascending; no need to check further

                close_fraction: float = float(tp.get("close_fraction", 1.0))
                shares_closed: float = running_remaining * close_fraction
                pnl = (current_price - entry) * shares_closed
                pnl_pct = (current_price - entry) / entry * 100.0
                reason = f"tp{i + 1}"

                # Persist TP hit + SL move before executor calls sell.
                db.update_position_tp_hit(pos_id, i + 1)

                move_sl_to = tp.get("move_sl_to")
                if move_sl_to is not None:
                    if move_sl_to == 0.0:
                        db.update_position_sl(pos_id, entry, 0.0)
                    elif isinstance(move_sl_to, str) and move_sl_to.startswith("tp"):
                        ref_idx = int(move_sl_to[2:]) - 1
                        if ref_idx < len(tp_levels):
                            ref_target = tp_levels[ref_idx].get("target_pct", 0.0)
                            if isinstance(ref_target, (int, float)):
                                new_sl = entry * (1.0 + float(ref_target))
                                db.update_position_sl(pos_id, new_sl, float(ref_target))

                results.append(
                    {
                        "position_id":   pos_id,
                        "symbol":        symbol,
                        "shares_to_close": shares_closed,
                        "reason":        reason,
                        "current_price": current_price,
                        "pnl":           pnl,
                        "pnl_pct":       pnl_pct,
                    }
                )
                running_remaining -= shares_closed
                if running_remaining <= 1e-9:
                    break

        return results

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
            self._cfg.bot_id, symbol, source, price, shares, strategy,
            stop_loss_pct=self._cfg.stop_loss_pct,
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
        shares_to_close: float | None = None,
        reason: str = "signal",
    ) -> dict[str, Any]:
        """
        Partially or fully close an open position and credit the proceeds to cash.

        Parameters
        ----------
        shares_to_close:
            Shares to close.  ``None`` closes all remaining shares.
        reason:
            Exit reason — ``"signal"``, ``"stop_loss"``, ``"tp1"``–``"tp4"``,
            or ``"trailing_stop"``.

        Returns
        -------
        The closed trade dict, or ``{}`` if the position is not found.
        """
        trade = db.close_position(position_id, price, shares_to_close=shares_to_close, reason=reason)
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

    # ------------------------------------------------------------------
    # Position queries
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list[dict[str, Any]]:
        """Return all open positions for this bot."""
        return db.get_open_positions(self._cfg.bot_id)

    def get_open_symbols(self) -> set[str]:
        """Return the set of symbols currently held by this bot."""
        return {p["symbol"] for p in self.get_open_positions()}

