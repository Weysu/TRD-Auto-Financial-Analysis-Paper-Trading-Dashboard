"""
paper_trader.executor
=====================
Signal executor.  The single public function ``check_and_execute`` scans
every asset defined in ``trd_auto/config/assets.ALL_ASSETS``, evaluates a
confluence score, and triggers buy / sell actions on the supplied
``Portfolio`` instance.

Buy rule  : confluence score >= 3, no open position on the asset
            → allocate up to 20 % of current cash.
Sell rule : confluence score <= 1, open position exists on the asset
            → sell the entire position at the current market price.

Sentiment is set to neutral (``overall_score = 0``) because the executor
runs outside the Streamlit session context and cannot call the live
sentiment API without blocking the schedule loop.

The confluence calculation is a local reimplementation that avoids the
``st.warning`` call inside ``data.signal_engine`` so the engine stays
Streamlit-free.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — must happen before any trd_auto or paper_trader imports.
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

from config.assets import ALL_ASSETS  # noqa: E402
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
from paper_trader.portfolio import Portfolio  # noqa: E402
from paper_trader import db as _db  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONNECTOR_REGISTRY: dict[str, type[DataSourceBase]] = {
    "yahoo": YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}

# Period used when fetching OHLCV for signal computation.
# 3M (90 daily bars) is sufficient for MA-50, MACD(26), and Bollinger(20).
_SIGNAL_PERIOD: str = "3M"

# Maximum share of current cash allocated to a single buy order.
_MAX_ALLOCATION: float = 0.20

_STRATEGIES: list[tuple[str, Any]] = [
    ("MA Crossover", run_ma_crossover),
    ("RSI", run_rsi_strategy),
    ("Bollinger Bands", run_bollinger_bands),
    ("MACD Crossover", run_macd_crossover),
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fetch_ohlcv(source: str, symbol: str) -> pd.DataFrame:
    """Fetch OHLCV history using the appropriate connector."""
    try:
        connector: DataSourceBase = _CONNECTOR_REGISTRY[source]()
        return connector.get_historical(symbol, _SIGNAL_PERIOD)
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


def _compute_confluence(df: pd.DataFrame) -> int:
    """
    Compute a multi-strategy confluence score without Streamlit dependencies.

    Runs all four built-in strategies with default parameters.  Each strategy
    that ends in an active position (``position == 1`` on the last bar)
    contributes +1 to the score.  No sentiment adjustment is applied.

    Returns a score in [0, 4].
    """
    if df.empty or len(df) < 60:
        return 0

    raw_score: int = 0
    for name, fn in _STRATEGIES:
        try:
            enriched = fn(df.copy())
            if "position" in enriched.columns:
                last_val = enriched["position"].iloc[-1]
                if pd.notna(last_val):
                    raw_score += int(last_val)
        except Exception as exc:
            logger.warning("Strategy '%s' failed: %s", name, exc)
    return raw_score


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def check_and_execute(portfolio: Portfolio) -> list[dict[str, Any]]:
    """
    Scan all assets and execute buy / sell actions based on confluence scores.

    Parameters
    ----------
    portfolio:
        Live ``Portfolio`` instance whose cash and positions are updated in
        place (the underlying SQLite state is mutated).

    Returns
    -------
    list[dict]
        One dict per executed action with keys:
        ``action`` (``"buy"`` | ``"sell"``), ``label``, ``symbol``,
        ``source``, ``price``, ``score``, and trade details for sells.
    """
    actions: list[dict[str, Any]] = []

    # Build a lookup: symbol -> list of open position dicts
    all_open: list[dict[str, Any]] = _db.get_open_positions()
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for pos in all_open:
        open_by_symbol.setdefault(pos["symbol"], []).append(pos)

    for label, asset_cfg in ALL_ASSETS.items():
        source: str = asset_cfg["source"]
        symbol: str = asset_cfg["id"]

        logger.debug("Evaluating %s (%s)…", label, symbol)

        # --- Fetch data and compute score -----------------------------------
        df = _fetch_ohlcv(source, symbol)
        score = _compute_confluence(df)
        logger.debug("%s confluence score = %d", label, score)

        # --- Fetch current market price for order sizing / fills ------------
        current_price = _fetch_price(source, symbol)
        if current_price != current_price:  # NaN check without math.isnan
            logger.warning("%s: could not fetch price, skipping.", label)
            continue

        # --- Sell logic -----------------------------------------------------
        if score <= 1 and symbol in open_by_symbol:
            for pos in open_by_symbol[symbol]:
                trade = portfolio.sell(pos["id"], symbol, current_price)
                if trade:
                    actions.append(
                        {
                            "action": "sell",
                            "label": label,
                            "symbol": symbol,
                            "source": source,
                            "price": current_price,
                            "score": score,
                            **trade,
                        }
                    )

        # --- Buy logic ------------------------------------------------------
        elif score >= 3 and symbol not in open_by_symbol:
            allocation = portfolio.cash * _MAX_ALLOCATION
            if allocation <= 0 or current_price <= 0:
                continue
            shares = allocation / current_price
            success = portfolio.buy(symbol, source, current_price, shares, "confluence")
            if success:
                actions.append(
                    {
                        "action": "buy",
                        "label": label,
                        "symbol": symbol,
                        "source": source,
                        "price": current_price,
                        "score": score,
                        "shares": shares,
                        "allocation": allocation,
                    }
                )

    return actions
