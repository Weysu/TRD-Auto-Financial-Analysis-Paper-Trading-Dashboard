"""
trd_auto.simulation
===================
Walk-forward bot simulation engine.

No DB reads or writes.  No Streamlit imports.
Sentiment score is always 0 — no historical news data is available.
"""
from __future__ import annotations

import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Path bootstrap — ensure paper_trader is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
for _p in (_PROJECT_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from paper_trader.bots import BotConfig, get_assets_for_bot  # noqa: E402
from paper_trader.executor import _compute_confluence  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# First date that the simulation loop will act on.
# Computed dynamically so the window never exceeds the CoinGecko 365-day limit.
START_DATE = date.today() - timedelta(days=364)
_SIM_START = pd.Timestamp(START_DATE, tz="UTC")

# Fetch data from earlier so there are 200+ daily bars before _SIM_START
# (required for SMA200 filter and for the slowest rolling indicators).
# yfinance has no day-count limit on free use, so we can go back 2 years.
_YFINANCE_FETCH_START: str = (date.today() - timedelta(days=729)).strftime("%Y-%m-%d")

# CoinGecko free tier: max 365 days via the market_chart/range endpoint.
# Use the same rolling window as START_DATE so the API call never exceeds the limit.
_FETCH_START: str = (date.today() - timedelta(days=364)).strftime("%Y-%m-%d")

# Minimum bars in a slice before confluence can be computed.
_MIN_BARS: int = 60


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SimPosition:
    symbol: str
    entry_price: float
    shares: float
    entry_date: pd.Timestamp
    strategy: str
    highest_price: float = 0.0       # highest close seen while position is open
    tps_hit: int = 0                  # number of TP levels already triggered
    stop_loss_price: float = 0.0      # dynamic SL — moved to BE/TP price as ladder runs
    trailing_active: bool = False     # True once the last TP level is hit


@dataclass
class SimTrade:
    symbol: str
    entry_price: float
    exit_price: float
    shares: float
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class SimulationResult:
    bot_id: str
    snapshots: list[dict]           # one per business day: {date, equity, cash, open_positions}
    trades: list[SimTrade]          # all closed round-trip trades
    open_at_end: list[SimPosition]  # positions still open when simulation ends
    initial_capital: float
    final_equity: float


# ---------------------------------------------------------------------------
# Data fetching  (direct calls — bypasses the period-label connector system)
# ---------------------------------------------------------------------------

def _fetch_yahoo(symbol: str, interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV from Yahoo Finance.

    For interval="1d" (default) fetches from _YFINANCE_FETCH_START to today.
    For any other interval (e.g. "1h") uses period="730d" so yfinance
    determines the window automatically.
    Returns a DataFrame with UTC DatetimeIndex and columns
    open / high / low / close / volume.  Returns empty DataFrame on failure.
    """
    try:
        _kwargs: dict = {"auto_adjust": True, "actions": False}
        if interval == "1d":
            _kwargs["start"] = _YFINANCE_FETCH_START
        else:
            _kwargs["period"] = "730d"
            _kwargs["interval"] = interval
        raw: pd.DataFrame = yf.Ticker(symbol).history(**_kwargs)
        if raw.empty:
            return pd.DataFrame()
        df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df.index.name = "timestamp"
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype("float64")
        return df.sort_index()
    except Exception as exc:
        logger.warning("_fetch_yahoo(%s): %s", symbol, exc)
        return pd.DataFrame()


def _fetch_coingecko(coin_id: str) -> pd.DataFrame:
    """
    Fetch daily OHLCV from CoinGecko for the simulation window.
    Uses the market_chart/range endpoint; free tier returns daily
    granularity for ranges > 90 days.
    Returns a DataFrame with UTC DatetimeIndex.  Returns empty on failure.
    """
    try:
        from pycoingecko import CoinGeckoAPI  # noqa: PLC0415
        cg = CoinGeckoAPI()
        from_ts = int(pd.Timestamp(_FETCH_START, tz="UTC").timestamp())
        to_ts = int(pd.Timestamp.now(tz="UTC").timestamp())
        data = cg.get_coin_market_chart_range_by_id(
            coin_id, "usd", str(from_ts), str(to_ts)
        )
        prices = data.get("prices", [])
        volumes = data.get("total_volumes", [])
        if not prices:
            return pd.DataFrame()

        price_df = pd.DataFrame(prices, columns=["ts_ms", "close"])
        price_df["open"] = price_df["close"]
        price_df["high"] = price_df["close"]
        price_df["low"] = price_df["close"]
        vol_df = pd.DataFrame(volumes, columns=["ts_ms", "volume"])
        merged = pd.merge_asof(
            price_df.sort_values("ts_ms"),
            vol_df.sort_values("ts_ms"),
            on="ts_ms",
            direction="nearest",
        )
        merged.index = pd.to_datetime(merged["ts_ms"], unit="ms", utc=True)
        merged.index.name = "timestamp"
        for col in ["open", "high", "low", "close", "volume"]:
            merged[col] = merged[col].astype("float64")
        # Resample to daily (free tier may return sub-daily bars for short ranges)
        daily = (
            merged[["open", "high", "low", "close", "volume"]]
            .resample("1D")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )
        return daily.sort_index()
    except Exception as exc:
        logger.warning("_fetch_coingecko(%s): %s", coin_id, exc)
        return pd.DataFrame()


def fetch_simulation_data(
    bot_cfg: BotConfig,
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Fetch full OHLCV history for every asset in the bot's universe.

    Parameters
    ----------
    bot_cfg:
        Bot configuration used to resolve the asset universe.
    interval:
        yfinance interval string (e.g. ``"1d"`` or ``"1h"``).  Only
        applied to Yahoo Finance assets; CoinGecko assets always use
        daily granularity.

    Returns a dict keyed by asset display label (same keys as
    ``get_assets_for_bot``).  Assets that fail to fetch are silently
    omitted.  No network calls happen after this function returns.
    """
    assets = get_assets_for_bot(bot_cfg)
    all_data: dict[str, pd.DataFrame] = {}
    for label, asset_cfg in assets.items():
        source = asset_cfg["source"]
        symbol = asset_cfg["id"]
        if source == "yahoo":
            df = _fetch_yahoo(symbol, interval)
        elif source == "coingecko":
            df = _fetch_coingecko(symbol)
        else:
            logger.warning("Unknown source %r for %s — skipping.", source, label)
            continue
        if not df.empty:
            all_data[label] = df
        else:
            logger.warning("No data for %s (%s / %s) — skipping.", label, source, symbol)
    return all_data


# ---------------------------------------------------------------------------
# Walk-forward simulation
# ---------------------------------------------------------------------------

def run_simulation(
    bot_cfg: BotConfig,
    all_data: dict[str, pd.DataFrame],
    fractional: bool = False,
) -> SimulationResult:
    """
    Walk-forward simulation from 2025-01-01 to today.

    The bot only ever sees OHLCV data up to the current simulation date,
    replicating realistic conditions.  No network calls are made here.
    Sentiment is always 0 (no historical sentiment data available).

    Parameters
    ----------
    bot_cfg:
        Bot configuration — thresholds, strategy filter, risk params.
    all_data:
        Pre-fetched OHLCV dict from ``fetch_simulation_data``.  Must have
        UTC DatetimeIndex and columns open / high / low / close / volume.
    """
    from data.filters import is_uptrend_sma200      # noqa: PLC0415
    from data.indicators import compute_indicators  # noqa: PLC0415

    cash: float = bot_cfg.initial_capital
    open_positions: dict[str, SimPosition] = {}
    closed_trades: list[SimTrade] = []
    snapshots: list[dict] = []

    # Pre-compute technical indicators on the full history for each asset.
    # Rolling operations are causal (bar i depends only on bars 0..i), so
    # slicing the result for any date D gives the correct indicator values
    # without lookahead bias.
    prepared: dict[str, pd.DataFrame] = {}
    for label, df in all_data.items():
        df_col = df.reset_index()        # timestamp → regular column
        df_col = compute_indicators(df_col)
        df_col = df_col.set_index("timestamp").sort_index()
        prepared[label] = df_col

    today_utc = pd.Timestamp.now(tz="UTC").normalize()
    simulation_dates = pd.date_range(_SIM_START, today_utc, freq="B", tz="UTC")

    # ---- helpers ----

    def _close(
        label: str,
        pos: SimPosition,
        price: float,
        date: pd.Timestamp,
        reason: str,
    ) -> None:
        nonlocal cash
        cost = pos.shares * pos.entry_price
        proceeds = pos.shares * price
        pnl = proceeds - cost
        closed_trades.append(SimTrade(
            symbol=label,
            entry_price=pos.entry_price,
            exit_price=price,
            shares=pos.shares,
            entry_date=pos.entry_date,
            exit_date=date,
            pnl=pnl,
            pnl_pct=pnl / cost * 100.0,
            reason=reason,
        ))
        cash += proceeds
        del open_positions[label]

    def _partial_close(
        label: str,
        pos: SimPosition,
        close_shares: float,
        price: float,
        date: pd.Timestamp,
        reason: str,
    ) -> None:
        """Close *close_shares* of an open position and record a partial trade."""
        nonlocal cash
        cost: float = close_shares * pos.entry_price
        proceeds: float = close_shares * price
        pnl: float = proceeds - cost
        closed_trades.append(SimTrade(
            symbol=label,
            entry_price=pos.entry_price,
            exit_price=price,
            shares=close_shares,
            entry_date=pos.entry_date,
            exit_date=date,
            pnl=pnl,
            pnl_pct=pnl / cost * 100.0 if cost > 0.0 else 0.0,
            reason=reason,
        ))
        cash += proceeds
        pos.shares -= close_shares
        if pos.shares <= 1e-8:  # effectively zero — close position fully
            del open_positions[label]

    # ---- main loop ----

    for current_date in simulation_dates:
        for label, full_df in prepared.items():
            df = full_df[full_df.index <= current_date]
            if len(df) < _MIN_BARS:
                continue

            # Trend filter — applied before all actions (including exits)
            if bot_cfg.use_trend_filter and not is_uptrend_sma200(df):
                continue

            score, _ = _compute_confluence(df, list(bot_cfg.strategy_filter))
            current_price = float(df["close"].iloc[-1])

            # SL / TP ladder / trailing-stop on open positions
            if label in open_positions:
                pos = open_positions[label]

                # Update highest-price tracker (feeds trailing stop)
                pos.highest_price = max(pos.highest_price, current_price)

                # Stop-loss — dynamic price, may have been moved by TP ladder
                if current_price <= pos.stop_loss_price:
                    _close(label, pos, current_price, current_date, "stop_loss")
                    continue

                # TP ladder — process each unhit level in ascending order
                _tp_levels: tuple[dict, ...] = bot_cfg.take_profit_levels
                _tp_fully_closed: bool = False
                for _tp_idx in range(pos.tps_hit, len(_tp_levels)):
                    _tp: dict = _tp_levels[_tp_idx]
                    _tgt = _tp.get("target_pct")
                    if not isinstance(_tgt, (int, float)):
                        break  # non-numeric level (e.g. "trailing_5pct") — stop
                    if current_price < pos.entry_price * (1.0 + float(_tgt)):
                        break  # price hasn’t reached this level yet
                    # Partial close at this TP
                    _close_shares: float = pos.shares * float(_tp["close_fraction"])
                    _partial_close(
                        label, pos, _close_shares,
                        current_price, current_date, f"tp{_tp_idx + 1}",
                    )
                    # Update dynamic stop-loss based on move_sl_to rule
                    _move_sl = _tp.get("move_sl_to")
                    if _move_sl is not None:
                        if _move_sl == 0.0:
                            pos.stop_loss_price = pos.entry_price  # break-even
                        elif isinstance(_move_sl, str) and _move_sl.startswith("tp"):
                            _sl_tp_idx: int = int(_move_sl[2:]) - 1
                            if 0 <= _sl_tp_idx < len(_tp_levels):
                                _sl_tgt = _tp_levels[_sl_tp_idx].get("target_pct", 0.0)
                                if isinstance(_sl_tgt, (int, float)):
                                    pos.stop_loss_price = (
                                        pos.entry_price * (1.0 + float(_sl_tgt))
                                    )
                    pos.tps_hit += 1
                    if pos.tps_hit >= len(_tp_levels):
                        pos.trailing_active = True
                    if label not in open_positions:  # fully closed by _partial_close
                        _tp_fully_closed = True
                        break
                if _tp_fully_closed:
                    continue

                # Trailing stop — active after last TP hit; exits at -2.5% from highest
                if pos.trailing_active and current_price <= pos.highest_price * 0.975:
                    _close(label, pos, current_price, current_date, "trailing_stop")
                    continue

                # Sell signal
                if score <= bot_cfg.sell_threshold:
                    _close(label, pos, current_price, current_date, "signal")
                    continue

            # Buy signal
            if score >= bot_cfg.min_confluence and label not in open_positions:
                allocation = cash * bot_cfg.max_position_pct
                if allocation >= current_price:
                    _raw_shares: float = allocation / current_price
                    if fractional:
                        _shares: float = _raw_shares
                        _cost: float = allocation
                    else:
                        _shares = float(math.floor(_raw_shares))
                        if _shares < 1.0:
                            continue
                        _cost = _shares * current_price
                    open_positions[label] = SimPosition(
                        symbol=label,
                        entry_price=current_price,
                        shares=_shares,
                        entry_date=current_date,
                        strategy=",".join(bot_cfg.strategy_filter),
                        highest_price=current_price,
                        tps_hit=0,
                        stop_loss_price=current_price * (1.0 - bot_cfg.stop_loss_pct),
                        trailing_active=False,
                    )
                    cash -= _cost

        # Daily equity snapshot
        open_equity = 0.0
        for label, pos in open_positions.items():
            if label in prepared:
                price = prepared[label]["close"].asof(current_date)
                if pd.notna(price):
                    open_equity += pos.shares * float(price)
        snapshots.append({
            "date": current_date,
            "equity": cash + open_equity,
            "cash": cash,
            "open_positions": len(open_positions),
        })

    final_equity = snapshots[-1]["equity"] if snapshots else bot_cfg.initial_capital
    return SimulationResult(
        bot_id=bot_cfg.bot_id,
        snapshots=snapshots,
        trades=closed_trades,
        open_at_end=list(open_positions.values()),
        initial_capital=bot_cfg.initial_capital,
        final_equity=final_equity,
    )
