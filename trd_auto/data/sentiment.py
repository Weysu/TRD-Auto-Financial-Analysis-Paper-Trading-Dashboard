"""News sentiment scoring via NewsAPI + Gemini."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import google.generativeai as genai
import streamlit as st
from dotenv import load_dotenv
from newsapi import NewsApiClient

_log = logging.getLogger(__name__)

# Load .env from the project root (no-op if already set via environment).
load_dotenv()

_NEWS_API_KEY: str = os.environ.get("NEWS_API_KEY", "")
_GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

if not _NEWS_API_KEY:
    _log.warning("NEWS_API_KEY is not set — sentiment scoring will be disabled.")
if not _GEMINI_API_KEY:
    _log.warning("GEMINI_API_KEY is not set — sentiment scoring will be disabled.")
_ARTICLE_COUNT: int = 5
_GEMINI_MODEL: str = "gemini-2.5-flash"

_PROMPT_TEMPLATE: str = (
    "Rate the sentiment of this financial news headline for an investor, "
    "from -100 (very negative) to +100 (very positive). "
    "Return only a JSON with keys: score (int), summary (str, one sentence in French). "
    "Headline: {title}\n"
    "IMPORTANT: your entire response must be only the raw JSON object, "
    "no markdown, no backticks, no explanation, no thinking text. "
    "Start your response with {{ and end with }}"
)

# Configure Gemini once at import time (if key is present).
if _GEMINI_API_KEY:
    genai.configure(api_key=_GEMINI_API_KEY)


def _call_gemini(title: str) -> tuple[int, str]:
    """Score a single headline via Gemini. Returns (score, summary).

    Falls back to ``(0, "")`` on any error so a single API failure never
    blocks the full sentiment result.  Logs the raw response text to stdout
    on failure so the cause is visible in the Streamlit server console.
    """
    raw_text: str = ""
    try:
        model = genai.GenerativeModel(_GEMINI_MODEL)
        response = model.generate_content(_PROMPT_TEMPLATE.format(title=title))
        raw_text = response.text.strip()

        # --- attempt 1: strip markdown fences and parse directly ----------
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE
        ).strip()
        try:
            payload: dict = json.loads(cleaned)
        except json.JSONDecodeError:
            # --- attempt 2: regex extraction of first {...} block ----------
            match = re.search(r"\{.*?\}", raw_text, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON object found in Gemini response: {raw_text!r}")
            payload = json.loads(match.group())

        score: int = max(-100, min(100, int(payload["score"])))
        return score, str(payload.get("summary", ""))

    except Exception as exc:
        # Log via the standard logging framework so output is controlled by
        # the log level and never printed unconditionally to stdout / container logs.
        _log.warning(
            "[sentiment] Gemini parse error for title=%r — %s", title, exc
        )
        return 0, ""


@st.cache_data(ttl=1800, show_spinner=False)
def get_sentiment(asset_label: str, symbol: str, source: str) -> dict[str, Any]:
    """Fetch the 5 most recent English news articles and score their sentiment.

    Parameters
    ----------
    asset_label:
        Human-readable asset name used as the NewsAPI ``q`` query string
        (e.g. ``"Bitcoin (BTC)"``).  Drives the news search.
    symbol:
        Connector symbol string (e.g. ``"AAPL"`` or ``"bitcoin"``).  Used
        as part of the Streamlit cache key so different assets with similar
        labels are cached independently.
    source:
        Data source key (``"yahoo"`` or ``"coingecko"``).  Also part of the
        cache key.

    Returns
    -------
    dict
        Keys:

        * ``overall_score`` (int) — average sentiment score across articles.
        * ``signal`` (str) — ``"Bullish"`` if score > 20,
          ``"Bearish"`` if score < -20, else ``"Neutral"``.
        * ``articles`` (list[dict]) — one entry per article, each with
          ``title``, ``score``, ``summary``, ``url``, ``published_at``.

    Notes
    -----
    Returns a neutral empty result if either API key is missing, so the
    dashboard degrades gracefully without crashing.
    """
    if not _NEWS_API_KEY or not _GEMINI_API_KEY:
        return {"overall_score": 0, "signal": "Neutral", "articles": []}

    # Strip the ticker symbol in parentheses so the query is clean,
    # e.g. "Bitcoin (BTC)" → "Bitcoin", "S&P 500 ETF (SPY)" → "S&P 500 ETF".
    news_query: str = re.sub(r"\s*\(.*?\)", "", asset_label).strip()

    client = NewsApiClient(api_key=_NEWS_API_KEY)
    response: dict = client.get_everything(
        q=news_query,
        language="en",
        sort_by="publishedAt",
        page_size=_ARTICLE_COUNT,
    )

    raw_articles: list[dict] = (response.get("articles") or [])[:_ARTICLE_COUNT]
    if not raw_articles:
        return {"overall_score": 0, "signal": "Neutral", "articles": []}

    articles: list[dict[str, Any]] = []
    scores: list[int] = []

    for art in raw_articles:
        title: str = art.get("title") or ""
        score, summary = _call_gemini(title)
        scores.append(score)
        articles.append(
            {
                "title": title,
                "score": score,
                "summary": summary,
                "url": art.get("url", ""),
                "published_at": art.get("publishedAt", ""),
            }
        )

    overall_score: int = int(round(sum(scores) / len(scores))) if scores else 0

    if overall_score > 20:
        signal = "Bullish"
    elif overall_score < -20:
        signal = "Bearish"
    else:
        signal = "Neutral"

    return {
        "overall_score": overall_score,
        "signal": signal,
        "articles": articles,
    }
