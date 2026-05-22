"""
data.processor
==============
Stateless data-processing and normalisation layer.

Responsibilities
----------------
- Validate and clean raw DataFrames returned by connectors.
- Compute derived metrics consumed by the chart and UI layers.
- Act as the single integration point between the data layer and the
  chart/UI layer — charts never call connectors directly.

Design constraints
------------------
- All functions are pure and stateless (no class state, no side effects).
- No external dependencies beyond ``pandas``.
- ``validate`` is lenient on dtypes but strict on column presence so that
  the UI layer receives either a clean DataFrame or a clear error message.

Planned extensions (do not implement yet)
-----------------------------------------
- compute_rsi(df, period)               : Relative Strength Index
- compute_macd(df, fast, slow, signal)  : MACD line + signal + histogram
- compute_bollinger(df, period, std_dev): Bollinger Bands
- resample_ohlcv(df, rule)              : Resample to a coarser timeframe
- merge_sentiment(df, sentiment_df)     : Align sentiment series to OHLCV index
"""

import pandas as pd

# Columns that every connector must provide.
_REQUIRED_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate and clean a raw OHLCV DataFrame returned by a connector.

    Steps (in order):
    1. Verify all required columns are present; raise ``ValueError`` if not.
    2. Ensure ``timestamp`` is ``datetime64`` (tz-aware or tz-naive);
       coerce string/object columns with ``pd.to_datetime``.
    3. Drop any row where ``close`` is null — rows without a closing price
       are unusable for charting and metric computation.
    4. Reset the integer index so the caller always receives a clean,
       contiguous index regardless of what the connector returned.

    Parameters
    ----------
    df : pd.DataFrame
        Raw OHLCV DataFrame produced by a ``DataSourceBase`` connector.
        Must contain at minimum the columns:
        ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame with the same columns as the input, a contiguous
        integer index, and no null ``close`` values.

    Raises
    ------
    ValueError
        If one or more required columns are absent from ``df``.
    """
    missing: list[str] = [col for col in _REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            f"OHLCV DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )

    out = df.copy()

    # Coerce timestamp to datetime if it arrived as object/string.
    if not pd.api.types.is_datetime64_any_dtype(out["timestamp"]):
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")

    # Drop rows with a null closing price — they cannot be charted or metrified.
    out = out.dropna(subset=["close"])

    return out.reset_index(drop=True)


def compute_metrics(df: pd.DataFrame) -> dict:
    """
    Compute scalar summary metrics over a validated OHLCV DataFrame.

    All metrics are computed from the ``close``, ``high``, ``low``, and
    ``volume`` columns.  The DataFrame should be passed through
    ``validate`` first.

    Parameters
    ----------
    df : pd.DataFrame
        Validated OHLCV DataFrame.  Must contain:
        ``close``, ``high``, ``low``, ``volume``.

    Returns
    -------
    dict
        Flat dictionary with the following keys:

        ===========  =======  ===============================================
        Key          type     Description
        ===========  =======  ===============================================
        change_pct   float    Total percentage change from the first to the
                              last ``close`` in the period.
                              Formula: ``(last / first - 1) * 100``.
                              ``nan`` if fewer than 2 rows.
        high         float    Maximum value of the ``high`` column over the
                              period.
        low          float    Minimum value of the ``low`` column over the
                              period.
        avg_volume   float    Mean of the ``volume`` column over the period.
        volatility   float    Standard deviation of the daily ``close``
                              percentage changes (annualised *not* applied —
                              raw std of ``close.pct_change()``).
                              ``nan`` if fewer than 2 rows.
        ===========  =======  ===============================================

        All values are ``float``.  Returns all-``nan`` keys (not an empty
        dict) when ``df`` is empty so callers can always expect the same
        set of keys.
    """
    # Return the sentinel structure on empty input.
    if df.empty or "close" not in df.columns:
        return {
            "change_pct": float("nan"),
            "high":       float("nan"),
            "low":        float("nan"),
            "avg_volume": float("nan"),
            "volatility": float("nan"),
        }

    close: pd.Series  = df["close"].astype("float64")
    high: pd.Series   = df["high"].astype("float64")
    low: pd.Series    = df["low"].astype("float64")
    volume: pd.Series = df["volume"].astype("float64")

    first_close: float = float(close.iloc[0])
    last_close: float  = float(close.iloc[-1])

    # Period % change: (last / first - 1) * 100.
    if first_close != 0 and len(close) >= 2:
        change_pct: float = (last_close / first_close - 1.0) * 100.0
    else:
        change_pct = float("nan")

    # Volatility: std of period-over-period % changes (as decimal, not percent).
    volatility: float = float(close.pct_change().std()) if len(close) >= 2 else float("nan")

    return {
        "change_pct": change_pct,
        "high":       float(high.max()),
        "low":        float(low.min()),
        "avg_volume": float(volume.mean()),
        "volatility": volatility,
    }
