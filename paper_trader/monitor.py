"""
paper_trader.monitor
====================
Multi-bot paper trading Streamlit page.

Layout
------
1. Summary table — one row per bot showing equity, total-return %, open
   positions, closed trades, and win rate.  Rows are coloured green/red
   depending on whether total return is positive.
2. Bot selector — ``st.selectbox`` to choose one bot for a detailed view.
3. Detailed view for the selected bot:
   - Four KPI metric tiles (equity, cash, total return %, open positions).
   - Open positions table with SL/TP price columns.
   - Closed trades table with the exit ``reason`` column.
   - Equity curve built from cumulative PnL in the trade history.

Imported by ``trd_auto/app.py`` as a navigation page::

    st.Page(paper_trading_page, title="Paper Trading")
"""

from __future__ import annotations

import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_TRDAUTO = os.path.join(_PROJECT_ROOT, "trd_auto")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _TRDAUTO not in sys.path:
    sys.path.insert(0, _TRDAUTO)

# ---------------------------------------------------------------------------
# paper_trader imports
# ---------------------------------------------------------------------------
from paper_trader.bots import BOTS, BotConfig  # noqa: E402
from paper_trader.db import (  # noqa: E402
    get_all_portfolios,
    get_open_positions,
    get_portfolio,
    get_trade_history,
    init_db,
)

# ---------------------------------------------------------------------------
# trd_auto connector imports (path bootstrap adds _TRDAUTO to sys.path above)
# ---------------------------------------------------------------------------
import math  # noqa: E402

from data.connectors.coingecko import CoinGeckoConnector  # noqa: E402
from data.connectors.yahoo_finance import YahooFinanceConnector  # noqa: E402

# ---------------------------------------------------------------------------
# Streamlit import (only safe inside the Streamlit process)
# ---------------------------------------------------------------------------
import streamlit as st  # noqa: E402
import pandas as pd  # noqa: E402

from config.tooltips import BOT_TOOLTIPS, METRIC_TOOLTIPS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _colour_return(val: float) -> str:
    """Return a CSS colour string for a return percentage value."""
    return "color: #26a69a" if val > 0 else "color: #ef5350" if val < 0 else ""


