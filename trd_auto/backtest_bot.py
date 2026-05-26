"""
backtest_bot.py — Bot Walk-Forward Simulation page.

Renders a walk-forward simulation for any configured bot,
covering the period 2025-01-01 to today using historical OHLCV data.
No DB reads or writes.  Registered as a page in app.py.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_TRDAUTO_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TRDAUTO_DIR)
for _p in (_PROJECT_ROOT, _TRDAUTO_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from paper_trader.bots import BOTS, get_assets_for_bot  # noqa: E402
from config.tooltips import BOT_TOOLTIPS, METRIC_TOOLTIPS  # noqa: E402
from simulation import (  # noqa: E402
    SimulationResult,
    fetch_simulation_data,
    run_simulation,
)

START_DATE = date.today() - timedelta(days=364)

# ---------------------------------------------------------------------------
# Dark-theme constants (mirrored from charts/)
# ---------------------------------------------------------------------------
_BG       = "#0e1117"
_GRID     = "#1e2130"
_TEXT     = "#fafafa"
_COLOR_UP = "#26a69a"
_COLOR_DN = "#ef5350"


# ---------------------------------------------------------------------------
# Cached OHLCV fetch — keyed on bot_id, TTL 1 hour
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_fetch(bot_id: str) -> dict[str, pd.DataFrame]:
    return fetch_simulation_data(BOTS[bot_id])


# ---------------------------------------------------------------------------
# Buy & Hold baseline
# ---------------------------------------------------------------------------

def _compute_buyhold(
    all_data: dict[str, pd.DataFrame],
    initial_capital: float,
    simulation_dates: pd.DatetimeIndex,
) -> pd.Series:
    """
    Equal-weighted buy & hold across all assets in all_data.
    Each asset receives initial_capital / n_assets at the first
    available price on or after 2025-01-01.
    """
    if not all_data or simulation_dates.empty:
        return pd.Series(initial_capital, index=simulation_dates)

    per_asset = initial_capital / len(all_data)
    sim_start = pd.Timestamp(START_DATE, tz="UTC")
    total = pd.Series(0.0, index=simulation_dates)

    for df in all_data.values():
        available = df.loc[df.index >= sim_start, "close"]
        if available.empty:
            continue
        initial_price = float(available.iloc[0])
        if initial_price <= 0.0:
            continue
        shares = per_asset / initial_price
        # Forward-fill prices to every business day in the simulation window
        reindexed = df["close"].reindex(simulation_dates, method="ffill")
        total += (shares * reindexed).fillna(0.0)

    return total


# ---------------------------------------------------------------------------
# Equity curve chart
# ---------------------------------------------------------------------------

def _render_equity_curve(
    result: SimulationResult,
    bh_series: pd.Series,
) -> None:
    dates = [s["date"] for s in result.snapshots]
    equity = [s["equity"] for s in result.snapshots]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=equity,
        name="Bot Strategy",
        line=dict(color=_COLOR_UP, width=2),
    ))
    fig.add_trace(go.Scatter(
        x=bh_series.index,
        y=bh_series.values,
        name="Buy & Hold (equal-weight)",
        line=dict(color="#90a4ae", width=1.5, dash="dot"),
    ))
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
        xaxis=dict(showgrid=True, gridcolor=_GRID, linecolor=_GRID, color=_TEXT),
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


# ---------------------------------------------------------------------------
# Performance metrics (6 tiles)
# ---------------------------------------------------------------------------

def _sharpe(equity_series: pd.Series) -> float:
    ret = equity_series.pct_change().dropna()
    if len(ret) < 2 or ret.std() == 0.0:
        return 0.0
    return float(ret.mean() / ret.std() * (252 ** 0.5))


def _max_drawdown(equity_series: pd.Series) -> float:
    roll_max = equity_series.cummax()
    dd = (equity_series - roll_max) / roll_max * 100.0
    return float(dd.min())


def _render_performance(
    result: SimulationResult,
    bh_series: pd.Series,
) -> None:
    equity_series = pd.Series(
        [s["equity"] for s in result.snapshots],
        index=pd.DatetimeIndex([s["date"] for s in result.snapshots]),
    )

    total_ret = (result.final_equity - result.initial_capital) / result.initial_capital * 100.0
    bh_start = float(bh_series.iloc[0]) if not bh_series.empty else result.initial_capital
    bh_end = float(bh_series.iloc[-1]) if not bh_series.empty else result.initial_capital
    bh_ret = (bh_end - bh_start) / bh_start * 100.0 if bh_start > 0.0 else 0.0

    n_trades = len(result.trades)
    wins = sum(1 for t in result.trades if t.pnl > 0.0)
    win_rate = wins / n_trades * 100.0 if n_trades > 0 else 0.0
    max_dd = _max_drawdown(equity_series)
    sharpe = _sharpe(equity_series)

    metrics = [
        ("Total Return (%)", f"{total_ret:.2f}%",    "Total Return Backtest"),
        ("Buy & Hold (%)",   f"{bh_ret:.2f}%",       "Buy & Hold"),
        ("Trades",           str(n_trades),           "Trades"),
        ("Win Rate (%)",     f"{win_rate:.1f}%",      "Win Rate"),
        ("Max Drawdown (%)", f"{max_dd:.2f}%",        "Max Drawdown"),
        ("Sharpe Ratio",     f"{sharpe:.2f}",         "Sharpe Ratio"),
    ]
    cols = st.columns(6)
    for col, (label, value, tip_key) in zip(cols, metrics):
        with col:
            st.metric(label, value, help=METRIC_TOOLTIPS.get(tip_key, ""))


# ---------------------------------------------------------------------------
# Date inspector
# ---------------------------------------------------------------------------

def _render_date_inspector(result: SimulationResult) -> None:
    if not result.snapshots:
        return

    selected_date = st.select_slider(
        "Inspect date",
        options=[s["date"] for s in result.snapshots],
        value=result.snapshots[-1]["date"],
        format_func=lambda d: d.strftime("%Y-%m-%d"),
    )

    snap = next(
        (s for s in result.snapshots if s["date"] == selected_date),
        result.snapshots[-1],
    )

    cols = st.columns(3)
    with cols[0]:
        st.metric("Equity", f"${snap['equity']:,.2f}",
                  help=METRIC_TOOLTIPS.get("Equity", ""))
    with cols[1]:
        st.metric("Cash", f"${snap['cash']:,.2f}",
                  help=METRIC_TOOLTIPS.get("Cash", ""))
    with cols[2]:
        st.metric("Open Positions", snap["open_positions"],
                  help=METRIC_TOOLTIPS.get("Open Positions", ""))

    # Reconstruct which positions were open at the selected date
    open_at: list[dict] = []
    for trade in result.trades:
        if trade.entry_date <= selected_date < trade.exit_date:
            open_at.append({
                "Symbol":     trade.symbol,
                "Entry Date": trade.entry_date.strftime("%Y-%m-%d"),
                "Entry ($)":  round(trade.entry_price, 4),
                "Shares":     round(trade.shares, 4),
            })
    for pos in result.open_at_end:
        if pos.entry_date <= selected_date:
            open_at.append({
                "Symbol":     pos.symbol,
                "Entry Date": pos.entry_date.strftime("%Y-%m-%d"),
                "Entry ($)":  round(pos.entry_price, 4),
                "Shares":     round(pos.shares, 4),
            })

    if open_at:
        st.dataframe(pd.DataFrame(open_at), use_container_width=True, hide_index=True)
    else:
        st.caption("No positions open on this date.")


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------

def _render_trade_log(result: SimulationResult) -> None:
    if not result.trades:
        st.caption("No completed trades.")
        return

    rows = [
        {
            "Symbol":     t.symbol,
            "Entry Date": t.entry_date.strftime("%Y-%m-%d"),
            "Exit Date":  t.exit_date.strftime("%Y-%m-%d"),
            "Entry ($)":  round(t.entry_price, 4),
            "Exit ($)":   round(t.exit_price, 4),
            "Shares":     round(t.shares, 4),
            "PnL ($)":    round(t.pnl, 2),
            "PnL (%)":    round(t.pnl_pct, 2),
            "Reason":     t.reason,
        }
        for t in result.trades
    ]
    df_trades = pd.DataFrame(rows)

    def _row_style(row: pd.Series) -> list[str]:
        color = (
            "rgba(38,166,154,0.15)" if row["PnL ($)"] > 0
            else "rgba(239,83,80,0.15)"
        )
        return [f"background-color: {color}"] * len(row)

    styled = df_trades.style.apply(_row_style, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Walk Forward Analysis
# ---------------------------------------------------------------------------

def _render_walk_forward(result: SimulationResult) -> None:
    """Permanent walk-forward section: split snapshots 70/30, compare IS vs OOS."""
    snaps = result.snapshots
    n = len(snaps)
    split_idx = int(n * 0.70)
    oos_count = n - split_idx

    if oos_count < 15:
        st.caption("Not enough data \u2014 use 3M or 1Y")
        return

    # ---- equity series ----
    all_dates   = [s["date"]   for s in snaps]
    all_equity  = [s["equity"] for s in snaps]

    snaps_is  = snaps[:split_idx]
    snaps_oos = snaps[split_idx:]

    dates_is   = [s["date"]   for s in snaps_is]
    equity_is  = [s["equity"] for s in snaps_is]
    dates_oos  = [s["date"]   for s in snaps_oos]
    equity_oos = [s["equity"] for s in snaps_oos]

    split_date = snaps_oos[0]["date"]

    # ---- Sharpe ratios ----
    ser_is  = pd.Series(equity_is,  index=pd.DatetimeIndex(dates_is))
    ser_oos = pd.Series(equity_oos, index=pd.DatetimeIndex(dates_oos))
    sharpe_is  = _sharpe(ser_is)
    sharpe_oos = _sharpe(ser_oos)

    # ---- 3-trace chart ----
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=all_dates, y=all_equity,
        name="Full Period",
        line=dict(color="#90a4ae", width=1.5, dash="dash"),
        opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=dates_is, y=equity_is,
        name="In-Sample (70%)",
        line=dict(color="#7986cb", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=dates_oos, y=equity_oos,
        name="Out-of-Sample (30%)",
        line=dict(color=_COLOR_UP, width=2),
    ))

    split_str = str(split_date)
    fig.add_shape(
        type="line",
        x0=split_str, x1=split_str,
        y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(color=_COLOR_DN, width=2, dash="dash"),
    )
    fig.add_annotation(
        x=split_str,
        y=1,
        xref="x", yref="paper",
        text="Split 70%",
        showarrow=False,
        font=dict(color=_COLOR_DN),
        yanchor="bottom",
    )

    fig.update_layout(
        height=380,
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
        xaxis=dict(showgrid=True, gridcolor=_GRID, linecolor=_GRID, color=_TEXT),
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

    # ---- Sharpe metrics ----
    col_is, col_oos = st.columns(2)
    with col_is:
        st.metric("Sharpe \u2014 In-Sample (70%)", f"{sharpe_is:.2f}")
    with col_oos:
        st.metric("Sharpe \u2014 Out-of-Sample (30%)", f"{sharpe_oos:.2f}")

    # ---- diagnostic ----
    if sharpe_is <= 0:
        st.error(
            f"In-sample Sharpe ({sharpe_is:.2f}) \u2264 0 \u2014 "
            "strategy is not profitable in-sample."
        )
    elif sharpe_oos >= 0.75 * sharpe_is:
        st.success(
            f"OOS Sharpe ({sharpe_oos:.2f}) \u2265 75\u202f% of IS Sharpe ({sharpe_is:.2f}) \u2014 "
            "strategy appears robust out-of-sample."
        )
    elif sharpe_oos >= 0.50 * sharpe_is:
        st.warning(
            f"OOS Sharpe ({sharpe_oos:.2f}) is between 50\u202f% and 75\u202f% of IS Sharpe "
            f"({sharpe_is:.2f}) \u2014 moderate degradation out-of-sample."
        )
    else:
        st.error(
            f"OOS Sharpe ({sharpe_oos:.2f}) is below 50\u202f% of IS Sharpe ({sharpe_is:.2f}) \u2014 "
            "significant out-of-sample degradation."
        )


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------

def backtest_bot_page() -> None:
    """Streamlit page: walk-forward bot simulation."""

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    with st.sidebar:
        st.markdown("### Bot Simulation")
        st.caption("Walk-forward — 2025-01-01 to today")
        st.divider()
        st.caption("Bot")
        bot_id: str = st.selectbox(
            "Bot",
            options=list(BOTS.keys()),
            format_func=lambda k: BOTS[k].name,
            label_visibility="collapsed",
            key="sim_bot_id",
        )
        bot_cfg = BOTS[bot_id]
        st.caption(BOT_TOOLTIPS.get(bot_id, ""))
        st.divider()
        st.caption("Initial Capital")
        capital: float = st.number_input(
            "Initial Capital",
            min_value=100.0,
            max_value=10_000_000.0,
            value=float(bot_cfg.initial_capital),
            step=1000.0,
            format="%.0f",
            label_visibility="collapsed",
            key="sim_capital",
        )
        st.divider()
        run_clicked = st.button(
            "Run Simulation",
            use_container_width=True,
            type="primary",
        )

    # ------------------------------------------------------------------
    # Page header
    # ------------------------------------------------------------------
    st.subheader("Bot Simulation")
    n_assets = len(get_assets_for_bot(bot_cfg))
    st.caption(
        f"{bot_cfg.name}  ·  {bot_cfg.asset_universe}  ·  "
        f"{n_assets} asset{'s' if n_assets != 1 else ''}  ·  "
        f"cycle {bot_cfg.cycle_hours}h"
    )

    # ------------------------------------------------------------------
    # Cache key: invalidate when bot or capital changes
    # ------------------------------------------------------------------
    cache_key = f"_sim_result_{bot_id}_{int(capital)}"

    # Override initial_capital with the user-selected value
    sim_cfg = dataclasses.replace(bot_cfg, initial_capital=capital)

    if run_clicked or cache_key not in st.session_state:
        with st.spinner("Loading historical data..."):
            all_data = _cached_fetch(bot_id)

        if not all_data:
            st.error("No historical data could be fetched for this bot's assets.")
            return

        with st.spinner("Running simulation..."):
            result = run_simulation(sim_cfg, all_data)

        st.session_state[cache_key] = (result, all_data)
    else:
        result, all_data = st.session_state[cache_key]

    if not result.snapshots:
        st.warning("Simulation returned no results. The asset universe may have insufficient data.")
        return

    # ------------------------------------------------------------------
    # Pre-compute buy & hold (used by both curve and metrics)
    # ------------------------------------------------------------------
    sim_dates = pd.DatetimeIndex([s["date"] for s in result.snapshots])
    bh_series = _compute_buyhold(all_data, result.initial_capital, sim_dates)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    st.caption("Equity Curve")
    _render_equity_curve(result, bh_series)

    st.caption("Performance Metrics")
    _render_performance(result, bh_series)

    st.divider()
    st.caption("Walk Forward Analysis")
    _render_walk_forward(result)

    st.divider()
    st.caption("Inspect Date")
    _render_date_inspector(result)

    st.divider()
    st.caption("Trade Log")
    _render_trade_log(result)
