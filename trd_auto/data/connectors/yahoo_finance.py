"""
data.connectors.yahoo_finance
==============================
Data connector for equity and ETF data powered by the ``yfinance`` library.

Provider
--------
Yahoo Finance — free, no API key required.
Rate limits are soft; avoid tight polling loops.

Class
-----
YahooFinanceConnector
    Implements ``DataSourceBase.get_historical`` and ``get_quote``.

Interval derivation
-------------------
The connector accepts the canonical period *label* defined in
``config.assets.TIME_RANGES`` (e.g. ``"1D"``, ``"1W"``, ``"1M"``).
Both the yfinance ``period`` string and the ``interval`` string are
derived automatically from ``TIME_RANGES`` at module load time via
``_PERIOD_MAP`` — callers never pass an interval explicitly.

Error handling
--------------
All network and parsing errors are caught silently.  On any failure
``get_historical`` returns an empty DataFrame with the correct columns
and ``get_quote`` returns an empty-valued dict, both matching the
canonical schema.  This lets the UI layer render a "no data" state
instead of crashing.

Planned extensions (do not implement yet)
-----------------------------------------
- Batch ticker fetch via ``yfinance.download`` for portfolio mode.
- Options chain data retrieval.
"""

import logging
from typing import Any

import pandas as pd
import yfinance as yf

from config.assets import TIME_RANGES
from data.base import DataSourceBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Canonical OHLCV column order returned by this connector.
_OHLCV_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

# Lookup: period label (e.g. "1M") -> (yfinance period str, yfinance interval str)
# Built once at import time from the single source of truth in config.assets.
_PERIOD_MAP: dict[str, tuple[str, str]] = {
    tr["label"]: (tr["period"], tr["interval"])
    for tr in TIME_RANGES
}

# Fallback used when an unrecognised period label is supplied.
_DEFAULT_PERIOD: tuple[str, str] = ("1mo", "1d")

# Sentinel empty structures returned on failure.
_EMPTY_OHLCV: pd.DataFrame = pd.DataFrame(columns=_OHLCV_COLUMNS)
_EMPTY_QUOTE: dict[str, Any] = {
    "price": float("nan"),
    "change_pct": float("nan"),
    "volume": float("nan"),
    "market_cap": float("nan"),
    "source": "yahoo",
}


class YahooFinanceConnector(DataSourceBase):
    """
    Fetches equity and ETF market data from Yahoo Finance via ``yfinance``.

    No API key or configuration is required.  The connector is stateless;
    a single instance can be reused across multiple calls.
    """

    # ------------------------------------------------------------------
    # DataSourceBase interface
    # ------------------------------------------------------------------

    def get_historical(self, symbol: str, period: str) -> pd.DataFrame:
        """
        Fetch OHLCV history for an equity or ETF ticker.

        Parameters
        ----------
        symbol : str
            Yahoo Finance ticker symbol (e.g. ``"AAPL"``, ``"SPY"``).
        period : str
            Canonical period label from ``config.assets.TIME_RANGES``
            (e.g. ``"1D"``, ``"1W"``, ``"1M"``, ``"3M"``, ``"1Y"``).
            The yfinance period and interval strings are derived
            internally via ``_PERIOD_MAP``.

        Returns
        -------
        pd.DataFrame
            Canonical OHLCV DataFrame with columns:
            ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.

            - ``timestamp`` is a regular column of UTC-aware
              ``datetime64[ns, UTC]`` values (not the index).
            - All price and volume columns are ``float64``.
            - Returns an empty DataFrame with correct columns on failure.
        """
        try:
            yf_period, yf_interval = _PERIOD_MAP.get(period, _DEFAULT_PERIOD)

            raw: pd.DataFrame = yf.Ticker(symbol).history(
                period=yf_period,
                interval=yf_interval,
                auto_adjust=True,
                actions=False,
            )

            if raw.empty:
                return _EMPTY_OHLCV.copy()

            # Select and rename to canonical column names.
            df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.columns = ["open", "high", "low", "close", "volume"]

            # Normalise index timezone to UTC, then promote to a plain column.
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")

            df = df.reset_index()
            # The index column is named "Date" (daily) or "Datetime" (intraday).
            index_col: str = "Datetime" if "Datetime" in df.columns else "Date"
            df = df.rename(columns={index_col: "timestamp"})

            # Enforce canonical dtypes.
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype("float64")

            return df[_OHLCV_COLUMNS].reset_index(drop=True)

        except Exception as exc:
            logger.warning("YahooFinanceConnector.get_historical(%s, %s): %s", symbol, period, exc)
            return _EMPTY_OHLCV.copy()

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """
        Fetch the latest quote snapshot for an equity or ETF ticker.

        Uses ``yfinance.Ticker.info`` which returns a rich metadata dict.
        Only the five keys required by the canonical schema are extracted.

        Parameters
        ----------
        symbol : str
            Yahoo Finance ticker symbol (e.g. ``"AAPL"``).

        Returns
        -------
        dict
            Always contains exactly these keys:

            ============  =======  ==========================================
            Key           type     Description
            ============  =======  ==========================================
            price         float    Latest market price (``currentPrice`` or
                                   ``regularMarketPrice``).
            change_pct    float    Session % change
                                   (``regularMarketChangePercent``).
                                   Value is already in percent units
                                   (e.g. ``-1.23`` means ``-1.23 %``).
            volume        float    Session volume
                                   (``regularMarketVolume``).
            market_cap    float    Market capitalisation (``marketCap``).
            source        str      Always ``"yahoo"``.
            ============  =======  ==========================================

            Any key whose value is unavailable from the API is set to
            ``float("nan")``.  Returns a copy of ``_EMPTY_QUOTE`` on any
            retrieval failure.
        """
        try:
            info: dict[str, Any] = yf.Ticker(symbol).info

            def _float(key: str, *fallbacks: str) -> float:
                """Extract the first non-None value from info as float."""
                for k in (key, *fallbacks):
                    val = info.get(k)
                    if val is not None:
                        return float(val)
                return float("nan")

            return {
                "price":       _float("currentPrice", "regularMarketPrice"),
                "change_pct":  _float("regularMarketChangePercent"),
                "volume":      _float("regularMarketVolume", "volume"),
                "market_cap":  _float("marketCap"),
                "source":      "yahoo",
            }

        except Exception as exc:
            logger.warning("YahooFinanceConnector.get_quote(%s): %s", symbol, exc)
            return _EMPTY_QUOTE.copy()
