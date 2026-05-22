"""
charts package
==============
Self-contained visualisation components built on Plotly.

Each chart type is an independent module exposing a single render
function that accepts a canonical DataFrame (or scalar dict) and returns
a ``plotly.graph_objects.Figure``.

The Streamlit UI layer calls these functions and passes the result to
``st.plotly_chart`` — it never constructs Plotly objects directly.

Modules
-------
charts.base         : Abstract base class for all chart components.
charts.price_chart  : Candlestick / OHLC chart for price history.
charts.volume_chart : Bar chart for traded volume over time.
charts.metrics      : KPI tile row (price, % change, period H/L).

Design constraints
------------------
- Each chart module is a standalone unit.  Adding a new chart type
  requires only creating a new module here.
- No data fetching or processing occurs inside chart modules.
- All styling constants (colours, fonts, margins) are defined inside
  each chart module, not scattered across the app.

Planned chart extensions (do not implement yet)
-----------------------------------------------
charts.rsi              : RSI oscillator panel
charts.macd             : MACD line + histogram panel
charts.bollinger        : Price chart with Bollinger Band overlay
charts.sentiment        : Sentiment score timeline
charts.portfolio        : Portfolio allocation / equity curve
"""
