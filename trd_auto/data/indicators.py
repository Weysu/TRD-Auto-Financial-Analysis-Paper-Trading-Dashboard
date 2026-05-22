"""Technical indicator computation using pandas-ta."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

_MIN_ROWS: int = 15


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI, MACD, and Bollinger Bands and append them as new columns.

    Returns *df* unchanged when it is empty or has fewer than ``_MIN_ROWS``
    rows, so callers never have to guard against a missing-column error.
    """
    if df.empty or len(df) < _MIN_ROWS:
        return df

    out = df.copy()

    # RSI-14 ------------------------------------------------------------------
    out["rsi_14"] = ta.rsi(out["close"], length=14)

    # MACD (12, 26, 9) --------------------------------------------------------
    macd_df = ta.macd(out["close"])
    if macd_df is not None and not macd_df.empty:
        macd_col   = next(c for c in macd_df.columns if c.startswith("MACD_"))
        signal_col = next(c for c in macd_df.columns if c.startswith("MACDs_"))
        hist_col   = next(c for c in macd_df.columns if c.startswith("MACDh_"))
        out["macd"]        = macd_df[macd_col].values
        out["macd_signal"] = macd_df[signal_col].values
        out["macd_hist"]   = macd_df[hist_col].values

    # Bollinger Bands (20, 2) -------------------------------------------------
    bb_df = ta.bbands(out["close"], length=20)
    if bb_df is not None and not bb_df.empty:
        lower_col  = next(c for c in bb_df.columns if c.startswith("BBL"))
        middle_col = next(c for c in bb_df.columns if c.startswith("BBM"))
        upper_col  = next(c for c in bb_df.columns if c.startswith("BBU"))
        out["bb_lower"]  = bb_df[lower_col].values
        out["bb_middle"] = bb_df[middle_col].values
        out["bb_upper"]  = bb_df[upper_col].values

    return out
