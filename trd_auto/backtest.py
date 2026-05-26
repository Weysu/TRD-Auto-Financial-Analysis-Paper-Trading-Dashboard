"""backtest.py — Strategy Backtesting page.

Rendered by ``st.navigation`` in ``app.py``.  Provides an interactive
strategy backtester with a sidebar for asset / time-range / strategy
selection and a main area showing the equity curve, KPI metrics, and a
trade-log table.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import processor
from data.backtester import run_backtest
from data.base import DataSourceBase
from data.connectors.coingecko import CoinGeckoConnector
from data.connectors.yahoo_finance import YahooFinanceConnector
from data.strategies import (
    run_bollinger_bands,
    run_ma_crossover,
    run_macd_crossover,
    run_rsi_strategy,
)
from config.tooltips import INDICATOR_TOOLTIPS, METRIC_TOOLTIPS
from ui.sidebar import render_sidebar

# ---------------------------------------------------------------------------
# Dark-theme constants (mirrored from charts/)
# ---------------------------------------------------------------------------
_BG: str   = "#0e1117"
_GRID: str = "#1e2130"
_TEXT: str = "#fafafa"

_STRATEGY_OPTIONS: list[str] = [
    "MA Crossover",
    "RSI",
    "Bollinger Bands",
    "MACD Crossover",
]

_CONNECTOR_REGISTRY: dict[str, type[DataSourceBase]] = {
    "yahoo":     YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}


# ---------------------------------------------------------------------------
# Data fetcher (local cache — does not depend on app.py)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_historical(source: str, symbol: str, period: str) -> pd.DataFrame:
    connector: DataSourceBase = _CONNECTOR_REGISTRY[source]()
    return connector.get_historical(symbol, period)


# ---------------------------------------------------------------------------
# Sidebar helpers
# ---------------------------------------------------------------------------

def _render_strategy_sidebar() -> tuple[str, dict]:
    """Append strategy selector and parameter sliders to the sidebar.

    Must be called *after* ``render_sidebar()`` so the asset/time controls
    appear first.

    Returns
    -------
    tuple[str, dict]
        ``(strategy_name, params)`` where ``params`` is a kwargs dict
        ready to be unpacked into the corresponding strategy function.
    """
    with st.sidebar:
        st.divider()
        st.caption("Strategy")
        strategy: str = st.selectbox(
            "Strategy",
            _STRATEGY_OPTIONS,
            label_visibility="collapsed",
            key="backtest_strategy",
            help=INDICATOR_TOOLTIPS.get(
                st.session_state.get("backtest_strategy", _STRATEGY_OPTIONS[0]), ""
            ),
        )

        params: dict = {}

        if strategy == "MA Crossover":
            params["fast_ma"] = st.slider("Fast MA", 5, 50, 20)
            params["slow_ma"] = st.slider("Slow MA", 20, 200, 50)
            if params["fast_ma"] >= params["slow_ma"]:
                st.error("Fast period must be smaller than slow period.")
                st.stop()

        elif strategy == "RSI":
            params["rsi_period"] = st.slider("RSI Period", 7, 21, 14)
            params["oversold"]   = st.slider("Oversold",   20, 40, 30)
            params["overbought"] = st.slider("Overbought", 60, 80, 70)

        elif strategy == "Bollinger Bands":
            params["bb_period"] = st.slider("Period",  10, 30, 20)
            params["bb_std"]    = st.slider("Std Dev", 1.0, 3.0, 2.0, step=0.1)

        elif strategy == "MACD Crossover":
            params["fast"]          = st.slider("Fast EMA", 8,  20, 12)
            params["slow"]          = st.slider("Slow EMA", 20, 40, 26)
            params["signal_period"] = st.slider("Signal",   5,  15,  9)
            if params["fast"] >= params["slow"]:
                st.error("Fast period must be smaller than slow period.")
                st.stop()

    return strategy, params


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------

def _apply_strategy(df: pd.DataFrame, strategy: str, params: dict) -> pd.DataFrame:
    """Route ``df`` through the correct strategy function."""
    if strategy == "MA Crossover":
        return run_ma_crossover(df, **params)
    if strategy == "RSI":
        return run_rsi_strategy(df, **params)
    if strategy == "Bollinger Bands":
        return run_bollinger_bands(df, **params)
    if strategy == "MACD Crossover":
        return run_macd_crossover(df, **params)
    return df


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_equity_chart(result: dict) -> None:
    """Plot strategy equity curve vs buy-and-hold baseline."""
    eq: pd.Series = result["equity_curve"]
    bh: pd.Series = result["bh_equity"]

    if eq.empty:
        st.info("No equity data to plot.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=eq.index,
            y=eq.values,
            name="Strategy",
            line=dict(color="#7986cb", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=bh.index,
            y=bh.values,
            name="Buy & Hold",
            line=dict(color="#90a4ae", width=1.5, dash="dot"),
        )
    )
    fig.update_layout(
        height=400,
        plot_bgcolor=_BG,
        paper_bgcolor=_BG,
        font_color=_TEXT,
        margin=dict(l=0, r=0, t=24, b=0),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=_TEXT, size=11),
            orientation="h",
            y=1.04,
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
            title="Portfolio Value (USD)",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_kpis(result: dict) -> None:
    """Render the six backtest KPIs as a single column row."""
    total_ret: float    = result["total_return_pct"]
    bh_ret: float       = result["buy_hold_return_pct"]
    win_rate: float     = result["win_rate"]
    drawdown: float     = result["max_drawdown_pct"]
    sharpe: float       = result["sharpe_ratio"]
    num_trades: int     = result["num_trades"]

    cols = st.columns(6)
    with cols[0]:
        st.metric(
            "Total Return",
            f"{total_ret:.2f}%",
            delta=f"{total_ret - bh_ret:+.2f}% vs B&H",
            help=METRIC_TOOLTIPS.get("Total Return Backtest", ""),
        )
    with cols[1]:
        st.metric("Buy & Hold", f"{bh_ret:.2f}%",
                  help=METRIC_TOOLTIPS.get("Buy & Hold", ""))
    with cols[2]:
        st.metric("Trades", num_trades,
                  help=METRIC_TOOLTIPS.get("Trades", ""))
    with cols[3]:
        st.metric("Win Rate", f"{win_rate * 100:.1f}%",
                  help=METRIC_TOOLTIPS.get("Win Rate", ""))
    with cols[4]:
        st.metric("Max Drawdown", f"{abs(drawdown):.2f}%",
                  help=METRIC_TOOLTIPS.get("Max Drawdown", ""))
    with cols[5]:
        st.metric("Sharpe Ratio", f"{sharpe:.2f}",
                  help=METRIC_TOOLTIPS.get("Sharpe Ratio", ""))


def _render_trade_log(result: dict) -> None:
    """Render completed trades as a formatted DataFrame."""
    trades: list[dict] = result.get("trades", [])

    if not trades:
        st.info("No completed trades in the selected period.")
        return

    df_trades = pd.DataFrame(trades)

    # Format for display
    df_trades["return_pct"] = df_trades["return_pct"].map(lambda x: f"{x:.2f}%")
    df_trades["pnl"]        = df_trades["pnl"].map(lambda x: f"${x:,.2f}")
    df_trades.rename(
        columns={
            "entry_date":  "Entry Date",
            "exit_date":   "Exit Date",
            "entry_price": "Entry Price",
            "exit_price":  "Exit Price",
            "shares":      "Shares",
            "pnl":         "P&L",
            "return_pct":  "Return (%)",
        },
        inplace=True,
    )

    st.dataframe(df_trades, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Backtest page render cycle."""
    # 1. Sidebar: asset + time range (reuse dashboard sidebar controls)
    asset_label, asset_cfg, time_range_label = render_sidebar()

    # 2. Sidebar: strategy selector + params
    strategy, params = _render_strategy_sidebar()

    source: str = asset_cfg["source"]
    symbol: str = asset_cfg["id"]

    # 3. Header
    st.subheader("Backtest")
    st.caption(f"{strategy}  ·  {asset_label}  ·  {time_range_label}")

    # 4. Fetch + validate
    if source not in _CONNECTOR_REGISTRY:
        st.error(f"Unknown data source {source!r}.")
        return

    with st.spinner("Loading data…"):
        try:
            df = _fetch_historical(source, symbol, time_range_label)
        except Exception as exc:
            st.error(f"Failed to fetch data: {exc}")
            return

    df = processor.validate(df)

    if df.empty:
        st.warning("No data available for the selected asset and time range.")
        return

    # 5. Apply strategy
    df = _apply_strategy(df, strategy, params)

    # 6. Run backtest — use 365 for crypto (trades every calendar day)
    annualization_factor: int = 365 if source == "coingecko" else 252
    result = run_backtest(df, annualization_factor=annualization_factor)

    # 7. Equity curve
    st.subheader("Equity Curve")
    _render_equity_chart(result)

    # 8. KPI row
    st.divider()
    st.caption("Performance Metrics")
    _render_kpis(result)

    # 9. Trade log
    st.divider()
    st.subheader("Trade Log")
    _render_trade_log(result)


main()
