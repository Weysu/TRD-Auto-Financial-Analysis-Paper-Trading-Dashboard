"""
paper_trader.executor
=====================
Per-bot signal executor.  ``check_and_execute`` is the single public entry
point: given a ``Portfolio`` and its ``BotConfig``, it:

1. Fetches current prices for all open positions.
2. Runs stop-loss / take-profit checks and exits any triggered positions first.
3. Scans all assets defined in ``trd_auto/config/assets.ALL_ASSETS``.
4. For each asset, computes a confluence score using only the strategies
   listed in ``bot_config.strategy_filter``.
5. Applies the bot's ``min_confluence`` buy threshold and a symmetric
   sell threshold of ``max(0, min_confluence - 2)``.
6. Returns a list of all executed actions with a ``reason`` field.

No Streamlit dependency — safe to run in a plain Python process.
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
_TRDAUTO = os.path.join(_PROJECT_ROOT, "trd_auto")

for _p in (_PROJECT_ROOT, _TRDAUTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# trd_auto imports
# ---------------------------------------------------------------------------
import pandas as pd  # noqa: E402

from config.assets import ALL_ASSETS  # noqa: E402  # kept for type reference
from data.connectors.coingecko import CoinGeckoConnector  # noqa: E402
from data.connectors.yahoo_finance import YahooFinanceConnector  # noqa: E402
from data.base import DataSourceBase  # noqa: E402
from data.strategies import (  # noqa: E402
    run_bollinger_bands,
    run_ma_crossover,
    run_macd_crossover,
    run_rsi_strategy,
)

# ---------------------------------------------------------------------------
# paper_trader imports
# ---------------------------------------------------------------------------
from paper_trader.bots import BotConfig, get_assets_for_bot  # noqa: E402
from paper_trader.portfolio import Portfolio  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONNECTOR_REGISTRY: dict[str, type[DataSourceBase]] = {
    "yahoo": YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}

# Maps strategy_filter keys to their implementation functions.
_STRATEGY_MAP: dict[str, Any] = {
    "ma":   run_ma_crossover,
    "rsi":  run_rsi_strategy,
    "bb":   run_bollinger_bands,
    "macd": run_macd_crossover,
}

# Minimum bars required to run the slowest indicator (MA-50).
_MIN_BARS: int = 60


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fetch_ohlcv(source: str, symbol: str, timeframe: str) -> pd.DataFrame:
    """Fetch OHLCV history for ``symbol`` using the bot's configured timeframe."""
    try:
        connector: DataSourceBase = _CONNECTOR_REGISTRY[source]()
        return connector.get_historical(symbol, timeframe)
    except Exception as exc:
        logger.warning("_fetch_ohlcv(%s, %s): %s", source, symbol, exc)
        return pd.DataFrame()


def _fetch_price(source: str, symbol: str) -> float:
    """Return the latest market price, or ``float('nan')`` on failure."""
    try:
        connector: DataSourceBase = _CONNECTOR_REGISTRY[source]()
        quote = connector.get_quote(symbol)
        return float(quote.get("price", float("nan")))
    except Exception as exc:
        logger.warning("_fetch_price(%s, %s): %s", source, symbol, exc)
        return float("nan")


