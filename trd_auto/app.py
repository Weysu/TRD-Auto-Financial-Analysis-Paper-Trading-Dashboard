"""
app.py — Financial Dashboard entry point
=========================================
Main Streamlit application for the TRD Auto financial dashboard.

This module is the composition root.  It:
1. Configures the Streamlit page (wide layout, title, icon).
2. Calls ``ui.sidebar.render_sidebar`` to get user selections.
3. Resolves the correct connector from ``CONNECTOR_REGISTRY`` using the
   ``source`` key stored in each asset's config dict.
4. Fetches OHLCV history (cached, 5 min TTL) and the latest quote.
5. Validates and computes metrics via ``data.processor``.
6. Delegates rendering to ``ui.layout.render_main``.

This module contains no business logic, no chart construction code, and
no raw API calls — it is a thin orchestration layer only.

Run
---
    streamlit run app.py

Planned extensions (do not implement yet)
-----------------------------------------
- Auto-refresh loop for live WebSocket price feeds.
- Session-state caching to avoid redundant fetches on widget interaction.
- Multi-asset comparison mode.
"""

import pandas as pd
import streamlit as st
import os
import sys

# ---------------------------------------------------------------------------
# Ensure the project root is in sys.path so that the ``paper_trader`` package
# (which lives at the same level as ``trd_auto``) is importable.
# ---------------------------------------------------------------------------
_TRDAUTO_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TRDAUTO_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from data.base import DataSourceBase
from data.connectors.coingecko import CoinGeckoConnector
from data.connectors.yahoo_finance import YahooFinanceConnector
from data import processor
from data.indicators import compute_indicators
from data.sentiment import get_sentiment
from ui.layout import render_main
from ui.sidebar import render_sidebar

# paper_trader.monitor is imported lazily inside _paper_trading_page() so that
# Streamlit's hot-reload picks up changes without a full server restart.
# importlib.reload() is called only when the module's source file has changed
# (mtime-based check), making repeated renders cheap.
_monitor_mtime: float = 0.0


def _paper_trading_page() -> None:
    """Thin shim: lazily import + conditionally reload paper_trader.monitor."""
    import importlib
    import paper_trader.monitor as _mod

    global _monitor_mtime
    try:
        import inspect
        src = inspect.getfile(_mod)
        current_mtime = os.path.getmtime(src)
        if current_mtime != _monitor_mtime:
            _mod = importlib.reload(_mod)
            _monitor_mtime = current_mtime
    except Exception:
        pass  # if mtime check fails, use whatever is cached

    _mod.paper_trading_page()

# ---------------------------------------------------------------------------
# Connector registry
# Maps the "source" key from config.assets.ALL_ASSETS to its connector class.
# Adding a new source requires only a new entry here — zero other changes.
# ---------------------------------------------------------------------------
CONNECTOR_REGISTRY: dict[str, type[DataSourceBase]] = {
    "yahoo":     YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}


# ---------------------------------------------------------------------------
# Cached data fetcher
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_historical(source: str, symbol: str, period: str) -> pd.DataFrame:
    """
    Fetch OHLCV history and cache the result for 300 seconds (5 minutes).

    A new connector instance is created per call; this is safe because all
    connectors are stateless.  The cache key is ``(source, symbol, period)``
    — fully serialisable strings.  ``show_spinner=False`` suppresses the
    default cache spinner; the caller renders its own via ``st.spinner``.

    Parameters
    ----------
    source : str
        Connector registry key (e.g. ``"yahoo"``, ``"coingecko"``).
    symbol : str
        Asset identifier passed directly to the connector
        (ticker or CoinGecko coin ID).
    period : str
        Canonical period label (e.g. ``"1M"``).

    Returns
    -------
    pd.DataFrame
        Raw OHLCV DataFrame from the connector (not yet validated).
    """
    connector: DataSourceBase = CONNECTOR_REGISTRY[source]()
    return connector.get_historical(symbol, period)


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_quote(source: str, symbol: str) -> dict:
    """
    Fetch the latest quote snapshot and cache it for 300 seconds.

    Caching avoids redundant API calls when the user changes only the
    time-range selector (which does not affect the quote).  TTL matches
    ``_fetch_historical`` so both expire together.

    Parameters
    ----------
    source : str
        Connector registry key (e.g. ``"yahoo"``, ``"coingecko"``).
    symbol : str
        Asset identifier passed directly to the connector.

    Returns
    -------
    dict
        Quote dict with keys: price, change_pct, volume, market_cap, source.
    """
    connector: DataSourceBase = CONNECTOR_REGISTRY[source]()
    return connector.get_quote(symbol)


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def dashboard() -> None:
    """
    Full render cycle: sidebar → fetch → process → render.

    Invoked by ``st.navigation`` when the Dashboard page is active.
    ``st.set_page_config`` is called at module level (before ``st.navigation``)
    so it always runs first regardless of the active page.
    """
    # ------------------------------------------------------------------
    # 1. Sidebar controls
    # ------------------------------------------------------------------
    asset_label: str
    asset_cfg: dict
    time_range_label: str
    asset_label, asset_cfg, time_range_label = render_sidebar()

    source: str = asset_cfg["source"]
    symbol: str = asset_cfg["id"]

    # ------------------------------------------------------------------
    # 2. Guard: unknown source key
    # ------------------------------------------------------------------
    if source not in CONNECTOR_REGISTRY:
        st.error(
            f"Unknown data source **{source!r}** for asset **{asset_label}**. "
            "Ensure every entry in `config/assets.py` has a valid `source` key "
            f"matching one of: {list(CONNECTOR_REGISTRY.keys())}."
        )
        return

    # ------------------------------------------------------------------
    # 3. Data fetch  (both calls cached, single spinner for the pair)
    # ------------------------------------------------------------------
    df: pd.DataFrame
    quote: dict

    with st.spinner("Loading data…"):
        try:
            df = _fetch_historical(source, symbol, time_range_label)
        except Exception as exc:
            st.error(
                f"Failed to fetch historical data for **{asset_label}** "
                f"({time_range_label}): {exc}"
            )
            return

        try:
            quote = _fetch_quote(source, symbol)
        except Exception as exc:
            st.error(f"Failed to fetch quote for **{asset_label}**: {exc}")
            return

    with st.spinner("Scoring sentiment…"):
        sentiment: dict = get_sentiment(asset_label, symbol, source)

    # ------------------------------------------------------------------
    # 4. Compute indicators on raw df, then validate and compute metrics
    # ------------------------------------------------------------------
    df = compute_indicators(df)

    try:
        df = processor.validate(df)
    except ValueError as exc:
        st.error(f"Data validation error for **{asset_label}**: {exc}")
        return

    metrics: dict = processor.compute_metrics(df)

    # ------------------------------------------------------------------
    # 5. Render
    # ------------------------------------------------------------------
    render_main(
        label=asset_label,
        asset_cfg=asset_cfg,
        df=df,
        quote=quote,
        metrics=metrics,
        sentiment=sentiment,
    )


st.set_page_config(
    page_title="TRD Auto",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation(
    [
        st.Page(dashboard, title="Dashboard"),
        st.Page("backtest.py", title="Backtest"),
        st.Page(_paper_trading_page, title="Paper Trading"),
    ]
)
pg.run()

