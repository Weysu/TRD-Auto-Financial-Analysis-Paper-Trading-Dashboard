# TRD Auto — Financial Analysis & Paper Trading Dashboard

A self-contained financial dashboard and automated paper trading engine built with Python and Streamlit. It provides interactive technical analysis, multi-strategy backtesting, AI-powered sentiment scoring, and a fully autonomous paper trading loop — all running from a single Docker Compose stack.

---

## Architecture Overview

### `trd_auto/` — Interactive Dashboard
The main Streamlit application. Organised as a set of loosely-coupled modules:

| Module | Role |
|---|---|
| `app.py` | Composition root — navigation, data fetching, page routing |
| `config/assets.py` | Single source of truth for all tradeable assets and time ranges |
| `data/connectors/` | Pluggable data connectors (Yahoo Finance, CoinGecko) |
| `data/strategies.py` | Four built-in trading strategies (MA Crossover, RSI, Bollinger Bands, MACD) |
| `data/signal_engine.py` | Multi-strategy confluence scorer |
| `data/sentiment.py` | News headline scoring via NewsAPI + Gemini |
| `data/indicators.py` | Technical indicator computation (RSI, MACD, Bollinger Bands, ...) |
| `data/processor.py` | OHLCV validation and metric computation |
| `charts/` | Plotly chart builders (price, volume, sentiment) |
| `ui/` | Streamlit layout and sidebar components |
| `backtest.py` | Interactive strategy backtester page |

### `paper_trader/` — Autonomous Paper Trading Engine
A standalone engine that reuses the connectors and strategies from `trd_auto/`.

| Module | Role |
|---|---|
| `db.py` | SQLite persistence layer (portfolio, positions, trades) |
| `portfolio.py` | `Portfolio` class — cash management, mark-to-market equity |
| `executor.py` | Signal executor — scans all assets every cycle, buys/sells on confluence |
| `engine.py` | Scheduler — runs `check_and_execute` every 4 hours via `schedule` |
| `monitor.py` | Streamlit page — KPIs, open positions, trade history, equity curve |

---

## Stack

| Layer | Technology |
|---|---|
| UI | [Streamlit](https://streamlit.io) + [Plotly](https://plotly.com/python/) |
| Data — Equities | [yfinance](https://github.com/ranaroussi/yfinance) |
| Data — Crypto | [CoinGecko API](https://www.coingecko.com/en/api) via `pycoingecko` |
| Technical analysis | [pandas-ta](https://github.com/twopirllc/pandas-ta), NumPy |
| Sentiment | [NewsAPI](https://newsapi.org) + [Gemini](https://ai.google.dev) (Flash) |
| Persistence | SQLite (stdlib `sqlite3`) |
| Containerisation | Docker + Docker Compose |
| Language | Python 3.12 |

---

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd "Finance APP"
```

### 2. Create your environment file

```bash
cp trd_auto/.env.example trd_auto/.env
```

Fill in the required API keys in `trd_auto/.env`:

```
NEWS_API_KEY=your_newsapi_key
GEMINI_API_KEY=your_gemini_key
```

### 3. Install dependencies

```bash
pip install -r trd_auto/requirements.txt
```

### 4. Run the dashboard

```bash
streamlit run trd_auto/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### 5. Run the paper trading engine (optional, separate process)

```bash
# Create the database file before the first run
touch paper_trader.db      # Linux / macOS
New-Item paper_trader.db   # PowerShell

python -m paper_trader.engine
```

---

## Docker Deployment

Both services (dashboard + paper trading engine) share a single image built from the project `Dockerfile`.

```bash
# Create the database file on the host first (one-time)
touch paper_trader.db

# Build and start both services in the background
docker compose up --build -d

# Stream logs
docker compose logs -f

# Stop all services
docker compose down
```

The dashboard is available at [http://localhost:8501](http://localhost:8501).
Both containers share the same `./paper_trader.db` bind-mount so the Paper Trading monitor page reflects live engine activity in real time.

> **Note:** `paper_trader.db` must exist on the host before running `docker compose up`.
> If it is missing, Docker will create a directory at that path instead of a file.

---

## Disclaimer

> This project is for educational purposes only. Not financial advice.
