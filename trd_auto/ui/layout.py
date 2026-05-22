"""
ui.layout
=========
Main content area composition for the financial dashboard.

Orchestrates the placement of metric tiles and chart components within the
Streamlit page.  All chart objects are instantiated and rendered here;
the function receives only pre-processed data — no fetching, no computation.

Functions
---------
render_main(label, asset_cfg, df, quote, metrics) -> None
    Renders the complete main content area in order:
    1. KPI metric tile row    (charts.metrics.render_metrics)
    2. Candlestick price chart (charts.price_chart.PriceChart)
    3. Volume bar chart        (charts.volume_chart.VolumeChart)

Planned extensions (do not implement yet)
-----------------------------------------
- render_indicator_panel(df) : RSI / MACD sub-panel below volume
- render_sentiment_panel(df) : Sentiment signal timeline
- render_portfolio_panel()   : Portfolio equity curve and allocation
"""

import pandas as pd
import streamlit as st

from charts.metrics import render_metrics
from charts.price_chart import PriceChart, render_macd, render_rsi
from charts.sentiment_chart import render_sentiment
from charts.volume_chart import VolumeChart
from data.signal_engine import compute_confluence


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _render_confluence(confluence: dict) -> None:
    """Render the confluence score, signal badge, breakdown table, and disclaimer."""
    score: int       = confluence["score"]
    max_score: int   = confluence["max_score"]
    signal: str      = confluence["signal"]
    breakdown: dict  = confluence["breakdown"]

    # Score metric + signal badge
    col_score, col_signal, _ = st.columns([1, 1, 4])

    with col_score:
        # Use a numeric delta (+1 / -1 / 0) to drive green / red / grey colouring.
        if score >= 3:
            st.metric("Confluence Score", f"{score} / {max_score}", delta=1,  delta_color="normal")
        elif score <= 1:
            st.metric("Confluence Score", f"{score} / {max_score}", delta=-1, delta_color="normal")
        else:
            st.metric("Confluence Score", f"{score} / {max_score}", delta=0,  delta_color="off")

    with col_signal:
        st.markdown("**Signal**")
        badge_color = "green" if score >= 3 else "red" if score <= 1 else "gray"
        st.badge(signal, color=badge_color)

    # Breakdown table
    rows: list[dict] = []
    for component, value in breakdown.items():
        if component == "Sentiment":
            icon = "▲" if value > 0 else ("▼" if value < 0 else "→")
            display = f"{icon} {value:+d}"
        else:
            display = "✓ Bullish" if value == 1 else "○ Bearish"
        rows.append({"Component": component, "Signal": display})

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Indicateur basé sur données historiques uniquement. "
        "Ne constitue pas un conseil financier."
    )


def render_main(
    label: str,
    asset_cfg: dict,
    df: pd.DataFrame,
    quote: dict,
    metrics: dict,
    sentiment: dict,
) -> None:
    """
    Render the full main content area of the financial dashboard.

    Renders (in order):
    1. A row of five KPI metric tiles via ``charts.metrics.render_metrics``.
    2. An interactive candlestick price chart via ``charts.price_chart.PriceChart``.
    3. A volume bar chart via ``charts.volume_chart.VolumeChart``.

    Both charts use ``use_container_width=True`` for responsive sizing.

    Parameters
    ----------
    label : str
        Human-readable asset label (e.g. ``"Bitcoin (BTC)"``).
        Used as the chart title prefix.
    asset_cfg : dict
        Asset config dict from ``config.assets.ALL_ASSETS``.
        Contains ``{"source": str, "id": str}``.  Used to display
        the data-source badge in the page header.
    df : pd.DataFrame
        Validated canonical OHLCV DataFrame from ``data.processor.validate``.
        If empty, a warning is shown and the function returns early.
    quote : dict
        Latest quote snapshot from the connector's ``get_quote`` method.
        Expected keys: ``price``, ``change_pct``, ``volume``,
        ``market_cap``, ``source``.
    metrics : dict
        Period scalar metrics from ``data.processor.compute_metrics``.
        Expected keys: ``change_pct``, ``high``, ``low``,
        ``avg_volume``, ``volatility``.

    Returns
    -------
    None
        Renders directly into the active Streamlit container.
    """
    # ------------------------------------------------------------------
    # Guard: nothing to render without data
    # ------------------------------------------------------------------
    if df.empty:
        st.warning(
            f"No data available for **{label}**. "
            "The asset may be temporarily unavailable or rate-limited. "
            "Try a different time range or check back shortly."
        )
        return

    # ------------------------------------------------------------------
    # Page header
    # ------------------------------------------------------------------
    source_display: str = (
        "Yahoo Finance" if asset_cfg.get("source") == "yahoo" else "CoinGecko"
    )
    st.subheader(label)
    st.caption(f"Data source: {source_display}")

    # ------------------------------------------------------------------
    # 1. KPI metric tiles
    # ------------------------------------------------------------------
    # Merge quote and metrics into the flat summary dict expected by
    # render_metrics.  ``change_24h`` drives the delta colour on the
    # price tile; ``change_pct`` is the full-period change.
    summary: dict = {
        "price":      quote.get("price"),
        "change_24h": quote.get("change_pct"),
        "change_pct": metrics.get("change_pct"),
        "high":       metrics.get("high"),
        "low":        metrics.get("low"),
        "volatility": metrics.get("volatility"),
    }
    render_metrics(summary)

    st.divider()

    # ------------------------------------------------------------------
    # 2. Candlestick price chart (with Bollinger Band overlay)
    # ------------------------------------------------------------------
    PriceChart().render(df, indicators=True)

    # ------------------------------------------------------------------
    # 3. Volume bar chart
    # ------------------------------------------------------------------
    VolumeChart().render(df)

    # ------------------------------------------------------------------
    # 4. Technical indicator sub-charts (collapsible)
    # ------------------------------------------------------------------
    with st.expander("Technical Indicators", expanded=False):
        render_rsi(df)
        render_macd(df)

    # ------------------------------------------------------------------
    # 5. Trading signal confluence (requires ≥ 60 bars of history)
    # ------------------------------------------------------------------
    if len(df) >= 60:
        confluence: dict = compute_confluence(df, sentiment)
        st.divider()
        st.subheader("🎯 Trading Signal")
        _render_confluence(confluence)

    # ------------------------------------------------------------------
    # 6. News sentiment
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("✉️ News Sentiment")
    render_sentiment(sentiment)
