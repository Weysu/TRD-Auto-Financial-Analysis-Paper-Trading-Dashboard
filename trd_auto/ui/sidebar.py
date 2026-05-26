"""
ui.sidebar
==========
Left-panel Streamlit controls for the financial dashboard.

Renders all user-facing controls and returns the selected values so
``app.py`` can drive data fetching and chart rendering accordingly.

The sidebar is the single point where ``config.assets`` values are
converted into Streamlit widgets.  No other module creates these controls.

Functions
---------
render_sidebar() -> tuple[str, dict, str]
    Renders the full sidebar and returns:
        - asset_label      : str  — human-readable label from ALL_ASSETS
        - asset_config     : dict — {"source": ..., "id": ...}
        - time_range_label : str  — period label key (e.g. "1M")

Planned extensions (do not implement yet)
-----------------------------------------
- Watchlist / favourites panel
- Alert threshold configuration
- Indicator toggle checkboxes (RSI, MACD, Bollinger)
- Data-source health-check status indicators
"""

import streamlit as st

from config.assets import (
    ALL_ASSETS,
    TIME_RANGES,
    DEFAULT_ASSET_LABEL,
    DEFAULT_TIME_RANGE_LABEL,
)


def render_sidebar() -> tuple[str, dict, str]:
    """
    Render the dashboard sidebar and return the user's current selections.

    Controls rendered (in order):
    - Asset selector  : ``st.selectbox`` populated from ``ALL_ASSETS``.
      Options are ordered stocks-first, crypto-second, matching the
      insertion order of ``ALL_ASSETS``.
    - Time-range selector : ``st.radio`` (horizontal) populated from the
      ``label`` field of each entry in ``TIME_RANGES``.

    Default selections on first load come from ``DEFAULT_ASSET_LABEL`` and
    ``DEFAULT_TIME_RANGE_LABEL`` defined in ``config.assets``.

    Parameters
    ----------
    None

    Returns
    -------
    asset_label : str
        Human-readable label of the chosen asset
        (e.g. ``"Bitcoin (BTC)"``, ``"Apple (AAPL)"``).
    asset_config : dict
        Corresponding entry from ``ALL_ASSETS``.
        Contains: ``{"source": str, "id": str}``.
    time_range_label : str
        Selected period label string (e.g. ``"1D"``, ``"1M"``, ``"1Y"``).
        Passed directly to connector methods as the ``period`` argument.
    """
    asset_labels: list[str] = list(ALL_ASSETS.keys())
    time_range_labels: list[str] = [tr["label"] for tr in TIME_RANGES]

    default_asset_idx: int = (
        asset_labels.index(DEFAULT_ASSET_LABEL)
        if DEFAULT_ASSET_LABEL in asset_labels
        else 0
    )
    default_tr_idx: int = (
        time_range_labels.index(DEFAULT_TIME_RANGE_LABEL)
        if DEFAULT_TIME_RANGE_LABEL in time_range_labels
        else 0
    )

    with st.sidebar:
        st.markdown("### TRD Auto")
        st.caption("Paper trading & analysis platform")
        st.divider()

        st.caption("Asset")
        asset_label: str = st.selectbox(
            label="Asset",
            options=asset_labels,
            index=default_asset_idx,
            label_visibility="collapsed",
        )

        st.caption("Time Range")
        time_range_label: str = st.radio(
            label="Time Range",
            options=time_range_labels,
            index=default_tr_idx,
            horizontal=True,
            label_visibility="collapsed",
        )

        st.divider()
        # Source badge — informs the user which connector will be used.
        source: str = ALL_ASSETS[asset_label]["source"]
        source_display: str = "Yahoo Finance" if source == "yahoo" else "CoinGecko"
        st.caption(f"Source : {source_display}")

    asset_config: dict = ALL_ASSETS[asset_label]

    return asset_label, asset_config, time_range_label
