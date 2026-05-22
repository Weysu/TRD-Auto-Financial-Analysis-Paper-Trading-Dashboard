"""
data package
============
Responsible for all data acquisition and normalisation.

Sub-packages / modules
-----------------------
data.base           : Abstract base class (DataSourceBase) that every
                      connector must implement.
data.connectors     : One module per external data source.  Each module
                      exposes a single connector class that inherits from
                      DataSourceBase.
data.processor      : Stateless helper functions that clean and normalise
                      raw DataFrames into the canonical schema expected by
                      the chart layer.

Planned extensions (do not add logic yet)
-----------------------------------------
- data.websocket    : Live price-feed adapters (Binance, Kraken streams)
- data.indicators   : RSI, MACD, Bollinger Bands computation
- data.sentiment    : Sentiment signal ingestion from external sources
- data.alerts       : Price/signal alert engine
"""
