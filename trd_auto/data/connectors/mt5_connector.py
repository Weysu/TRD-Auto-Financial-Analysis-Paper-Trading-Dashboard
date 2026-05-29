"""
data.connectors.mt5_connector
==============================
Data connector for market data powered by the ``MetaTrader5`` Python package.

Provider
--------
MetaTrader 5 — requires MT5 terminal to be running and logged in on the
local machine.  No API key is needed; the package communicates with the
MT5 terminal process via its local IPC interface.

Class
-----
MT5Connector
    Implements ``DataSourceBase.get_historical`` and ``get_quote``.

Symbol resolution
-----------------
Internal asset labels (e.g. ``"AAPL"``) are mapped to Pepperstone MT5
symbol names (e.g. ``"AAPL.US"``) via the module-level ``MT5_SYMBOL_MAP``
constant before any MT5 API call.  If a symbol is not in the map it is
passed as-is so that forex pairs (e.g. ``"EURUSD"``) work without an
explicit mapping.

Error handling
--------------
All failures — MT5 not running, symbol not found, copy_rates error —
are caught silently.  ``get_historical`` returns an empty DataFrame with
the correct columns and ``get_quote`` returns a safe-valued dict so the
UI can render a "no data" state instead of crashing.
"""

import logging
from typing import Any

import pandas as pd

from trd_auto.data.base import DataSourceBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — MetaTrader5 is only available when the package is
# installed *and* MT5 is running on the local machine.
# ---------------------------------------------------------------------------
try:
    import MetaTrader5 as mt5  # type: ignore[import]
    _MT5_AVAILABLE: bool = True
except ImportError:
    mt5 = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Canonical OHLCV column order returned by this connector.
_OHLCV_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

# Sentinel empty structures returned on failure.
_EMPTY_OHLCV: pd.DataFrame = pd.DataFrame(columns=_OHLCV_COLUMNS)
_EMPTY_QUOTE: dict[str, Any] = {
    "price":      float("nan"),
    "change_pct": 0.0,
    "volume":     float("nan"),
    "market_cap": 0.0,
    "source":     "mt5",
}

# Pepperstone MT5 symbol names keyed by our internal asset labels.
MT5_SYMBOL_MAP: dict[str, str] = {
    "AAPL":   "AAPL.US",
    "NVDA":   "NVDA.US",
    "AMD":    "AMD.US",
    "GOOGL":  "GOOGL.US",
    "AMZN":   "AMZN.US",
    "META":   "META.US",
    "MSFT":   "MSFT.US",
    "TSLA":   "TSLA.US",
    "JPM":    "JPM.US",
    "BAC":    "BAC.US",
    "GS":     "GS.US",
    "MS":     "MS.US",
    "XOM":    "XOM.US",
    "CVX":    "CVX.US",
    "COP":    "COP.US",
    "OXY":    "OXY.US",
    "MPC":    "MPC.US",
    "CAT":    "CAT.US",
    "MRK":    "MRK.US",
    "ABBV":   "ABBV.US",
    "XAUUSD": "XAUUSD",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
}

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_connected: bool = False  # module-level cache so we don't re-initialize every call


def _ensure_connected() -> bool:
    """
    Ensure the MT5 terminal connection is active.

    Calls ``mt5.initialize()`` if the terminal is not already reachable.
    Returns ``False`` if the MetaTrader5 package is not installed or if the
    MT5 terminal is not running / cannot be contacted.
    """
    global _connected
    if not _MT5_AVAILABLE:
        return False
    if mt5.terminal_info() is not None:
        _connected = True
        return True
    initialized: bool = mt5.initialize()
    if not initialized:
        logger.warning("MT5 initialize() failed: %s", mt5.last_error())
        _connected = False
        return False
    _connected = True
    return True


def _resolve_symbol(symbol: str) -> str:
    """Return the MT5 symbol name for *symbol*, falling back to the raw string."""
    return MT5_SYMBOL_MAP.get(symbol, symbol)


def _get_period_config(period: str) -> tuple[Any, int]:
    """
    Return ``(mt5_timeframe_constant, n_bars)`` for the given period label.

    Timeframe assignment:
        "1D", "1W"  → TIMEFRAME_M15  (intraday / weekly resolution)
        "1H", "1M"  → TIMEFRAME_H1   (hourly bars)
        "3M", "1Y"  → TIMEFRAME_D1   (daily bars)
        "4H"        → TIMEFRAME_H1   (fallback, not in primary spec)
        unknown     → TIMEFRAME_D1, 30 bars

    The n_bars values are sized to cover the full period implied by the
    label; MT5 will return fewer bars when markets are closed.
    """
    mapping: dict[str, tuple[Any, int]] = {
        "1D": (mt5.TIMEFRAME_M15,  96),    # 1 day   × 96 × 15 min
        "1W": (mt5.TIMEFRAME_M15, 672),    # 7 days  × 96 × 15 min
        "1M": (mt5.TIMEFRAME_H1,  720),    # 30 days × 24 h
        "3M": (mt5.TIMEFRAME_D1,   90),    # 90 daily bars
        "1Y": (mt5.TIMEFRAME_D1,  365),    # 365 daily bars
        "1H": (mt5.TIMEFRAME_H1, 17520),   # 730 days × 24 h (long-term hourly)
        "4H": (mt5.TIMEFRAME_H1, 1440),    # 60 days × 24 h
    }
    return mapping.get(period, (mt5.TIMEFRAME_D1, 30))


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------


