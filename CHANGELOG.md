# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.0] - 2026-05-22

### Added

#### Interactive Dashboard (`trd_auto/`)
- Multi-asset support: equities via Yahoo Finance, cryptocurrencies via CoinGecko.
- Interactive candlestick price chart with volume overlay (Plotly).
- Technical indicators panel: RSI, MACD, Bollinger Bands.
- Configurable time ranges: 1D, 1W, 1M, 3M, 1Y.
- Asset selector and time-range picker in a persistent sidebar.

#### Backtesting (`trd_auto/backtest.py`)
- Strategy backtester page supporting four built-in strategies:
  MA Crossover, RSI, Bollinger Bands, MACD Crossover.
- Per-trade PnL breakdown and equity curve.
- Configurable strategy parameters exposed via sidebar widgets.

#### Sentiment Analysis (`trd_auto/data/sentiment.py`)
- Headline fetching from NewsAPI (top 5 articles per asset).
- Per-headline sentiment scoring via Google Gemini (Flash model).
- Aggregate `overall_score` used as a +1 / -1 adjustment in the confluence engine.
- Sentiment panel rendered in the dashboard alongside technical signals.

#### Multi-Strategy Confluence Engine (`trd_auto/data/signal_engine.py`)
- Composite confluence score (0–5) combining all four strategies and sentiment.
- Human-readable signal labels: Strong Buy, Buy, Neutral, Caution, Avoid.
- Per-component breakdown displayed in the UI.

#### Paper Trading Engine (`paper_trader/`)
- SQLite persistence layer (`db.py`) with three tables: portfolio, positions, trades.
- `Portfolio` class with cash-flow management, mark-to-market equity, and summary.
- `executor.py`: autonomous signal executor — scans all assets, buys on score >= 3,
  sells on score <= 1, allocates up to 20 % of cash per position.
- `engine.py`: `schedule`-based main loop, runs every 4 hours, fully exception-safe.
- `monitor.py`: Streamlit page with KPI tiles, open positions table, closed trades
  table, and an equity curve chart — added to the main app navigation.

#### Infrastructure
- `Dockerfile`: single `python:3.12-slim` image for both services.
- `docker-compose.yml`: `dashboard` (port 8501) and `paper_engine` services sharing
  a `./paper_trader.db` bind-mount for live data exchange.
- `.dockerignore` and `.gitignore` configured for the full stack.
