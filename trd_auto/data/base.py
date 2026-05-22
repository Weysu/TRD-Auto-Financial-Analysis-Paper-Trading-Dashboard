"""
data.base
=========
Defines the abstract interface that every data-source connector must
implement.

Design goals
------------
- Open/Closed Principle: adding a new data source (Binance, Alpha Vantage,
  Alpaca …) only requires creating a new subclass in data/connectors/.
  No existing code is modified.
- All connectors return data in the same canonical schema so the chart
  and processing layers are entirely source-agnostic.

Canonical DataFrame schema  (``get_historical`` return value)
-------------------------------------------------------------
Column      dtype       Description
----------  ----------  -------------------------------------------
timestamp   datetime64  Bar open time, UTC-aware (DatetimeTZDtype)
open        float64     Opening price of the bar
high        float64     Highest price of the bar
low         float64     Lowest price of the bar
close       float64     Closing / last price of the bar
volume      float64     Traded volume in base-asset units

The DataFrame uses a default integer index; ``timestamp`` is a regular
column so that downstream processing and chart code can handle it
uniformly without index-manipulation boilerplate.

Canonical dict schema  (``get_quote`` return value)
---------------------------------------------------
Key             type    Description
--------------  ------  -------------------------------------------
price           float   Latest traded / mark price
change_pct      float   Percentage change over the last 24 h / session
volume_24h      float   Total traded volume over the last 24 hours

Connectors may include additional keys (e.g. ``market_cap``,
``circulating_supply``) without breaking compatibility.

Planned extensions (do not add logic yet)
-----------------------------------------
- ``get_orderbook(symbol)``  : L2 order-book snapshot for WebSocket feeds
- ``stream_price(symbol)``   : async generator for live tick data
- ``get_sentiment(symbol)``  : sentiment score from external signal sources
"""

from abc import ABC, abstractmethod

import pandas as pd


class DataSourceBase(ABC):
    """
    Abstract base class for all market-data connectors.

    Every concrete connector must inherit from this class and implement
    both abstract methods.  The Streamlit app and chart layer interact
    exclusively with this interface — they are entirely unaware of the
    underlying data provider.

    Connectors are stateless by design.  Any credentials or client
    instances required by a concrete source should be created in that
    subclass's ``__init__`` and stored as instance attributes.
    """

    # ------------------------------------------------------------------
    # Abstract interface — must be implemented by every connector
    # ------------------------------------------------------------------

    @abstractmethod
    def get_historical(self, symbol: str, period: str) -> pd.DataFrame:
        """
        Fetch OHLCV historical price data for the given asset.

        Parameters
        ----------
        symbol : str
            Asset identifier understood by the underlying provider.
            Examples: ``"AAPL"`` (Yahoo Finance), ``"bitcoin"`` (CoinGecko).
        period : str
            Look-back window using a canonical label defined in
            ``config.assets.TIME_RANGES`` (e.g. ``"1D"``, ``"1W"``,
            ``"1M"``, ``"3M"``, ``"1Y"``).  Connectors are responsible
            for translating this label into provider-specific parameters.

        Returns
        -------
        pd.DataFrame
            DataFrame conforming to the canonical OHLCV schema described
            in the module docstring.  Columns (in order):

                timestamp, open, high, low, close, volume

            ``timestamp`` is a regular column of UTC-aware
            ``datetime64[ns, UTC]`` values — **not** the index.
            Returns an **empty DataFrame with the correct columns** on
            any retrieval failure so callers can detect the error without
            catching exceptions.
        """
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> dict:
        """
        Fetch the latest real-time (or near-real-time) quote for the asset.

        Parameters
        ----------
        symbol : str
            Asset identifier understood by the underlying provider.
            Examples: ``"AAPL"`` (Yahoo Finance), ``"bitcoin"`` (CoinGecko).

        Returns
        -------
        dict
            Flat dictionary conforming to the canonical quote schema
            described in the module docstring.  Required keys:

                price, change_pct, volume_24h

            All values are ``float``.  Additional provider-specific keys
            are permitted.  Returns an **empty dict** on any retrieval
            failure so callers can detect the error without catching
            exceptions.
        """
        ...

    # ------------------------------------------------------------------
    # Optional hook — subclasses may override for health checks
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return ``True`` if the data source is currently reachable.

        The default implementation always returns ``True``.  Override in
        concrete connectors to perform a lightweight connectivity check
        (e.g. a minimal API ping) before the app attempts a full fetch.
        """
        return True

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
