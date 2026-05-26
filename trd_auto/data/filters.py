"""
Market regime filters.
Each filter takes an OHLCV DataFrame and returns a bool.
The DataFrame must have a 'close' column and at least 200 rows for SMA200.
"""
import pandas as pd


def is_uptrend_sma200(df: pd.DataFrame) -> bool:
    """
    Return True if the last closing price is above the 200-period simple moving average.
    Returns False if there are fewer than 200 bars (insufficient data).
    """
    if len(df) < 200:
        return False
    sma200 = df["close"].rolling(200).mean().iloc[-1]
    last_close = df["close"].iloc[-1]
    return bool(last_close > sma200)


def is_downtrend_sma200(df: pd.DataFrame) -> bool:
    """Return True if the last closing price is below the SMA200."""
    if len(df) < 200:
        return False
    return not is_uptrend_sma200(df)
