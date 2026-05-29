"""
data.connectors package
=======================
One module per external data source.

Each module exposes exactly one public class that inherits from
``data.base.DataSourceBase``.

Current connectors
------------------
yahoo_finance.py   : YahooFinanceConnector  — equities via yfinance
coingecko.py       : CoinGeckoConnector     — crypto via pycoingecko
mt5_connector.py   : MT5Connector           — equities/forex via MetaTrader5

Planned connectors (do not implement yet)
-----------------------------------------
binance.py         : BinanceConnector       — spot + futures, WebSocket
alpha_vantage.py   : AlphaVantageConnector  — equities, forex, macro
alpaca.py          : AlpacaConnector        — equities, paper trading

Adding a connector
------------------
1. Create a new module here, e.g. ``binance.py``.
2. Define a class that inherits from ``DataSourceBase`` and implements
   ``get_historical`` and ``get_quote``.
3. Register the connector key in ``data.factory`` (to be created).
4. No other module requires modification.
"""

__all__: list[str] = []

try:
    from trd_auto.data.connectors.mt5_connector import MT5Connector
    __all__ = [*__all__, "MT5Connector"]
except ImportError:
    pass
