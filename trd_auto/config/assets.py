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
# Equity assets organised by sector  (yfinance compatible tickers)
# Each leaf entry carries the full connector config so it can be used
# directly in ASSETS_BY_SECTOR without further transformation.
# ---------------------------------------------------------------------------
STOCK_ASSETS_BY_SECTOR: dict[str, dict[str, dict]] = {
    "Technology": {
        "Apple (AAPL)":       {"source": "yahoo", "id": "AAPL"},
        "Microsoft (MSFT)":   {"source": "yahoo", "id": "MSFT"},
        "Nvidia (NVDA)":      {"source": "yahoo", "id": "NVDA"},
        "Alphabet (GOOGL)":   {"source": "yahoo", "id": "GOOGL"},
        "Meta (META)":        {"source": "yahoo", "id": "META"},
        "AMD (AMD)":          {"source": "yahoo", "id": "AMD"},
        "Salesforce (CRM)":   {"source": "yahoo", "id": "CRM"},
        "Adobe (ADBE)":       {"source": "yahoo", "id": "ADBE"},
    },
    "Healthcare": {
        "Johnson & Johnson (JNJ)": {"source": "yahoo", "id": "JNJ"},
        "UnitedHealth (UNH)":      {"source": "yahoo", "id": "UNH"},
        "Pfizer (PFE)":            {"source": "yahoo", "id": "PFE"},
        "AbbVie (ABBV)":           {"source": "yahoo", "id": "ABBV"},
        "Merck (MRK)":             {"source": "yahoo", "id": "MRK"},
        "Thermo Fisher (TMO)":     {"source": "yahoo", "id": "TMO"},
        "Danaher (DHR)":           {"source": "yahoo", "id": "DHR"},
        "Eli Lilly (LLY)":         {"source": "yahoo", "id": "LLY"},
    },
    "Finance": {
        "JPMorgan (JPM)":          {"source": "yahoo", "id": "JPM"},
        "Bank of America (BAC)":   {"source": "yahoo", "id": "BAC"},
        "Goldman Sachs (GS)":      {"source": "yahoo", "id": "GS"},
        "Morgan Stanley (MS)":     {"source": "yahoo", "id": "MS"},
        "BlackRock (BLK)":         {"source": "yahoo", "id": "BLK"},
        "Visa (V)":                {"source": "yahoo", "id": "V"},
        "Mastercard (MA)":         {"source": "yahoo", "id": "MA"},
        "American Express (AXP)":  {"source": "yahoo", "id": "AXP"},
    },
    "Energy": {
        "ExxonMobil (XOM)":         {"source": "yahoo", "id": "XOM"},
        "Chevron (CVX)":            {"source": "yahoo", "id": "CVX"},
        "ConocoPhillips (COP)":     {"source": "yahoo", "id": "COP"},
        "SLB (SLB)":                {"source": "yahoo", "id": "SLB"},
        "EOG Resources (EOG)":      {"source": "yahoo", "id": "EOG"},
        "Phillips 66 (PSX)":        {"source": "yahoo", "id": "PSX"},
        "Marathon Petroleum (MPC)": {"source": "yahoo", "id": "MPC"},
        "Occidental (OXY)":         {"source": "yahoo", "id": "OXY"},
    },
    "Consumer": {
        "Amazon (AMZN)":    {"source": "yahoo", "id": "AMZN"},
        "Tesla (TSLA)":     {"source": "yahoo", "id": "TSLA"},
        "Home Depot (HD)":  {"source": "yahoo", "id": "HD"},
        "McDonald's (MCD)": {"source": "yahoo", "id": "MCD"},
        "Nike (NKE)":       {"source": "yahoo", "id": "NKE"},
        "Starbucks (SBUX)": {"source": "yahoo", "id": "SBUX"},
        "Target (TGT)":     {"source": "yahoo", "id": "TGT"},
        "Lowe's (LOW)":     {"source": "yahoo", "id": "LOW"},
    },
    "Industrials": {
        "Caterpillar (CAT)":      {"source": "yahoo", "id": "CAT"},
        "Boeing (BA)":            {"source": "yahoo", "id": "BA"},
        "Honeywell (HON)":        {"source": "yahoo", "id": "HON"},
        "UPS (UPS)":              {"source": "yahoo", "id": "UPS"},
        "Raytheon (RTX)":         {"source": "yahoo", "id": "RTX"},
        "John Deere (DE)":        {"source": "yahoo", "id": "DE"},
        "Lockheed Martin (LMT)":  {"source": "yahoo", "id": "LMT"},
        "GE Aerospace (GE)":      {"source": "yahoo", "id": "GE"},
    },
}

# Flat view for backward compatibility — consumed by ALL_ASSETS and the bots.
STOCK_ASSETS: dict[str, dict] = {
    label: cfg
    for sector in STOCK_ASSETS_BY_SECTOR.values()
    for label, cfg in sector.items()
}

# ---------------------------------------------------------------------------
# Crypto assets  (CoinGecko coin IDs)
# ---------------------------------------------------------------------------
CRYPTO_ASSETS: dict[str, dict] = {
    "Bitcoin (BTC)":    {"source": "coingecko", "id": "bitcoin"},
    "Ethereum (ETH)":   {"source": "coingecko", "id": "ethereum"},
    "Solana (SOL)":     {"source": "coingecko", "id": "solana"},
    "BNB (BNB)":        {"source": "coingecko", "id": "binancecoin"},
    "XRP (XRP)":        {"source": "coingecko", "id": "ripple"},
    "Cardano (ADA)":    {"source": "coingecko", "id": "cardano"},
    "Avalanche (AVAX)": {"source": "coingecko", "id": "avalanche-2"},
    "Chainlink (LINK)": {"source": "coingecko", "id": "chainlink"},
}

# ---------------------------------------------------------------------------
# Unified asset registry consumed by the UI and connector factory.
# Both STOCK_ASSETS and CRYPTO_ASSETS already carry the full connector config,
# so ALL_ASSETS is a simple merge.
# ---------------------------------------------------------------------------
ALL_ASSETS: dict[str, dict[str, Any]] = {
    **STOCK_ASSETS,
    **CRYPTO_ASSETS,
}

# ---------------------------------------------------------------------------
# Sector helpers — used by the sidebar sector filter.
# ---------------------------------------------------------------------------
STOCK_SECTORS: list[str] = list(STOCK_ASSETS_BY_SECTOR.keys())

ASSETS_BY_SECTOR: dict[str, dict[str, dict]] = {
    **STOCK_ASSETS_BY_SECTOR,
    "Crypto": CRYPTO_ASSETS,
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
    {"label": "1D",  "period": "1d",   "interval": "5m",  "days": 1},
    {"label": "1H",  "period": "730d", "interval": "1h",  "days": 730},
    {"label": "4H",  "period": "60d",  "interval": "1h",  "days": 60},
    {"label": "1W",  "period": "7d",   "interval": "1h",  "days": 7},
    {"label": "1M",  "period": "1mo", "interval": "1d",  "days": 30},
    {"label": "3M",  "period": "3mo", "interval": "1d",  "days": 90},
    {"label": "1Y",  "period": "1y",  "interval": "1wk", "days": 365},
]

# Default selections shown on first load
DEFAULT_ASSET_LABEL: str = "Bitcoin (BTC)"
DEFAULT_TIME_RANGE_LABEL: str = "1M"
