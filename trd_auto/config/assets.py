"""
config.assets
=============
Single source of truth for all tradeable asset definitions and
application-level constants.

All asset lists, time-range options, and display labels live here.
Adding a new asset or time range requires only editing this file —
no other module should hardcode such values.

Structure
---------
STOCK_ASSETS   : dict[str, str]
    Mapping of display label -> ticker symbol for equities.
    Ticker format must be compatible with yfinance.

CRYPTO_ASSETS  : dict[str, str]
    Mapping of display label -> CoinGecko coin ID for crypto.
    ID must match the ``id`` field returned by /coins/list.

ALL_ASSETS     : dict[str, dict]
    Merged view consumed by the UI layer.  Each entry carries the
    ticker/id plus the data-source key so the right connector is
    selected automatically.

TIME_RANGES    : list[dict]
    Ordered list of selectable time-range options exposed in the UI.
    Each entry contains a human-readable label and the parameters
    expected by the data connectors (period, interval).

Planned extensions (do not add logic yet)
-----------------------------------------
- WATCHLIST_GROUPS  : named groups for portfolio tracking
- ALERT_THRESHOLDS  : per-asset price / % change alert levels
- INDICATOR_DEFAULTS: default parameters for RSI, MACD, Bollinger Bands
"""

from typing import Any

# ---------------------------------------------------------------------------
# Equity assets  (yfinance compatible tickers)
# ---------------------------------------------------------------------------
STOCK_ASSETS: dict[str, str] = {
    "Apple (AAPL)": "AAPL",
    "Microsoft (MSFT)": "MSFT",
    "NVIDIA (NVDA)": "NVDA",
    "Tesla (TSLA)": "TSLA",
    "Amazon (AMZN)": "AMZN",
    "Alphabet (GOOGL)": "GOOGL",
    "Meta (META)": "META",
    "S&P 500 ETF (SPY)": "SPY",
}

# ---------------------------------------------------------------------------
# Crypto assets  (CoinGecko coin IDs)
# ---------------------------------------------------------------------------
CRYPTO_ASSETS: dict[str, str] = {
    "Bitcoin (BTC)": "bitcoin",
    "Ethereum (ETH)": "ethereum",
    "Solana (SOL)": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
}

# ---------------------------------------------------------------------------
# Unified asset registry consumed by the UI and connector factory.
# Each entry stores:
#   "source"  -> connector key  ("yahoo" | "coingecko")
#   "id"      -> ticker or coin ID passed to the connector
# ---------------------------------------------------------------------------
ALL_ASSETS: dict[str, dict[str, Any]] = {
    **{
        label: {"source": "yahoo", "id": ticker}
        for label, ticker in STOCK_ASSETS.items()
    },
    **{
        label: {"source": "coingecko", "id": coin_id}
        for label, coin_id in CRYPTO_ASSETS.items()
    },
}

# ---------------------------------------------------------------------------
# Time-range options
# Each entry carries:
#   "label"    -> shown in the UI selector
#   "period"   -> yfinance period string  (e.g. "1d", "1mo")
#   "interval" -> yfinance interval string (e.g. "5m", "1d")
#   "days"     -> number of calendar days used by CoinGecko connector
# ---------------------------------------------------------------------------
TIME_RANGES: list[dict[str, Any]] = [
    {"label": "1D",  "period": "1d",  "interval": "5m",  "days": 1},
    {"label": "1W",  "period": "7d",  "interval": "1h",  "days": 7},
    {"label": "1M",  "period": "1mo", "interval": "1d",  "days": 30},
    {"label": "3M",  "period": "3mo", "interval": "1d",  "days": 90},
    {"label": "1Y",  "period": "1y",  "interval": "1wk", "days": 365},
]

# Default selections shown on first load
DEFAULT_ASSET_LABEL: str = "Bitcoin (BTC)"
DEFAULT_TIME_RANGE_LABEL: str = "1M"
