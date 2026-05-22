"""Trading signal confluence engine.

Aggregates signals from all four built-in strategies plus the sentiment
score into a single composite confluence score and human-readable label.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from data.strategies import (
    run_bollinger_bands,
    run_ma_crossover,
    run_macd_crossover,
    run_rsi_strategy,
)

# Ordered list of (display_name, strategy_function) pairs.
# All functions are called with default parameters.
_STRATEGIES: list[tuple[str, Any]] = [
    ("MA Crossover",    run_ma_crossover),
    ("RSI",             run_rsi_strategy),
    ("Bollinger Bands", run_bollinger_bands),
    ("MACD Crossover",  run_macd_crossover),
]

_SIGNAL_LABELS: dict[int, str] = {
    5: "Strong Buy",
    4: "Strong Buy",
    3: "Buy",
    2: "Neutral",
    1: "Caution",
    0: "Avoid",
}


def compute_confluence(df: pd.DataFrame, sentiment: dict) -> dict[str, Any]:
    """Compute a multi-strategy confluence score for the last bar in ``df``.

    Algorithm
    ---------
    1. Each of the four built-in strategies is run with its default
       parameters.  The *last* value of the resulting ``position`` column
       (1 = in trade / bullish, 0 = flat / bearish) contributes +1 to the
       raw score (max 4).
    2. The ``overall_score`` from ``sentiment`` adjusts the raw score by
       +1 when > 20 and −1 when < −20.
    3. The final score is clamped to [−1, 5].

    Parameters
    ----------
    df:
        Validated OHLCV DataFrame (caller must ensure ``len(df) >= 60``).
    sentiment:
        Dict returned by ``data.sentiment.get_sentiment``.
        Only ``overall_score`` (int) is read.

    Returns
    -------
    dict with keys:

    * ``score``     (int)  — composite confluence score.
    * ``max_score`` (int)  — always 5.
    * ``signal``    (str)  — human-readable label.
    * ``breakdown`` (dict) — per-component contribution:
      strategy names map to their last position (0 or 1);
      ``"Sentiment"`` maps to −1, 0, or +1.
    """
    if df.empty:
        return _empty_result()

    strategy_scores: dict[str, int] = {}
    raw_score: int = 0

    for name, fn in _STRATEGIES:
        last_pos: int = 0
        try:
            enriched = fn(df.copy())
            if "position" in enriched.columns:
                last_val = enriched["position"].iloc[-1]
                last_pos = int(last_val) if pd.notna(last_val) else 0
        except Exception as exc:
            st.warning(f"Strategy '{name}' failed during confluence computation: {exc}")
            last_pos = 0
        strategy_scores[name] = last_pos
        raw_score += last_pos

    # Sentiment adjustment
    sentiment_score: int = int(sentiment.get("overall_score", 0))
    if sentiment_score > 20:
        sentiment_contribution: int = 1
    elif sentiment_score < -20:
        sentiment_contribution = -1
    else:
        sentiment_contribution = 0

    score: int = max(-1, min(5, raw_score + sentiment_contribution))
    signal: str = _SIGNAL_LABELS.get(score, "Avoid")

    return {
        "score":     score,
        "max_score": 5,
        "signal":    signal,
        "breakdown": {**strategy_scores, "Sentiment": sentiment_contribution},
    }


def _empty_result() -> dict[str, Any]:
    """Return a neutral zeroed result when no data is available."""
    return {
        "score":     0,
        "max_score": 5,
        "signal":    "Avoid",
        "breakdown": {
            "MA Crossover":    0,
            "RSI":             0,
            "Bollinger Bands": 0,
            "MACD Crossover":  0,
            "Sentiment":       0,
        },
    }
