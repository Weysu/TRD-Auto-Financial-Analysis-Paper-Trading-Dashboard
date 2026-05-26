"""
charts.metrics
==============
KPI tile row component for the dashboard header.

Renders a horizontal row of five scalar metric cards using Streamlit's
``st.metric`` widget.

This module is deliberately not a ``ChartBase`` subclass because it
produces Streamlit widgets rather than Plotly figures.  It is placed in
the ``charts`` package by convention since it is a visual display unit.

Function
--------
render_metrics(summary: dict) -> None
    Renders five KPI tiles directly into the active Streamlit container.

Expected keys in ``summary``
----------------------------
    price        : float  — latest traded price (from connector quote)
    change_24h   : float  — 24 h % change shown as delta on the price tile
    change_pct   : float  — period % change (first → last close)
    high         : float  — period high (max of ``high`` column)
    low          : float  — period low  (min of ``low`` column)
    volatility   : float  — std of daily close pct_change (decimal, e.g. 0.02)

All values tolerate ``float("nan")`` and ``None`` — displayed as ``"N/A"``.

Planned extensions (do not implement yet)
-----------------------------------------
- market_cap     : float  — crypto market cap tile
- rsi            : float  — RSI value with overbought/oversold colour coding
- sentiment_score: float  — external sentiment signal tile
"""

import math

import pandas as pd
import streamlit as st

from config.tooltips import METRIC_TOOLTIPS


# ---------------------------------------------------------------------------
# Private formatting helpers
# ---------------------------------------------------------------------------

def _is_missing(value: object) -> bool:
    """Return True when *value* is None, NaN, or non-finite."""
    if value is None:
        return True
    try:
        return math.isnan(float(value)) or math.isinf(float(value))
    except (TypeError, ValueError):
        return True


def _fmt_price(value: object) -> str:
    """Format a price as '$X,XXX.XX', or 'N/A' when missing."""
    if _is_missing(value):
        return "N/A"
    return f"${float(value):,.2f}"


def _fmt_pct(value: object) -> str:
    """Format a percentage as '+X.XX %' / '-X.XX %', or 'N/A' when missing."""
    if _is_missing(value):
        return "N/A"
    return f"{float(value):+.2f} %"


def _fmt_volatility(value: object) -> str:
    """
    Format volatility (std of pct_change, expressed as a decimal) as a
    percentage string, e.g. 0.0213 → '2.13 %'.
    """
    if _is_missing(value):
        return "N/A"
    return f"{float(value) * 100:.2f} %"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_metrics(summary: dict) -> None:
    """
    Render a horizontal row of five KPI metric tiles.

    Tiles (left → right):
    1. **Price**       — latest quote price; delta shows 24 h % change.
    2. **Period Chg.** — % change from first to last close in the period.
    3. **High**        — period maximum of the ``high`` column.
    4. **Low**         — period minimum of the ``low`` column.
    5. **Volatility**  — std of daily close pct_change, expressed as %.

    Parameters
    ----------
    summary : dict
        Flat dict assembled by ``ui.layout.render_main``.
        Required keys: ``price``, ``change_24h``, ``change_pct``,
        ``high``, ``low``, ``volatility``.
        Missing or NaN values are displayed as ``"N/A"``.

    Returns
    -------
    None
        Renders directly into the active Streamlit container.
    """
    price      = summary.get("price")
    change_24h = summary.get("change_24h")
    change_pct = summary.get("change_pct")
    high       = summary.get("high")
    low        = summary.get("low")
    volatility = summary.get("volatility")

    # Delta for the price tile: show 24 h change with directional colour.
    price_delta: str | None = _fmt_pct(change_24h) if not _is_missing(change_24h) else None

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(label="Price", value=_fmt_price(price), delta=price_delta,
                  help=METRIC_TOOLTIPS.get("Price", ""))
    with col2:
        st.metric(label="Period Chg.", value=_fmt_pct(change_pct),
                  help=METRIC_TOOLTIPS.get("Period Chg.", ""))
    with col3:
        st.metric(label="High", value=_fmt_price(high),
                  help=METRIC_TOOLTIPS.get("High", ""))
    with col4:
        st.metric(label="Low", value=_fmt_price(low),
                  help=METRIC_TOOLTIPS.get("Low", ""))
    with col5:
        st.metric(label="Volatility", value=_fmt_volatility(volatility),
                  help=METRIC_TOOLTIPS.get("Volatility", ""))
