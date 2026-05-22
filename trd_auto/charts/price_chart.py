"""
charts.price_chart
==================
Candlestick price chart component.

Renders an interactive Plotly candlestick chart from a canonical OHLCV
DataFrame directly into the active Streamlit container.

Class
-----
PriceChart
    Inherits from ``ChartBase``.
    Implements ``render(df) -> None``.

Visual conventions
------------------
- Bullish candles (close >= open) : green  (#26a69a)
- Bearish candles (close <  open) : red    (#ef5350)
- Background                      : #0e1117 (matches Streamlit dark theme)
- Grid lines                      : #1e2130 (subtle, low-contrast)
- Range-slider                    : disabled

Planned extensions (do not implement yet)
-----------------------------------------
- Bollinger Band overlay traces
- Volume profile on the right Y-axis
- Trade signal markers (buy/sell arrows)
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from charts.base import ChartBase

# ---------------------------------------------------------------------------
# Shared styling constants
# ---------------------------------------------------------------------------
_COLOR_UP:   str = "#26a69a"   # bullish green
_COLOR_DOWN: str = "#ef5350"   # bearish red
_BG:         str = "#0e1117"   # Streamlit dark background
_GRID:       str = "#1e2130"   # subtle grid
_TEXT:       str = "#fafafa"   # axis labels / title
_HEIGHT:     int = 480


class PriceChart(ChartBase):
    """
    Interactive candlestick chart for OHLC price data.

    Inherits from ``ChartBase`` and renders directly via
    ``st.plotly_chart(use_container_width=True)``.
    """

    def render(self, df: pd.DataFrame, indicators: bool = True) -> None:
        """
        Build and render the candlestick chart.

        Parameters
        ----------
        df : pd.DataFrame
            Canonical OHLCV DataFrame.  When ``indicators=True`` and the
            DataFrame contains ``bb_upper``, ``bb_middle``, ``bb_lower``
            columns (added by ``data.indicators.compute_indicators``), a
            Bollinger Band overlay is drawn automatically.
        indicators : bool
            When *True* (default), overlay Bollinger Bands if present.

        Returns
        -------
        None
            Renders directly into the active Streamlit container.
            Returns early silently when ``df`` is empty.
        """
        if df.empty:
            return

        has_bb = indicators and "bb_upper" in df.columns

        fig = go.Figure(
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color=_COLOR_UP,
                increasing_fillcolor=_COLOR_UP,
                decreasing_line_color=_COLOR_DOWN,
                decreasing_fillcolor=_COLOR_DOWN,
                name="",
                showlegend=False,
            )
        )

        if has_bb:
            _BB_COLOR = "#7986cb"
            # Upper band — drawn first so "tonexty" fill on lower traces back to it
            fig.add_trace(go.Scatter(
                x=df["timestamp"],
                y=df["bb_upper"],
                name="BB Upper",
                line=dict(color=_BB_COLOR, width=1, dash="dot"),
                legendgroup="bb",
                showlegend=True,
            ))
            # Lower band — filled area between lower and upper
            fig.add_trace(go.Scatter(
                x=df["timestamp"],
                y=df["bb_lower"],
                name="BB Lower",
                fill="tonexty",
                fillcolor="rgba(121, 134, 203, 0.08)",
                line=dict(color=_BB_COLOR, width=1, dash="dot"),
                legendgroup="bb",
                showlegend=False,
            ))
            # Middle band (SMA 20)
            fig.add_trace(go.Scatter(
                x=df["timestamp"],
                y=df["bb_middle"],
                name="SMA 20",
                line=dict(color="#90a4ae", width=1),
                showlegend=True,
            ))

        fig.update_layout(
            height=_HEIGHT,
            plot_bgcolor=_BG,
            paper_bgcolor=_BG,
            font_color=_TEXT,
            margin=dict(l=0, r=0, t=24, b=0),
            showlegend=has_bb,
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=_TEXT, size=11),
                orientation="h",
                y=1.02,
                x=0,
            ),
            xaxis=dict(
                showgrid=True,
                gridcolor=_GRID,
                linecolor=_GRID,
                rangeslider_visible=False,
                color=_TEXT,
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor=_GRID,
                linecolor=_GRID,
                color=_TEXT,
                side="right",
            ),
        )

        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Module-level indicator sub-charts
# ---------------------------------------------------------------------------

def render_rsi(df: pd.DataFrame) -> None:
    """Render an RSI(14) line chart with overbought/oversold reference lines.

    Draws horizontal dashed lines at 30 (oversold) and 70 (overbought) and a
    shaded neutral zone between them.  No-ops when *df* is empty or lacks the
    ``rsi_14`` column.
    """
    if df.empty or "rsi_14" not in df.columns:
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["rsi_14"],
        name="RSI(14)",
        line=dict(color="#7986cb", width=1.5),
        showlegend=False,
    ))

    # Reference bands
    fig.add_hrect(y0=30, y1=70, fillcolor="rgba(255,255,255,0.03)", line_width=0)
    fig.add_hline(y=70, line_dash="dash", line_color="#ef5350", line_width=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#26a69a", line_width=1)

    fig.update_layout(
        height=200,
        plot_bgcolor=_BG,
        paper_bgcolor=_BG,
        font_color=_TEXT,
        title=dict(text="RSI (14)", font=dict(size=12, color=_TEXT), x=0),
        margin=dict(l=0, r=0, t=32, b=0),
        showlegend=False,
        xaxis=dict(
            showgrid=True,
            gridcolor=_GRID,
            linecolor=_GRID,
            color=_TEXT,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=_GRID,
            linecolor=_GRID,
            color=_TEXT,
            range=[0, 100],
            side="right",
            tickvals=[0, 30, 50, 70, 100],
        ),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_macd(df: pd.DataFrame) -> None:
    """Render a MACD chart (histogram + MACD line + signal line).

    No-ops when *df* is empty or lacks ``macd`` / ``macd_signal`` /
    ``macd_hist`` columns.
    """
    if df.empty or "macd" not in df.columns:
        return

    hist_values = df["macd_hist"].fillna(0)
    hist_colors = [_COLOR_UP if v >= 0 else _COLOR_DOWN for v in hist_values]

    fig = go.Figure()

    # Histogram bars
    fig.add_trace(go.Bar(
        x=df["timestamp"],
        y=hist_values,
        marker_color=hist_colors,
        name="Histogram",
        showlegend=True,
    ))
    # MACD line
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["macd"],
        name="MACD",
        line=dict(color="#7986cb", width=1.5),
    ))
    # Signal line
    fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["macd_signal"],
        name="Signal",
        line=dict(color="#ff8a65", width=1.5),
    ))

    # Zero reference
    fig.add_hline(y=0, line_color="#555555", line_width=1)

    fig.update_layout(
        height=200,
        plot_bgcolor=_BG,
        paper_bgcolor=_BG,
        font_color=_TEXT,
        title=dict(text="MACD (12, 26, 9)", font=dict(size=12, color=_TEXT), x=0),
        margin=dict(l=0, r=0, t=32, b=0),
        barmode="relative",
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=_TEXT, size=11),
            orientation="h",
            y=1.15,
            x=0,
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor=_GRID,
            linecolor=_GRID,
            color=_TEXT,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=_GRID,
            linecolor=_GRID,
            color=_TEXT,
            side="right",
        ),
    )

    st.plotly_chart(fig, use_container_width=True)
