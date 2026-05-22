"""
data.connectors.coingecko
==========================
Data connector for cryptocurrency data powered by the ``pycoingecko``
library, which wraps the public CoinGecko REST API v3.

Provider
--------
CoinGecko — free tier, no API key required for public endpoints.
Rate limit: ~30 calls/minute on the free plan.  Each ``get_historical``
call may consume up to two API requests (OHLC + market_chart); plan
accordingly.

OHLC strategy
-------------
The CoinGecko free tier exposes two relevant endpoints:

``/coins/{id}/ohlc``
    Returns proper OHLC bars.  Supported ``days`` values: 1, 7, 14, 30,
    90, 180, 365.  **Does not include volume.**

    Auto-selected granularity:
        1 day   → 30-minute bars
        7–30    →  4-hour bars
        90+     →  4-day bars

``/coins/{id}/market_chart``
    Returns price snapshots, market-cap, and 24 h rolling volume.
    **Does not return proper OHLC.**

    Auto-selected granularity (free tier):
        1 day   →  5-minute snapshots
        2–90    →  hourly snapshots
        >90     →  daily snapshots

Resolution
~~~~~~~~~~
``get_historical`` always fetches ``market_chart`` (prices + volumes).
It then *attempts* the ``ohlc`` endpoint.  If OHLC succeeds, volume is
aligned to each bar via ``pd.merge_asof`` on the nearest timestamp.
If OHLC fails (HTTP 429, network error, empty response), OHLC values are
derived from the price snapshots (open = high = low = close = price at
each snapshot) and volume is taken directly from the same response.

All CoinGecko timestamps are Unix milliseconds in UTC.

Planned extensions (do not implement yet)
-----------------------------------------
- Pagination for very long historical ranges.
- On-chain metrics (TVL, active addresses) from CoinGecko Pro endpoints.
"""

import logging
from typing import Any

import pandas as pd
from pycoingecko import CoinGeckoAPI

from config.assets import TIME_RANGES
from data.base import DataSourceBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_OHLCV_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

# Lookup: period label (e.g. "1M") -> number of days passed to CoinGecko.
# Built once at import time from the single source of truth in config.assets.
_PERIOD_TO_DAYS: dict[str, int] = {tr["label"]: tr["days"] for tr in TIME_RANGES}

_DEFAULT_DAYS: int = 30

# Sentinel empty structures returned on failure.
_EMPTY_OHLCV: pd.DataFrame = pd.DataFrame(columns=_OHLCV_COLUMNS)
_EMPTY_QUOTE: dict[str, Any] = {
    "price":      float("nan"),
    "change_pct": float("nan"),
    "volume":     float("nan"),
    "market_cap": float("nan"),
    "source":     "coingecko",
}

# ---------------------------------------------------------------------------
# Private helpers (module-level, pure functions)
# ---------------------------------------------------------------------------


def _ms_to_utc(ms_series: pd.Series) -> pd.Series:
    """Convert a Series of Unix millisecond integers to UTC-aware datetimes."""
    return pd.to_datetime(ms_series, unit="ms", utc=True)