def _summary_df(all_portfolios: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the all-bots summary DataFrame."""
    rows = []
    for row in all_portfolios:
        bot_id: str = row["bot_id"]
        cfg: BotConfig = BOTS.get(bot_id, None)  # type: ignore[assignment]
        initial: float = row["initial_capital"]
        equity: float = row["current_capital"]
        total_ret_pct: float = (equity - initial) / initial * 100 if initial else 0.0
        rows.append(
            {
                "Bot": cfg.name if cfg else bot_id,
                "Strategy": cfg.description if cfg else "",
                "Equity ($)": equity,
                "Total Return (%)": total_ret_pct,
                "Open Positions": row["num_open_positions"],
                "Closed Trades": row["num_closed_trades"],
                "Win Rate (%)": row["win_rate"],
            }
        )
    return pd.DataFrame(rows)


def _open_positions_df(bot_id: str, cfg: BotConfig) -> pd.DataFrame:
    """Return open positions for ``bot_id`` with SL/TP price columns."""
    positions = get_open_positions(bot_id)
    if not positions:
        return pd.DataFrame()

    rows = []
    for pos in positions:
        entry: float = pos["entry_price"]
        sl_price: float = entry * (1 - cfg.stop_loss_pct)
        tp_price: float = entry * (1 + cfg.take_profit_pct)
        rows.append(
            {
                "Symbol": pos["symbol"],
                "Strategy": pos["strategy"],
                "Entry Price": entry,
                "Shares": pos["shares"],
                "Stop Loss ($)": sl_price,
                "Take Profit ($)": tp_price,
                "Entry Date": pos["entry_date"],
            }
        )
    return pd.DataFrame(rows)


def _trades_df(bot_id: str) -> pd.DataFrame:
    """Return closed trades for ``bot_id`` in a presentable form."""
    trades = get_trade_history(bot_id)
    if not trades:
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    cols = [
        "symbol", "strategy", "entry_price", "exit_price", "shares",
        "pnl", "pnl_pct", "reason", "entry_date", "exit_date",
    ]
    df = df[[c for c in cols if c in df.columns]]
    df = df.rename(
        columns={
            "symbol": "Symbol", "strategy": "Strategy",
            "entry_price": "Entry ($)", "exit_price": "Exit ($)",
            "shares": "Shares", "pnl": "PnL ($)", "pnl_pct": "PnL (%)",
            "reason": "Reason", "entry_date": "Entry Date", "exit_date": "Exit Date",
        }
    )
    return df


_CONNECTOR_REGISTRY: dict[str, Any] = {
    "yahoo": YahooFinanceConnector,
    "coingecko": CoinGeckoConnector,
}


def _fetch_current_prices(positions: list[dict[str, Any]]) -> dict[str, float]:
    """Fetch the latest market price for each open position.

    Deduplicates by symbol so each connector is called at most once per symbol.
    Falls back to ``entry_price`` for any symbol whose price cannot be retrieved.
    """
    prices: dict[str, float] = {}
    for pos in positions:
        symbol: str = pos["symbol"]
        if symbol in prices:
            continue
        source: str = pos["source"]
        try:
            connector = _CONNECTOR_REGISTRY[source]()
            quote = connector.get_quote(symbol)
            price = float(quote.get("price", float("nan")))
            prices[symbol] = price if not math.isnan(price) else pos["entry_price"]
        except Exception:
            prices[symbol] = pos["entry_price"]
    return prices


def _equity_curve(
    bot_id: str,
    initial_capital: float,
    current_equity: float | None = None,
) -> pd.DataFrame | None:
    """Return a cumulative-PnL DataFrame for the equity curve, or ``None`` if empty.

    If ``current_equity`` is provided, a final data point at the current UTC
    timestamp is appended so the curve reflects unrealized PnL from open positions.
    """
    trades = get_trade_history(bot_id)
    if trades:
        df = pd.DataFrame(trades)
        if "pnl" not in df.columns or "exit_date" not in df.columns:
            return None
        df = df.sort_values("exit_date").reset_index(drop=True)
        df["Equity ($)"] = initial_capital + df["pnl"].cumsum()
        df["Date"] = pd.to_datetime(df["exit_date"], utc=True)
        curve = df[["Date", "Equity ($)"]].copy()
    else:
        curve = pd.DataFrame(columns=["Date", "Equity ($)"])

    if current_equity is not None:
        now_row = pd.DataFrame(
            [{"Date": pd.Timestamp.now(tz="UTC"), "Equity ($)": current_equity}]
        )
        curve = pd.concat([curve, now_row], ignore_index=True)

    return curve if not curve.empty else None


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def paper_trading_page() -> None:
    """Streamlit page function — registered in ``trd_auto/app.py`` navigation."""
    # Ensure DB and portfolio rows exist.
    init_db(BOTS)

    st.subheader("Paper Trading")
    st.caption("Autonomous bots — signal cycle every 4 hours.")

    # ------------------------------------------------------------------
    # 1. Summary table
    # ------------------------------------------------------------------
    st.caption("All Bots")
    all_portfolios = get_all_portfolios()

    if not all_portfolios:
        st.info("No portfolio data yet.  The engine has not run its first cycle.")
        return

    summary = _summary_df(all_portfolios)

    def _row_style(row: pd.Series) -> list[str]:
        ret = row.get("Total Return (%)", 0.0)
        colour = "color: #26a69a" if ret > 0 else "color: #ef5350" if ret < 0 else ""
        return [colour] * len(row)

    st.dataframe(
        summary.style.apply(_row_style, axis=1).format(
            {
                "Equity ($)": "{:,.2f}",
                "Total Return (%)": "{:+.2f}%",
                "Win Rate (%)": "{:.1f}%",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Equity includes unrealized PnL from open positions at last fetched price.")

    st.divider()

    # ------------------------------------------------------------------
    # 2. Bot selector
    # ------------------------------------------------------------------
    bot_options = [cfg.name for cfg in BOTS.values()]
    bot_ids = list(BOTS.keys())
    selected_name = st.selectbox("Bot", bot_options)
    selected_bot_id = bot_ids[bot_options.index(selected_name)]
    selected_cfg = BOTS[selected_bot_id]
    st.caption(BOT_TOOLTIPS.get(selected_bot_id, ""))

    portfolio_row = get_portfolio(selected_bot_id) or {}
    initial_cap: float = portfolio_row.get("initial_capital", selected_cfg.initial_capital)
    current_cap: float = portfolio_row.get("current_capital", initial_cap)
    open_positions = get_open_positions(selected_bot_id)
    open_pos_count = len(open_positions)

    # Fetch live prices and compute mark-to-market equity.
    with st.spinner("Fetching live prices…"):
        live_prices = _fetch_current_prices(open_positions) if open_positions else {}
    mtm: float = sum(
        live_prices.get(p["symbol"], p["entry_price"]) * p["shares"]
        for p in open_positions
    )
    equity: float = current_cap + mtm
    total_ret: float = (equity - initial_cap) / initial_cap * 100 if initial_cap else 0.0

    # ------------------------------------------------------------------
    # 3. Detailed view
    # ------------------------------------------------------------------
    st.subheader(f"{selected_cfg.name}  —  {selected_cfg.description}")

    # KPI tiles
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Equity", f"${equity:,.2f}",
                help=METRIC_TOOLTIPS.get("Equity", ""))
    col2.metric("Cash", f"${current_cap:,.2f}",
                help=METRIC_TOOLTIPS.get("Cash", ""))
    col3.metric(
        "Total Return",
        f"{total_ret:+.2f}%",
        delta_color="normal",
        help=METRIC_TOOLTIPS.get("Total Return", ""),
    )
    col4.metric("Open Positions", str(open_pos_count),
                help=METRIC_TOOLTIPS.get("Open Positions", ""))

    st.caption(
        f"Timeframe: **{selected_cfg.timeframe}**  |  "
        f"Strategies: **{', '.join(selected_cfg.strategy_filter)}**  |  "
        f"Confluence threshold: **{selected_cfg.min_confluence}**  |  "
        f"SL: **{selected_cfg.stop_loss_pct*100:.0f}%**  |  "
        f"TP: **{selected_cfg.take_profit_pct*100:.0f}%**"
    )

    st.divider()

    # Open positions
    st.caption("Open Positions")
    open_df = _open_positions_df(selected_bot_id, selected_cfg)
    if open_df.empty:
        st.info("No open positions.")
    else:
        st.dataframe(
            open_df.style.format(
                {
                    "Entry Price": "{:.4f}",
                    "Shares": "{:.6f}",
                    "Stop Loss ($)": "{:.4f}",
                    "Take Profit ($)": "{:.4f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    # Closed trades
    st.caption("Trade History")
    trades_df = _trades_df(selected_bot_id)
    if trades_df.empty:
        st.info("No closed trades yet.")
    else:

        def _pnl_colour(row: pd.Series) -> list[str]:
            val = row.get("PnL ($)", 0.0)
            colour = "color: #26a69a" if val > 0 else "color: #ef5350" if val < 0 else ""
            return [colour] * len(row)

        fmt: dict[str, str] = {}
        if "Entry ($)" in trades_df.columns:
            fmt["Entry ($)"] = "{:.4f}"
        if "Exit ($)" in trades_df.columns:
            fmt["Exit ($)"] = "{:.4f}"
        if "PnL ($)" in trades_df.columns:
            fmt["PnL ($)"] = "{:+.2f}"
        if "PnL (%)" in trades_df.columns:
            fmt["PnL (%)"] = "{:+.2f}%"

        st.dataframe(
            trades_df.style.apply(_pnl_colour, axis=1).format(fmt),
            use_container_width=True,
            hide_index=True,
        )

    # Equity curve
    st.caption("Equity Curve")
    curve = _equity_curve(selected_bot_id, initial_cap, current_equity=equity)
    if curve is None or curve.empty:
        st.info("Not enough trade history to draw an equity curve.")
    else:
        st.line_chart(curve.set_index("Date"))

