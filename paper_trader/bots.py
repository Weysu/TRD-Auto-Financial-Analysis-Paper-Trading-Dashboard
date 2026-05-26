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

    sell_threshold: int
    """Maximum confluence score at which an open position is closed on signal.
    Typically ``max(0, min_confluence - 2)``."""

    strategy_filter: tuple[str, ...]
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
    """Initial stop-loss: fraction below entry that triggers an exit (e.g. 0.07 = 7 %)."""

    take_profit_levels: tuple[dict, ...]
    """
    Ordered take-profit ladder.  Each dict must contain:

    * ``target_pct`` (float | str): gain fraction from entry (e.g. ``0.10`` for 10 %),
      or the string ``"trailing_5pct"`` (valid only as the *last* level).
    * ``close_fraction`` (float): fraction of remaining shares to close (1.0 = all).
    * ``move_sl_to`` (float | str | None): ``0.0`` → move SL to break-even;
      ``"tp1"`` / ``"tp2"`` → move SL to that level's trigger price; ``None`` → no change.
    """

    cycle_hours: int
    """How often (in hours) the engine should run this bot (e.g. 2, 4, 6, 8)."""

    use_sentiment: bool
    """Whether to fetch and integrate news sentiment into the confluence score."""

    asset_universe: str
    """Asset subset to scan: ``"crypto"``, ``"stocks"``, or ``"all"``."""

    use_trend_filter: bool
    """If True, only allow buy signals when ``is_uptrend_sma200`` returns True."""


# ---------------------------------------------------------------------------
# Bot registry
# ---------------------------------------------------------------------------

BOTS: dict[str, BotConfig] = {

    # ── Crypto ─────────────────────────────────────────────────────────────────────
    "crypto_trend": BotConfig(
        bot_id="crypto_trend",
        name="Crypto Trend",
        description="Rides directional momentum on major crypto assets.",
        initial_capital=10_000.0,
        max_position_pct=0.20,
        min_confluence=2,
        sell_threshold=0,
        strategy_filter=("ma", "macd"),
        timeframe="1Y",
        stop_loss_pct=0.05,
        take_profit_levels=(
            {"target_pct": 0.04, "close_fraction": 0.30, "move_sl_to": 0.0},
            {"target_pct": 0.08, "close_fraction": 0.30, "move_sl_to": "tp1"},
            {"target_pct": 0.15, "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=4,
        use_sentiment=False,
        use_trend_filter=False,
        asset_universe="crypto",
    ),

    "crypto_reversion": BotConfig(
        bot_id="crypto_reversion",
        name="Crypto Mean Reversion",
        description="Buys crypto oversold conditions confirmed by Bollinger Bands.",
        initial_capital=10_000.0,
        max_position_pct=0.15,
        min_confluence=2,
        sell_threshold=0,
        strategy_filter=("rsi", "bb"),
        timeframe="3M",
        stop_loss_pct=0.04,
        take_profit_levels=(
            {"target_pct": 0.03, "close_fraction": 0.50, "move_sl_to": 0.0},
            {"target_pct": 0.06, "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=4,
        use_sentiment=True,
        use_trend_filter=False,
        asset_universe="crypto",
    ),

    # ── Equities ────────────────────────────────────────────────────────────
    "equity_trend": BotConfig(
        bot_id="equity_trend",
        name="Equity Trend",
        description="Follows long-duration trends on stocks above their SMA200.",
        initial_capital=10_000.0,
        max_position_pct=0.15,
        min_confluence=2,
        sell_threshold=0,
        strategy_filter=("ma", "macd"),
        timeframe="1Y",
        stop_loss_pct=0.10,
        take_profit_levels=(
            {"target_pct": 0.08,            "close_fraction": 0.25, "move_sl_to": 0.0},
            {"target_pct": 0.15,            "close_fraction": 0.35, "move_sl_to": "tp1"},
            {"target_pct": 0.25,            "close_fraction": 0.25, "move_sl_to": "tp2"},
            {"target_pct": "trailing_5pct", "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=6,
        use_sentiment=False,
        use_trend_filter=True,
        asset_universe="stocks",
    ),

    "equity_quality": BotConfig(
        bot_id="equity_quality",
        name="Equity Quality",
        description="High-conviction stock setups — 3 signals required, trend confirmed.",
        initial_capital=10_000.0,
        max_position_pct=0.20,
        min_confluence=3,
        sell_threshold=1,
        strategy_filter=("ma", "rsi", "bb", "macd"),
        timeframe="1Y",
        stop_loss_pct=0.07,
        take_profit_levels=(
            {"target_pct": 0.05, "close_fraction": 0.40, "move_sl_to": 0.0},
            {"target_pct": 0.10, "close_fraction": 0.35, "move_sl_to": "tp1"},
            {"target_pct": 0.18, "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=8,
        use_sentiment=True,
        use_trend_filter=True,
        asset_universe="stocks",
    ),

    # ── Multi-asset ─────────────────────────────────────────────────────────
    "scanner": BotConfig(
        bot_id="scanner",
        name="Multi-Asset Scanner",
        description="Scans the full universe — only acts on maximum confluence setups.",
        initial_capital=10_000.0,
        max_position_pct=0.10,
        min_confluence=4,
        sell_threshold=2,
        strategy_filter=("ma", "rsi", "bb", "macd"),
        timeframe="1Y",
        stop_loss_pct=0.07,
        take_profit_levels=(
            {"target_pct": 0.05, "close_fraction": 0.40, "move_sl_to": 0.0},
            {"target_pct": 0.10, "close_fraction": 0.35, "move_sl_to": "tp1"},
            {"target_pct": 0.18, "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=6,
        use_sentiment=True,
        use_trend_filter=False,
        asset_universe="all",
    ),

    "breakout": BotConfig(
        bot_id="breakout",
        name="Breakout Hunter",
        description="Detects Bollinger Band breakouts confirmed by MACD on all assets.",
        initial_capital=10_000.0,
        max_position_pct=0.10,
        min_confluence=2,
        sell_threshold=0,
        strategy_filter=("bb", "macd"),
        timeframe="3M",
        stop_loss_pct=0.02,
        take_profit_levels=(
            {"target_pct": 0.02, "close_fraction": 0.50, "move_sl_to": 0.0},
            {"target_pct": 0.04, "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=2,
        use_sentiment=False,
        use_trend_filter=False,
        asset_universe="all",
    ),
}


def get_assets_for_bot(bot: BotConfig) -> dict[str, dict]:
    """Return the asset subset this bot should scan."""
    from trd_auto.config.assets import STOCK_ASSETS, CRYPTO_ASSETS, ALL_ASSETS  # noqa: PLC0415
    if bot.asset_universe == "crypto":
        return CRYPTO_ASSETS
    if bot.asset_universe == "stocks":
        return STOCK_ASSETS
    return ALL_ASSETS
