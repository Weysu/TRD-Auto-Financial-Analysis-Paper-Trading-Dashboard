"""Long-only backtester.

Simulates a strategy defined by ``signal`` (1/−1/0) and ``position`` (1/0)
columns produced by a function in ``data.strategies``.

Rules
-----
- Long only — no short selling.
- Entry  : spend all available cash on the maximum number of whole shares
  at the closing price when ``signal == 1`` and not already in a position.
- Exit   : sell all shares at the closing price when ``signal == -1`` and
  in a position.
- No leverage, no transaction costs, no slippage, no fractional shares.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float = 10_000.0,
    annualization_factor: int = 252,
) -> dict[str, Any]:
    """Simulate a long-only strategy and compute performance metrics.

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame enriched with ``signal`` (int) and
        ``position`` (int) columns from a strategy function.  The
        ``timestamp`` column is used as the equity-curve index.
    initial_capital:
        Starting cash in USD.
    annualization_factor:
        Number of trading periods per year used to annualise the Sharpe
        ratio.  Use ``252`` for equities (trading days) and ``365`` for
        crypto assets that trade every calendar day.

    Returns
    -------
    dict with keys:

    * ``equity_curve``        — pd.Series (indexed by timestamp).
    * ``bh_equity``           — pd.Series, buy-and-hold baseline.
    * ``trades``              — list[dict], one dict per completed trade.
    * ``total_return_pct``    — float.
    * ``buy_hold_return_pct`` — float.
    * ``num_trades``          — int.
    * ``win_rate``            — float in [0, 1].
    * ``max_drawdown_pct``    — float ≤ 0 (e.g. −15.3 means −15.3 %).
    * ``sharpe_ratio``        — float, annualised.

    Known limitations
    -----------------
    - No transaction costs or slippage modelled.
    - No fractional shares; leftover cash stays uninvested.
    - Risk-free rate set to 0 in the Sharpe formula.
    - Assumes each bar represents one calendar period (daily).
    """
    if df.empty or "signal" not in df.columns:
        return _empty_result(initial_capital)

    timestamps: list = df["timestamp"].tolist()
    closes: list[float] = df["close"].tolist()
    signals: list[int] = df["signal"].tolist()

    capital: float = initial_capital
    shares: int = 0
    buy_price: float = 0.0
    buy_date: Any = None

    equity: list[float] = []
    trades: list[dict[str, Any]] = []

    for ts, price, sig in zip(timestamps, closes, signals):
        price = float(price)
        sig = int(sig)

        if sig == 1 and shares == 0 and price > 0:
            shares = int(capital // price)
            if shares > 0:
                capital -= shares * price
                buy_price = price
                buy_date = ts

        elif sig == -1 and shares > 0:
            proceeds = shares * price
            pnl = proceeds - shares * buy_price
            trades.append(
                {
                    "entry_date": buy_date,
                    "exit_date": ts,
                    "entry_price": round(buy_price, 4),
                    "exit_price": round(price, 4),
                    "shares": shares,
                    "pnl": round(pnl, 2),
                    "return_pct": round((price / buy_price - 1) * 100, 2),
                }
            )
            capital += proceeds
            shares = 0
            buy_price = 0.0
            buy_date = None

        equity.append(capital + shares * price)

    index = pd.Index(timestamps, name="timestamp")
    equity_series = pd.Series(equity, index=index, name="strategy")

    # Buy-and-hold baseline: proportional growth of initial_capital,
    # independent of any signal or share-count arithmetic.
    first_close: float = float(closes[0]) if closes else 1.0
    close_series = pd.Series(closes, dtype=float)
    bh_equity: pd.Series = (close_series / first_close * initial_capital).rename("buy_hold")
    bh_equity.index = index  # align to the same timestamp index as equity_series

    # ---------------------------------------------------------------- metrics
    final_equity: float = float(equity_series.iloc[-1]) if len(equity_series) else initial_capital
    total_return_pct: float = (final_equity / initial_capital - 1.0) * 100.0

    last_close: float = float(closes[-1]) if closes else first_close
    buy_hold_return_pct: float = (last_close / first_close - 1.0) * 100.0

    num_trades: int = len(trades)
    win_rate: float = (
        sum(1 for t in trades if t["pnl"] > 0) / num_trades if num_trades else 0.0
    )

    # Max drawdown (negative value, e.g. -15.3 means -15.3 %)
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max.replace(0.0, np.nan)
    max_drawdown_pct: float = float(drawdown.min() * 100.0) if len(drawdown) else 0.0

    # Annualised Sharpe (risk-free rate = 0)
    daily_ret = equity_series.pct_change().dropna()
    if len(daily_ret) > 1 and float(daily_ret.std()) > 0:
        sharpe_ratio: float = float(
            (daily_ret.mean() / daily_ret.std()) * math.sqrt(annualization_factor)
        )
    else:
        sharpe_ratio = 0.0

    return {
        "equity_curve":        equity_series,
        "bh_equity":           bh_equity,
        "trades":              trades,
        "total_return_pct":    round(total_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "num_trades":          num_trades,
        "win_rate":            round(win_rate, 4),
        "max_drawdown_pct":    round(max_drawdown_pct, 2),
        "sharpe_ratio":        round(sharpe_ratio, 2),
    }


def _empty_result(initial_capital: float) -> dict[str, Any]:
    """Return a zero-filled result when data or signals are missing."""
    return {
        "equity_curve":        pd.Series(dtype=float),
        "bh_equity":           pd.Series(dtype=float),
        "trades":              [],
        "total_return_pct":    0.0,
        "buy_hold_return_pct": 0.0,
        "num_trades":          0,
        "win_rate":            0.0,
        "max_drawdown_pct":    0.0,
        "sharpe_ratio":        0.0,
    }
