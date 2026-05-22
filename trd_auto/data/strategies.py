"""Trading strategy implementations.

Each public function takes a validated OHLCV DataFrame and strategy-specific
parameters, and returns the same DataFrame extended with two columns:

* ``signal``   — trade trigger: 1 = buy, -1 = sell, 0 = hold.
* ``position`` — running state: 1 = in trade, 0 = out of trade.

Only ``pandas`` and ``numpy`` are used; no third-party strategy libraries.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _signals_to_position(signal: pd.Series) -> pd.Series:
    """Convert discrete buy / sell signals to a running binary position.

    Treats 0 (hold) as "no change", propagates the last explicit state
    (1 after a buy, 0 after a sell) forward via forward-fill, and starts
    flat (position = 0) before the first signal.
    """
    pos = signal.astype(float).replace(0.0, np.nan).replace(-1.0, 0.0)
    return pos.ffill().fillna(0.0).astype(int)


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    """Cutler's RSI using a simple rolling-mean of gains and losses.

    Note: this is *not* Wilder's EWM-based RSI (used by most charting
    platforms).  Results may diverge slightly for the first ~period bars.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period).mean()
    rs = gain / loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # When avg_loss == 0 but avg_gain is defined (all bars in the window
    # closed higher), the RSI is mathematically 100, not NaN.
    fully_positive = (loss == 0.0) & gain.notna()
    return rsi.where(~fully_positive, other=100.0)


# ---------------------------------------------------------------------------
# Strategy functions
# ---------------------------------------------------------------------------

def run_ma_crossover(
    df: pd.DataFrame,
    fast_ma: int = 20,
    slow_ma: int = 50,
) -> pd.DataFrame:
    """Simple Moving Average Crossover.

    Generates a buy signal when the fast SMA crosses above the slow SMA and
    a sell signal when it crosses below.

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame.
    fast_ma:
        Lookback window for the fast SMA (must be < ``slow_ma``).
    slow_ma:
        Lookback window for the slow SMA.

    Returns
    -------
    DataFrame with ``signal`` and ``position`` columns appended.
    """
    out = df.copy()

    if fast_ma >= slow_ma:
        out["signal"] = 0
        out["position"] = 0
        return out

    fast = out["close"].rolling(fast_ma).mean()
    slow = out["close"].rolling(slow_ma).mean()

    signal = pd.Series(0, index=out.index)
    signal[(fast > slow) & (fast.shift(1) <= slow.shift(1))] = 1
    signal[(fast < slow) & (fast.shift(1) >= slow.shift(1))] = -1

    out["signal"] = signal
    out["position"] = (fast > slow).fillna(False).astype(int)
    return out


def run_rsi_strategy(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: int = 30,
    overbought: int = 70,
) -> pd.DataFrame:
    """RSI Mean-Reversion Strategy.

    Buys when RSI crosses back above the oversold threshold (bounce from
    oversold zone) and sells when RSI crosses above the overbought threshold.

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame.
    rsi_period:
        RSI lookback window.
    oversold:
        RSI level below which the asset is considered oversold (buy zone).
    overbought:
        RSI level above which the asset is considered overbought (sell zone).

    Returns
    -------
    DataFrame with ``signal`` and ``position`` columns appended.
    """
    out = df.copy()
    rsi = _compute_rsi(out["close"], rsi_period)

    signal = pd.Series(0, index=out.index)
    # Buy: RSI crosses above the oversold threshold from below
    signal[(rsi > oversold) & (rsi.shift(1) <= oversold)] = 1
    # Sell: RSI crosses above the overbought threshold
    signal[(rsi > overbought) & (rsi.shift(1) <= overbought)] = -1

    out["signal"] = signal
    out["position"] = _signals_to_position(signal)
    return out


def run_bollinger_bands(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Band Mean-Reversion Strategy.

    Issues a buy signal while price is at or below the lower band (oversold)
    and a sell signal while price is at or above the upper band (overbought).
    The backtester enters only once per signal cluster (guarded by position).

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame.
    bb_period:
        Rolling window for the middle band (SMA) and standard deviation.
    bb_std:
        Number of standard deviations for the band width.

    Returns
    -------
    DataFrame with ``signal`` and ``position`` columns appended.
    """
    out = df.copy()
    mid = out["close"].rolling(bb_period).mean()
    std = out["close"].rolling(bb_period).std(ddof=1)
    upper = mid + bb_std * std
    lower = mid - bb_std * std

    signal = pd.Series(0, index=out.index)
    signal[out["close"] <= lower] = 1
    signal[out["close"] >= upper] = -1

    out["signal"] = signal
    out["position"] = _signals_to_position(signal)
    return out


def run_macd_crossover(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """MACD Line Crossover Strategy.

    Buys when the MACD line crosses above the signal line and sells when it
    crosses below.

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame.
    fast:
        Span for the fast EMA (must be < ``slow``).
    slow:
        Span for the slow EMA.
    signal_period:
        Span for the signal line EMA (applied to the MACD line).

    Returns
    -------
    DataFrame with ``signal`` and ``position`` columns appended.
    """
    out = df.copy()

    if fast >= slow:
        out["signal"] = 0
        out["position"] = 0
        return out

    exp_fast = out["close"].ewm(span=fast, adjust=False).mean()
    exp_slow = out["close"].ewm(span=slow, adjust=False).mean()
    macd = exp_fast - exp_slow
    sig_line = macd.ewm(span=signal_period, adjust=False).mean()

    signal = pd.Series(0, index=out.index)
    signal[(macd > sig_line) & (macd.shift(1) <= sig_line.shift(1))] = 1
    signal[(macd < sig_line) & (macd.shift(1) >= sig_line.shift(1))] = -1

    out["signal"] = signal
    out["position"] = _signals_to_position(signal)
    return out