def _compute_confluence(
    df: pd.DataFrame, strategy_filter: list[str]
) -> tuple[int, list[str]]:
    """
    Compute a confluence score using only the strategies in ``strategy_filter``.

    Each active strategy (``position == 1`` on the last bar) contributes +1.
    Returns ``(0, [])`` if the DataFrame has fewer than ``_MIN_BARS`` rows.
    No Streamlit calls — safe outside a Streamlit session.

    Returns
    -------
    tuple[int, list[str]]
        ``(raw_score, active_keys)`` where ``active_keys`` is the list of
        strategy keys that returned ``position == 1`` on the last bar.
    """
    if df.empty or len(df) < _MIN_BARS:
        return 0, []

    raw_score: int = 0
    active_keys: list[str] = []
    for key in strategy_filter:
        fn = _STRATEGY_MAP.get(key)
        if fn is None:
            logger.warning("Unknown strategy key %r — skipping.", key)
            continue
        try:
            enriched = fn(df.copy())
            if "position" in enriched.columns:
                last_val = enriched["position"].iloc[-1]
                if pd.notna(last_val) and int(last_val) == 1:
                    raw_score += 1
                    active_keys.append(key)
        except Exception as exc:
            logger.warning("Strategy '%s' failed: %s", key, exc)
    return raw_score, active_keys


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def check_and_execute(
    portfolio: Portfolio,
    bot_config: BotConfig,
    ohlcv_cache: dict[tuple[str, str, str], pd.DataFrame] | None = None,
) -> list[dict[str, Any]]:
    """
    Evaluate signals for every asset and execute trades for one bot cycle.

    Execution order
    ---------------
    1. Fetch current prices for all open positions.
    2. Run stop-loss / take-profit checks → close triggered positions first.
    3. For each asset, compute a filtered confluence score.
    4. Apply sell rule (score ≤ sell_threshold) then buy rule (score ≥ min_confluence).

    Parameters
    ----------
    portfolio:
        Bound ``Portfolio`` instance (must match ``bot_config``).
    bot_config:
        Full bot configuration — strategy filter, timeframe, thresholds, etc.
    ohlcv_cache:
        Optional shared cache for OHLCV DataFrames keyed by
        ``(source, symbol, timeframe)``.  When provided, a cache hit skips the
        API call entirely; a miss fetches and stores the result.  Pass the same
        dict to every bot in a cycle to avoid redundant fetches across bots that
        share a timeframe.  ``None`` disables caching (original behaviour).

    Returns
    -------
    list[dict]
        One dict per executed action.  Common keys: ``action``, ``label``,
        ``symbol``, ``source``, ``price``, ``score``, ``reason``.
    """
    actions: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 1. Fetch prices for all currently open positions
    # ------------------------------------------------------------------
    open_positions = portfolio.get_open_positions()
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for pos in open_positions:
        open_by_symbol.setdefault(pos["symbol"], []).append(pos)

    position_prices: dict[str, float] = {}
    for symbol, positions in open_by_symbol.items():
        price = _fetch_price(positions[0]["source"], symbol)
        if not math.isnan(price):
            position_prices[symbol] = price

    # ------------------------------------------------------------------
    # 2. Stop-loss / take-profit exits (before scanning for new signals)
    # ------------------------------------------------------------------
    sl_tp_exits = portfolio.check_stop_loss_take_profit(position_prices)
    for exit_info in sl_tp_exits:
        pos_id: int = exit_info["position_id"]
        symbol: str = exit_info["symbol"]
        exit_price: float = exit_info["current_price"]
        reason: str = exit_info["reason"]

        trade = portfolio.sell(pos_id, symbol, exit_price, reason=reason)
        if trade:
            actions.append(
                {
                    "action": "sell",
                    "label": symbol,
                    "symbol": symbol,
                    "source": trade.get("source", ""),
                    "price": exit_price,
                    "score": None,
                    "reason": reason,
                    **trade,
                }
            )
            # Remove from open_by_symbol so the asset is skipped below.
            open_by_symbol.pop(symbol, None)

    # Refresh open positions after SL/TP exits.
    open_positions_fresh = portfolio.get_open_positions()
    open_by_symbol_fresh: dict[str, list[dict[str, Any]]] = {}
    for pos in open_positions_fresh:
        open_by_symbol_fresh.setdefault(pos["symbol"], []).append(pos)

    # ------------------------------------------------------------------
    # 3 & 4. Signal scan — sell weak, buy strong
    # ------------------------------------------------------------------
    assets = get_assets_for_bot(bot_config)
    for label, asset_cfg in assets.items():
        source: str = asset_cfg["source"]
        symbol = asset_cfg["id"]

        logger.debug("[%s] Evaluating %s (%s)…", bot_config.bot_id, label, symbol)

        if ohlcv_cache is not None:
            cache_key: tuple[str, str, str] = (source, symbol, bot_config.timeframe)
            if cache_key in ohlcv_cache:
                df = ohlcv_cache[cache_key]
                logger.debug("[%s] %s OHLCV cache hit.", bot_config.bot_id, label)
            else:
                df = _fetch_ohlcv(source, symbol, bot_config.timeframe)
                ohlcv_cache[cache_key] = df
        else:
            df = _fetch_ohlcv(source, symbol, bot_config.timeframe)
        score, active_strategies = _compute_confluence(df, bot_config.strategy_filter)
        if bot_config.use_sentiment:
            # Sentiment integration placeholder — wire up data.sentiment when ready.
            sentiment_score: int = 0
        else:
            sentiment_score = 0
        _ = sentiment_score  # available for future confluence adjustment
        logger.debug("[%s] %s score=%d strategies=%s", bot_config.bot_id, label, score, active_strategies)

        # Reuse already-fetched price when available; otherwise fetch now.
        current_price = position_prices.get(symbol) or _fetch_price(source, symbol)
        if math.isnan(current_price):
            logger.warning("[%s] %s: price unavailable, skipping.", bot_config.bot_id, label)
            continue

        # --- Sell on weak signal ------------------------------------------
        if score <= bot_config.sell_threshold and symbol in open_by_symbol_fresh:
            for pos in open_by_symbol_fresh[symbol]:
                trade = portfolio.sell(pos["id"], symbol, current_price, reason="signal")
                if trade:
                    actions.append(
                        {
                            "action": "sell",
                            "label": label,
                            "symbol": symbol,
                            "source": source,
                            "price": current_price,
                            "score": score,
                            "reason": "signal",
                            **trade,
                        }
                    )

        # --- Buy on strong signal -----------------------------------------
        elif score >= bot_config.min_confluence and symbol not in open_by_symbol_fresh:
            if bot_config.use_trend_filter:
                from trd_auto.data.filters import is_uptrend_sma200  # noqa: PLC0415
                if not is_uptrend_sma200(df):
                    logger.debug("[%s] %s filtered out — not in SMA200 uptrend.", bot_config.bot_id, label)
                    continue
            allocation = portfolio.cash * bot_config.max_position_pct
            if allocation <= 0 or current_price <= 0:
                continue
            shares = allocation / current_price
            strategy_label: str = ",".join(active_strategies) if active_strategies else bot_config.bot_id
            success = portfolio.buy(
                symbol, source, current_price, shares, strategy=strategy_label
            )
            if success:
                actions.append(
                    {
                        "action": "buy",
                        "label": label,
                        "symbol": symbol,
                        "source": source,
                        "price": current_price,
                        "score": score,
                        "reason": "signal",
                        "shares": shares,
                        "allocation": allocation,
                    }
                )

    return actions