def _build_from_ohlc_and_volumes(
    ohlc_raw: list[list[float]],
    volumes_raw: list[list[float]],
) -> pd.DataFrame:
    """
    Build the canonical OHLCV DataFrame from a CoinGecko OHLC response
    and the ``total_volumes`` list from a ``market_chart`` response.

    Volume is aligned to the nearest OHLC bar timestamp using
    ``pd.merge_asof`` so that bar-level granularity is preserved even
    when the two endpoints return data at different frequencies.

    Parameters
    ----------
    ohlc_raw : list[list[float]]
        Raw rows from the OHLC endpoint.
        Each row: ``[timestamp_ms, open, high, low, close]``.
    volumes_raw : list[list[float]]
        Raw rows from ``market_chart["total_volumes"]``.
        Each row: ``[timestamp_ms, volume]``.

    Returns
    -------
    pd.DataFrame
        Canonical OHLCV DataFrame (see module docstring for schema).
    """
    ohlc_df = pd.DataFrame(ohlc_raw, columns=["ts_ms", "open", "high", "low", "close"])
    ohlc_df["timestamp"] = _ms_to_utc(ohlc_df["ts_ms"])

    vol_df = pd.DataFrame(volumes_raw, columns=["ts_ms", "volume"])
    vol_df["timestamp"] = _ms_to_utc(vol_df["ts_ms"])

    ohlc_df = ohlc_df.sort_values("timestamp")
    vol_df = vol_df.sort_values("timestamp")

    # Align the nearest available volume snapshot to each OHLC bar.
    merged = pd.merge_asof(
        ohlc_df[["timestamp", "open", "high", "low", "close"]],
        vol_df[["timestamp", "volume"]],
        on="timestamp",
        direction="nearest",
    )

    for col in ["open", "high", "low", "close", "volume"]:
        merged[col] = merged[col].astype("float64")

    return merged[_OHLCV_COLUMNS].reset_index(drop=True)


