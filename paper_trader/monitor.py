"""
paper_trader.monitor
====================
Streamlit page for the paper trading monitor.

Displays
--------
- KPI tiles: equity, cash, total return %, open positions count.
- Open positions table with unrealised PnL per row.
- Closed trades table with realised PnL per row.
- Equity curve: cumulative value over time derived from trade history.

This module is imported by ``trd_auto/app.py`` and passed as a callable to
``st.Page``.  Path bootstrap runs at module level so imports from both
``paper_trader`` and ``trd_auto`` resolve correctly.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — runs once at import time.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_TRDAUTO = os.path.join(_PROJECT_ROOT, "trd_auto")

for _p in (_PROJECT_ROOT, _TRDAUTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from paper_trader.db import (  # noqa: E402
    get_open_positions,
    get_portfolio,
    get_trade_history,
)
from paper_trader.portfolio import Portfolio  # noqa: E402
from data.connectors.coingecko import CoinGeckoConnector  # noqa: E402
from data.connectors.yahoo_finance import YahooFinanceConnector  # noqa: E402
from data.base import DataSourceBase  # noqa: E402

_CONNECTOR_REGISTRY: dict[str, type[DataSourceBase]] = {
    "yahoo": YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_price_cached(source: str, symbol: str) -> float:
    """Fetch and cache the current price for 2 minutes."""
    try:
        connector = _CONNECTOR_REGISTRY[source]()
        quote = connector.get_quote(symbol)
        return float(quote.get("price", float("nan")))
    except Exception:
        return float("nan")


def _current_prices_for_positions(
    positions: list[dict[str, Any]],
) -> dict[str, float]:
    """Return a ``symbol → price`` dict for all open positions."""
    prices: dict[str, float] = {}
    for pos in positions:
        symbol = pos["symbol"]
        if symbol not in prices:
            prices[symbol] = _fetch_price_cached(pos["source"], symbol)
    return prices


def _build_equity_curve(
    trades: list[dict[str, Any]],
    initial_capital: float,
) -> pd.DataFrame:
    """
    Build a cumulative equity curve from closed trade history.

    Returns a DataFrame with columns ``date`` and ``equity``, starting at
    ``initial_capital`` before the first trade and advancing by each trade's
    realised PnL.
    """
    if not trades:
        return pd.DataFrame({"date": [], "equity": []})

    df = pd.DataFrame(trades)[["exit_date", "pnl"]].copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"], utc=True)
    df = df.sort_values("exit_date").reset_index(drop=True)
    df["equity"] = initial_capital + df["pnl"].cumsum()

    # Prepend the starting point.
    start = pd.DataFrame(
        {"exit_date": [df["exit_date"].iloc[0]], "equity": [initial_capital]}
    )
    curve = pd.concat([start, df[["exit_date", "equity"]]], ignore_index=True)
    curve = curve.rename(columns={"exit_date": "date"})
    return curve


def _colour(value: float) -> str:
    """Return a green / red / grey CSS colour string based on sign."""
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "grey"


# ---------------------------------------------------------------------------
# Page function (callable for st.Page)
# ---------------------------------------------------------------------------


def paper_trading_page() -> None:
    """Render the full Paper Trading monitor page."""
    st.title("💼 Paper Trading Monitor")

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    portfolio_row = get_portfolio()
    if not portfolio_row:
        st.warning(
            "No portfolio found.  Start the engine at least once to initialise "
            "the database:  `python -m paper_trader.engine`"
        )
        return

    initial_capital: float = portfolio_row.get("initial_capital", 10_000.0)
    open_positions = get_open_positions()
    trades = get_trade_history()

    # Fetch current prices for open positions (cached).
    with st.spinner("Fetching live prices…"):
        prices = _current_prices_for_positions(open_positions)

    portfolio = Portfolio(initial_capital)
    summary = portfolio.get_summary(prices)

    # ------------------------------------------------------------------
    # 2. KPI tiles
    # ------------------------------------------------------------------
    st.subheader("Portfolio Summary")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        label="Equity",
        value=f"${summary['equity']:,.2f}",
    )
    col2.metric(
        label="Cash",
        value=f"${summary['cash']:,.2f}",
    )
    ret = summary["total_return_pct"]
    col3.metric(
        label="Total Return",
        value=f"{ret:+.2f}%",
        delta=f"{ret:+.2f}%",
        delta_color="normal",
    )
    col4.metric(
        label="Open Positions",
        value=str(summary["num_open_positions"]),
    )

    st.divider()

    # ------------------------------------------------------------------
    # 3. Open positions table
    # ------------------------------------------------------------------
    st.subheader("Open Positions")
    if not open_positions:
        st.info("No open positions.")
    else:
        rows: list[dict[str, Any]] = []
        for pos in open_positions:
            symbol = pos["symbol"]
            current = prices.get(symbol, float("nan"))
            if current == current and pos["entry_price"] > 0:  # not NaN
                unrealised_pnl = (current - pos["entry_price"]) * pos["shares"]
                unrealised_pct = (
                    (current - pos["entry_price"]) / pos["entry_price"] * 100.0
                )
            else:
                unrealised_pnl = float("nan")
                unrealised_pct = float("nan")

            rows.append(
                {
                    "Symbol": symbol,
                    "Source": pos["source"],
                    "Strategy": pos["strategy"],
                    "Entry Price": pos["entry_price"],
                    "Current Price": current,
                    "Shares": pos["shares"],
                    "Unrealised PnL ($)": unrealised_pnl,
                    "Unrealised PnL (%)": unrealised_pct,
                    "Entry Date": pos["entry_date"][:19].replace("T", " "),
                }
            )

        positions_df = pd.DataFrame(rows)
        st.dataframe(
            positions_df.style.format(
                {
                    "Entry Price": "{:.4f}",
                    "Current Price": "{:.4f}",
                    "Shares": "{:.6f}",
                    "Unrealised PnL ($)": "{:+.2f}",
                    "Unrealised PnL (%)": "{:+.2f}%",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ------------------------------------------------------------------
    # 4. Closed trades table
    # ------------------------------------------------------------------
    st.subheader("Trade History")
    if not trades:
        st.info("No closed trades yet.")
    else:
        trade_rows: list[dict[str, Any]] = [
            {
                "Symbol": t["symbol"],
                "Source": t["source"],
                "Strategy": t["strategy"],
                "Entry Price": t["entry_price"],
                "Exit Price": t["exit_price"],
                "Shares": t["shares"],
                "PnL ($)": t["pnl"],
                "PnL (%)": t["pnl_pct"],
                "Entry Date": t["entry_date"][:19].replace("T", " "),
                "Exit Date": t["exit_date"][:19].replace("T", " "),
            }
            for t in trades
        ]
        trades_df = pd.DataFrame(trade_rows)
        st.dataframe(
            trades_df.style.format(
                {
                    "Entry Price": "{:.4f}",
                    "Exit Price": "{:.4f}",
                    "Shares": "{:.6f}",
                    "PnL ($)": "{:+.2f}",
                    "PnL (%)": "{:+.2f}%",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ------------------------------------------------------------------
    # 5. Equity curve
    # ------------------------------------------------------------------
    st.subheader("Equity Curve")
    curve = _build_equity_curve(trades, initial_capital)
    if curve.empty:
        st.info("No trade history available to plot.")
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=curve["date"],
                y=curve["equity"],
                mode="lines+markers",
                name="Equity",
                line={"color": "#00b09b", "width": 2},
                marker={"size": 5},
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Equity: $%{y:,.2f}<extra></extra>",
            )
        )
        # Baseline reference
        fig.add_hline(
            y=initial_capital,
            line_dash="dot",
            line_color="grey",
            annotation_text=f"Initial capital ${initial_capital:,.0f}",
            annotation_position="bottom right",
        )
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Portfolio Value ($)",
            template="plotly_dark",
            height=400,
            margin={"l": 40, "r": 20, "t": 20, "b": 40},
        )
        st.plotly_chart(fig, use_container_width=True)
