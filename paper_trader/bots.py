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
    "equity_trend": BotConfig(
        bot_id="equity_trend",
        name="Equity Trend",
        description="Multi-signal trend following on equities — CFD mode with trailing stop",
        initial_capital=10_000.0,
        max_position_pct=0.15,
        min_confluence=2,
        sell_threshold=0,
        strategy_filter=("ma", "rsi", "bb", "macd"),
        timeframe="1Y",
        stop_loss_pct=0.08,
        take_profit_levels=(
            {"target_pct": 0.08,               "close_fraction": 0.25, "move_sl_to": 0.0},
            {"target_pct": 0.15,               "close_fraction": 0.35, "move_sl_to": "tp1"},
            {"target_pct": 0.25,               "close_fraction": 0.25, "move_sl_to": "tp2"},
            {"target_pct": "trailing_2.5pct",  "close_fraction": 1.00, "move_sl_to": None},
        ),
        cycle_hours=6,
        use_sentiment=False,
        use_trend_filter=True,
        asset_universe="stocks",
    ),

    # ── Disabled bots ──────────────────────────────────────────────────────────────
    # "crypto_trend":    crypto momentum (MA + MACD, 10k, crypto universe)
    # "crypto_reversion": mean reversion (RSI + BB, 10k, crypto universe)
    # "equity_quality":  high-conviction equities (3 signals, SMA200 filter)
    # "scanner":         full-universe max-confluence scanner
    # "breakout":        BB + MACD breakout on all assets
}


def get_assets_for_bot(bot: BotConfig) -> dict[str, dict]:
    """Return the asset subset this bot should scan."""
    from trd_auto.config.assets import STOCK_ASSETS, CRYPTO_ASSETS, ALL_ASSETS  # noqa: PLC0415
    if bot.asset_universe == "crypto":
        return CRYPTO_ASSETS
    if bot.asset_universe == "stocks":
        return STOCK_ASSETS
    return ALL_ASSETS