def _build_from_price_snapshots(
    prices_raw: list[list[float]],
    volumes_raw: list[list[float]],
) -> pd.DataFrame:
    """
    Derive OHLCV from CoinGecko ``market_chart`` price snapshots when the
    dedicated OHLC endpoint is unavailable.

    Since each snapshot represents a single price observation rather than
    a full bar, open / high / low / close are all set to that price.
    Volume is aligned from the ``total_volumes`` list via nearest-timestamp
    merge.

    Parameters
    ----------
    prices_raw : list[list[float]]
        Raw rows from ``market_chart["prices"]``.
        Each row: ``[timestamp_ms, price]``.
    volumes_raw : list[list[float]]
        Raw rows from ``market_chart["total_volumes"]``.
        Each row: ``[timestamp_ms, volume]``.

    Returns
    -------
    pd.DataFrame
        Canonical OHLCV DataFrame (open = high = low = close = price).
    """
    price_df = pd.DataFrame(prices_raw, columns=["ts_ms", "close"])
    price_df["timestamp"] = _ms_to_utc(price_df["ts_ms"])
    # Derive flat OHLC from the single price snapshot.
    price_df["open"]  = price_df["close"]
    price_df["high"]  = price_df["close"]
    price_df["low"]   = price_df["close"]

    vol_df = pd.DataFrame(volumes_raw, columns=["ts_ms", "volume"])
    vol_df["timestamp"] = _ms_to_utc(vol_df["ts_ms"])

    price_df = price_df.sort_values("timestamp")
    vol_df   = vol_df.sort_values("timestamp")

    merged = pd.merge_asof(
        price_df[["timestamp", "open", "high", "low", "close"]],
        vol_df[["timestamp", "volume"]],
        on="timestamp",
        direction="nearest",
    )

    for col in ["open", "high", "low", "close", "volume"]:
        merged[col] = merged[col].astype("float64")

    return merged[_OHLCV_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------


class CoinGeckoConnector(DataSourceBase):
    """
    Fetches cryptocurrency market data from CoinGecko via ``pycoingecko``.

    No API key is required for the public free tier.  A single
    ``CoinGeckoAPI`` client is created at construction time and reused
    across all calls.
    """

    def __init__(self) -> None:
        self._cg: CoinGeckoAPI = CoinGeckoAPI()

    # ------------------------------------------------------------------
    # DataSourceBase interface
    # ------------------------------------------------------------------

    def get_historical(self, symbol: str, period: str) -> pd.DataFrame:
        """
        Fetch OHLCV history for a cryptocurrency.

        Parameters
        ----------
        symbol : str
            CoinGecko coin ID (e.g. ``"bitcoin"``, ``"ethereum"``).
            Must match the ``id`` field returned by ``/coins/list``.
        period : str
            Canonical period label from ``config.assets.TIME_RANGES``
            (e.g. ``"1D"``, ``"1W"``, ``"1M"``, ``"3M"``, ``"1Y"``).
            Mapped to a ``days`` integer via ``_PERIOD_TO_DAYS``.

        Returns
        -------
        pd.DataFrame
            Canonical OHLCV DataFrame with columns:
            ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.

            - ``timestamp`` is a regular column of UTC-aware
              ``datetime64[ns, UTC]`` values (not the index).
            - All price and volume columns are ``float64``.
            - When the OHLC endpoint is unavailable, OHLC values are
              derived from price snapshots (open = high = low = close).
            - Returns an empty DataFrame with correct columns on failure.
        """
        days: int = _PERIOD_TO_DAYS.get(period, _DEFAULT_DAYS)

        try:
            # Always fetch market_chart: provides prices + volumes in one call.
            chart: dict = self._cg.get_coin_market_chart_by_id(
                id=symbol,
                vs_currency="usd",
                days=days,
            )
            prices_raw:  list = chart.get("prices", [])
            volumes_raw: list = chart.get("total_volumes", [])

            if not prices_raw:
                return _EMPTY_OHLCV.copy()

            # Attempt the dedicated OHLC endpoint for proper candle data.
            try:
                ohlc_raw: list = self._cg.get_coin_ohlc_by_id(
                    id=symbol,
                    vs_currency="usd",
                    days=days,
                )
                if ohlc_raw:
                    return _build_from_ohlc_and_volumes(ohlc_raw, volumes_raw)
            except Exception as ohlc_exc:
                logger.warning(
                    "CoinGeckoConnector: OHLC endpoint unavailable for %s/%s "
                    "(falling back to price snapshots): %s",
                    symbol, period, ohlc_exc,
                )

            # Fallback: derive OHLC from price snapshots.
            return _build_from_price_snapshots(prices_raw, volumes_raw)

        except Exception as exc:
            logger.warning(
                "CoinGeckoConnector.get_historical(%s, %s): %s", symbol, period, exc
            )
            return _EMPTY_OHLCV.copy()

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """
        Fetch the latest quote snapshot for a cryptocurrency.

        Uses the ``/simple/price`` endpoint which is the lightest available
        call on the free tier (single request, minimal payload).

        Parameters
        ----------
        symbol : str
            CoinGecko coin ID (e.g. ``"bitcoin"``).

        Returns
        -------
        dict
            Always contains exactly these keys:

            ============  =======  ==========================================
            Key           type     Description
            ============  =======  ==========================================
            price         float    Current USD price.
            change_pct    float    24 h percentage change
                                   (e.g. ``-2.31`` means ``-2.31 %``).
            volume        float    24 h traded volume in USD.
            market_cap    float    Current market capitalisation in USD.
            source        str      Always ``"coingecko"``.
            ============  =======  ==========================================

            Any unavailable value is set to ``float("nan")``.  Returns a
            copy of ``_EMPTY_QUOTE`` on any retrieval failure.
        """
        try:
            data: dict = self._cg.get_price(
                ids=symbol,
                vs_currencies="usd",
                include_market_cap="true",
                include_24hr_vol="true",
                include_24hr_change="true",
            )

            if symbol not in data:
                logger.warning("CoinGeckoConnector.get_quote: symbol '%s' not found in response.", symbol)
                return _EMPTY_QUOTE.copy()

            coin: dict = data[symbol]

            def _float(key: str) -> float:
                """Return coin[key] as float, or nan if absent/None."""
                val = coin.get(key)
                return float(val) if val is not None else float("nan")

            return {
                "price":      _float("usd"),
                "change_pct": _float("usd_24h_change"),
                "volume":     _float("usd_24h_vol"),
                "market_cap": _float("usd_market_cap"),
                "source":     "coingecko",
            }

        except Exception as exc:
            logger.warning("CoinGeckoConnector.get_quote(%s): %s", symbol, exc)
            return _EMPTY_QUOTE.copy()
