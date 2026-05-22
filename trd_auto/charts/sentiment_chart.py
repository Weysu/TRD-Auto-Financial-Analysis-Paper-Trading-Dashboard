"""Sentiment display component."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from charts.base import ChartBase

_SIGNAL_COLORS: dict[str, str] = {
    "Bullish": "green",
    "Bearish": "red",
    "Neutral": "gray",
}

_SCORE_ICON: dict[str, str] = {
    "positive": "🟢",
    "negative": "🔴",
    "neutral":  "⚪",
}


class SentimentChart(ChartBase):
    """ChartBase stub — rendering is handled by the module-level
    ``render_sentiment`` function which takes a sentiment dict rather than
    a raw OHLCV DataFrame.
    """

    def render(self, df: pd.DataFrame) -> None:  # noqa: D102
        pass


def render_sentiment(data: dict) -> None:
    """Render overall sentiment score, signal badge, and scored article list.

    Parameters
    ----------
    data:
        Dict returned by ``data.sentiment.get_sentiment``.
        Expected keys: ``overall_score`` (int), ``signal`` (str),
        ``articles`` (list[dict]).

    Each article dict must have: ``title``, ``score``, ``summary``,
    ``url``, ``published_at``.

    Returns
    -------
    None
        Renders directly into the active Streamlit container.
    """
    if not data or not data.get("articles"):
        st.info("No sentiment data available — add API keys to your .env file.")
        return

    overall_score: int = int(data["overall_score"])
    signal: str = data["signal"]
    articles: list[dict] = data["articles"]

    # ------------------------------------------------------------------ header
    col_score, col_signal, _ = st.columns([1, 1, 4])
    with col_score:
        st.metric("Sentiment Score", overall_score)
    with col_signal:
        st.markdown("**Signal**")
        st.badge(signal, color=_SIGNAL_COLORS.get(signal, "gray"))

    st.write("")  # vertical spacer

    # ---------------------------------------------------------------- articles
    for art in articles:
        score: int = int(art.get("score", 0))
        title: str = art.get("title", "")
        summary: str = art.get("summary", "")
        url: str = art.get("url", "")
        published_at: str = art.get("published_at", "")

        if score > 20:
            icon = _SCORE_ICON["positive"]
        elif score < -20:
            icon = _SCORE_ICON["negative"]
        else:
            icon = _SCORE_ICON["neutral"]

        with st.expander(f"{icon} {score:+d} — {title}"):
            if published_at:
                st.caption(published_at)
            st.write(summary if summary else "Résumé non disponible.")
            if url:
                st.markdown(f"[Lire l'article]({url})")
