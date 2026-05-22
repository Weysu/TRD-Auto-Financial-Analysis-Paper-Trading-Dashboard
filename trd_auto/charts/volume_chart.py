"""
charts.volume_chart
===================
Traded-volume bar chart component.

Renders an interactive Plotly bar chart of the ``volume`` column from a
canonical OHLCV DataFrame directly into the active Streamlit container.
Bar colours mirror price direction to aid visual correlation with the
candlestick chart above.

Class
-----
VolumeChart
    Inherits from ``ChartBase``.
    Implements ``render(df) -> None``.

Visual conventions
------------------
- Up-volume bars   : semi-transparent green (#26a69a, 70 % opacity)
- Down-volume bars : semi-transparent red   (#ef5350, 70 % opacity)
- Background and grid follow the same dark theme as PriceChart.

Planned extensions (do not implement yet)
-----------------------------------------
- 20-period average-volume overlay line
- On-balance volume (OBV) toggle
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from charts.base import ChartBase

# ---------------------------------------------------------------------------
# Shared styling constants (mirror PriceChart values)
# ---------------------------------------------------------------------------
_COLOR_UP:   str = "rgba(38, 166, 154, 0.70)"   # #26a69a at 70 % opacity
_COLOR_DOWN: str = "rgba(239,  83,  80, 0.70)"   # #ef5350 at 70 % opacity
_BG:         str = "#0e1117"
_GRID:       str = "#1e2130"
_TEXT:       str = "#fafafa"
_HEIGHT:     int = 180


class VolumeChart(ChartBase):
    """
    Bar chart displaying traded volume per candle period.

    Bar colour matches price direction: green when ``close >= open``,
    red otherwise.  Inherits from ``ChartBase`` and renders directly via
    ``st.plotly_chart(use_container_width=True)``.
    """

    def render(self, df: pd.DataFrame) -> None:
        """
        Build and render the volume bar chart.

        Parameters
        ----------
        df : pd.DataFrame
            Canonical OHLCV DataFrame with columns:
            ``timestamp``, ``open``, ``close``, ``volume``.

        Returns
        -------
        None
            Renders directly into the active Streamlit container.
            Returns early silently when ``df`` is empty.
        """
        if df.empty:
            return

        # Colour each bar by price direction.
        colors: list[str] = [
            _COLOR_UP if float(c) >= float(o) else _COLOR_DOWN
            for c, o in zip(df["close"], df["open"])
        ]

        fig = go.Figure(
            go.Bar(
                x=df["timestamp"],
                y=df["volume"],
                marker_color=colors,
                name="Volume",
                showlegend=False,
            )
        )

        fig.update_layout(
            height=_HEIGHT,
            plot_bgcolor=_BG,
            paper_bgcolor=_BG,
            font_color=_TEXT,
            margin=dict(l=0, r=0, t=8, b=0),
            showlegend=False,
            bargap=0.1,
            xaxis=dict(
                showgrid=False,
                linecolor=_GRID,
                color=_TEXT,
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor=_GRID,
                linecolor=_GRID,
                color=_TEXT,
                side="right",
                tickformat=".2s",   # e.g. 1.2M, 500K
            ),
        )

        st.plotly_chart(fig, use_container_width=True)