class MT5Connector(DataSourceBase):
    """
    Fetches market data (OHLCV + quotes) from a locally running MetaTrader 5
    terminal via the ``MetaTrader5`` Python package.

    The connector is stateless; a single instance can be reused across
    multiple calls.  MT5 must be running and logged in on the same machine.
    """

    # ------------------------------------------------------------------
    # DataSourceBase interface
    # ------------------------------------------------------------------

    def get_historical(self, symbol: str, period: str) -> pd.DataFrame:
        """
        Fetch OHLCV history for a symbol from the local MT5 terminal.

        Parameters
        ----------
        symbol : str
            Internal asset label (e.g. ``"AAPL"``) or a raw MT5 symbol
            (e.g. ``"EURUSD"``).  Resolved through ``MT5_SYMBOL_MAP``.
        period : str
            Canonical period label from ``config.assets.TIME_RANGES``
            (``"1D"``, ``"1W"``, ``"1M"``, ``"3M"``, ``"1Y"``, ``"1H"``).

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame with columns: timestamp (UTC datetime64),
            open, high, low, close, volume (all float64).
            Returns an empty DataFrame on any failure.
        """
        if not _ensure_connected():
            logger.debug("MT5 not connected — returning empty DataFrame for %s", symbol)
            return _EMPTY_OHLCV.copy()

        mt5_sym: str = _resolve_symbol(symbol)
        timeframe, n_bars = _get_period_config(period)

        # Activate symbol in the Market Watch so MT5 can serve data for it.
        if not mt5.symbol_select(mt5_sym, True):
            logger.warning("MT5 symbol_select failed for '%s'", mt5_sym)
            return _EMPTY_OHLCV.copy()

        try:
            rates = mt5.copy_rates_from_pos(mt5_sym, timeframe, 0, n_bars)
        except Exception as exc:
            logger.warning("MT5 copy_rates_from_pos error for '%s': %s", mt5_sym, exc)
            return _EMPTY_OHLCV.copy()

        if rates is None or len(rates) == 0:
            logger.debug(
                "MT5 returned no rates for '%s' period='%s': %s",
                mt5_sym, period, mt5.last_error(),
            )
            return _EMPTY_OHLCV.copy()

        try:
            df = pd.DataFrame(rates)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
            # Prefer real_volume when available and non-zero, fall back to tick_volume.
            if "real_volume" in df.columns and df["real_volume"].sum() > 0:
                df = df.rename(columns={"real_volume": "volume"})
            else:
                df = df.rename(columns={"tick_volume": "volume"})
            df = df[_OHLCV_COLUMNS].copy()
            df[["open", "high", "low", "close", "volume"]] = (
                df[["open", "high", "low", "close", "volume"]].astype("float64")
            )
        except Exception as exc:
            logger.warning("MT5 DataFrame construction error for '%s': %s", mt5_sym, exc)
            return _EMPTY_OHLCV.copy()

        return df

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """
        Return the latest price snapshot for *symbol* from MT5.

        Parameters
        ----------
        symbol : str
            Internal asset label or raw MT5 symbol.

        Returns
        -------
        dict
            Keys: ``price``, ``change_pct``, ``volume``,
            ``market_cap`` (always 0.0), ``source`` (``"mt5"``).
            On failure returns safe sentinel values.
        """
        if not _ensure_connected():
            return dict(_EMPTY_QUOTE)

        mt5_sym: str = _resolve_symbol(symbol)
        mt5.symbol_select(mt5_sym, True)

        tick = mt5.symbol_info_tick(mt5_sym)
        info = mt5.symbol_info(mt5_sym)

        if tick is None or info is None:
            logger.debug("MT5 symbol info unavailable for '%s'", mt5_sym)
            return dict(_EMPTY_QUOTE)

        # Last traded / mid price
        price: float = float(tick.last) if tick.last > 0.0 else float(
            (tick.ask + tick.bid) / 2.0 if tick.ask > 0.0 and tick.bid > 0.0
            else tick.ask or tick.bid
        )

        # Volume from the current tick session
        volume: float = float(tick.volume_real) if tick.volume_real > 0.0 else float(tick.volume)

        # Change % vs previous day's closed bar
        change_pct: float = 0.0
        try:
            # start_pos=1 fetches the last *closed* daily bar (yesterday).
            prev_rates = mt5.copy_rates_from_pos(mt5_sym, mt5.TIMEFRAME_D1, 1, 1)
            if prev_rates is not None and len(prev_rates) == 1:
                prev_close = float(prev_rates[0]["close"])
                if prev_close > 0.0 and price > 0.0:
                    change_pct = (price - prev_close) / prev_close * 100.0
        except Exception as exc:
            logger.debug("MT5 change_pct computation failed for '%s': %s", mt5_sym, exc)

        return {
            "price":      price,
            "change_pct": change_pct,
            "volume":     volume,
            "market_cap": 0.0,
            "source":     "mt5",
        }
