"""
paper_trader.bots
=================
Centralised bot registry.  Each ``BotConfig`` is a frozen dataclass that
fully describes one trading bot's behaviour — capital, risk parameters,
strategy filter, timeframe, and confluence threshold.

Adding a new bot requires only a new entry in ``BOTS``; no other module
needs to be touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotConfig:
    """Immutable configuration for a single paper-trading bot."""

    bot_id: str
    """Unique machine-readable identifier.  Used as the database key."""

    name: str
    """Human-readable display name."""

    description: str
    """One-line strategy summary shown in the monitor."""

    initial_capital: float
    """Starting cash balance in USD."""

    max_position_pct: float
    """Maximum fraction of current cash to allocate per buy (0.0 – 1.0)."""

    min_confluence: int
    """Minimum confluence score required to open a new position."""

    strategy_filter: list[str]
    """
    Subset of strategies to include in confluence scoring.
    Valid keys: ``"ma"``, ``"rsi"``, ``"bb"``, ``"macd"``.
    """

    timeframe: str
    """
    Period label passed to the data connector.
    Must match a label defined in ``config.assets.TIME_RANGES``
    (e.g. ``"1M"``, ``"3M"``, ``"1Y"``).
    """

    stop_loss_pct: float
    """Fraction below entry price that triggers a stop-loss exit (e.g. 0.07 = 7 %)."""

    take_profit_pct: float
    """Fraction above entry price that triggers a take-profit exit (e.g. 0.15 = 15 %)."""


# ---------------------------------------------------------------------------
# Bot registry
# ---------------------------------------------------------------------------

BOTS: dict[str, BotConfig] = {
    "confluence": BotConfig(
        bot_id="confluence",
        name="Confluence",
        description="Multi-signal conservative — waits for 3+ aligned signals",
        initial_capital=10_000.0,
        max_position_pct=0.20,
        min_confluence=3,
        strategy_filter=["ma", "rsi", "bb", "macd"],
        timeframe="1Y",
        stop_loss_pct=0.07,
        take_profit_pct=0.15,
    ),
    "momentum": BotConfig(
        bot_id="momentum",
        name="Momentum",
        description="Rides strong trends — MACD + sentiment only",
        initial_capital=10_000.0,
        max_position_pct=0.25,
        min_confluence=2,
        strategy_filter=["macd"],
        timeframe="3M",
        stop_loss_pct=0.05,
        take_profit_pct=0.12,
    ),
    "mean_reversion": BotConfig(
        bot_id="mean_reversion",
        name="Mean Reversion",
        description="Buys dips — RSI oversold + BB lower touch",
        initial_capital=10_000.0,
        max_position_pct=0.20,
        min_confluence=2,
        strategy_filter=["rsi", "bb"],
        timeframe="3M",
        stop_loss_pct=0.06,
        take_profit_pct=0.10,
    ),
    "trend": BotConfig(
        bot_id="trend",
        name="Trend Following",
        description="Long term trend — MA Crossover on weekly data",
        initial_capital=10_000.0,
        max_position_pct=0.30,
        min_confluence=2,
        strategy_filter=["ma"],
        timeframe="1Y",
        stop_loss_pct=0.08,
        take_profit_pct=0.20,
    ),
    "scalper": BotConfig(
        bot_id="scalper",
        name="Scalper",
        description="Aggressive short-term — fast signals, strict risk management",
        initial_capital=10_000.0,
        max_position_pct=0.10,
        min_confluence=2,
        strategy_filter=["macd", "rsi"],
        timeframe="1M",
        stop_loss_pct=0.03,
        take_profit_pct=0.06,
    ),
}
