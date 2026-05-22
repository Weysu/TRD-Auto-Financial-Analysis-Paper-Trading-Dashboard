"""
paper_trader.db
===============
SQLite persistence layer for the paper trading engine.

Uses only the standard-library ``sqlite3`` module.  All public functions
are wrapped in try/except blocks so that database failures never crash the
calling code — they log the error and return a safe sentinel value instead.

Database file
-------------
``paper_trader.db`` is created at the project root (one level above the
``paper_trader/`` package directory).

Tables
------
portfolio : id, created_at, initial_capital REAL, current_capital REAL
positions : id, symbol, source, entry_price REAL, shares REAL,
            entry_date TEXT, strategy TEXT, status TEXT (open/closed)
trades    : id, symbol, source, strategy, entry_price REAL, exit_price REAL,
            shares REAL, entry_date TEXT, exit_date TEXT, pnl REAL, pnl_pct REAL
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Database lives at the project root (one level above paper_trader/) so that
# both the Streamlit dashboard and the engine container share the same file
# via a single bind-mount: ./paper_trader.db:/app/paper_trader.db
_DB_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "paper_trader.db",
)

_DDL: str = """
CREATE TABLE IF NOT EXISTS portfolio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    initial_capital REAL    NOT NULL,
    current_capital REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    shares      REAL    NOT NULL,
    entry_date  TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    exit_price  REAL    NOT NULL,
    shares      REAL    NOT NULL,
    entry_date  TEXT    NOT NULL,
    exit_date   TEXT    NOT NULL,
    pnl         REAL    NOT NULL,
    pnl_pct     REAL    NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    """Return a connection with row_factory set to ``sqlite3.Row``."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db(initial_capital: float = 10_000.0) -> None:
    """Create all tables and seed the portfolio row if the database is empty."""
    try:
        with _connect() as conn:
            conn.executescript(_DDL)
            count: int = conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
            if count == 0:
                now = datetime.now(tz=timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO portfolio (created_at, initial_capital, current_capital)"
                    " VALUES (?, ?, ?)",
                    (now, initial_capital, initial_capital),
                )
    except sqlite3.Error as exc:
        logger.error("init_db failed: %s", exc)


# ---------------------------------------------------------------------------
# Portfolio queries / mutations
# ---------------------------------------------------------------------------


def get_portfolio() -> dict[str, Any]:
    """Return the single portfolio row as a dict, or ``{}`` on failure."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio ORDER BY id LIMIT 1"
            ).fetchone()
            return dict(row) if row else {}
    except sqlite3.Error as exc:
        logger.error("get_portfolio failed: %s", exc)
        return {}


def update_capital(new_capital: float) -> None:
    """Overwrite ``current_capital`` on the portfolio row."""
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE portfolio SET current_capital = ?"
                " WHERE id = (SELECT id FROM portfolio ORDER BY id LIMIT 1)",
                (new_capital,),
            )
    except sqlite3.Error as exc:
        logger.error("update_capital failed: %s", exc)


# ---------------------------------------------------------------------------
# Position operations
# ---------------------------------------------------------------------------


def open_position(
    symbol: str,
    source: str,
    entry_price: float,
    shares: float,
    strategy: str,
) -> int:
    """Insert a new open position.  Returns the new row id, or ``-1`` on failure."""
    try:
        with _connect() as conn:
            now = datetime.now(tz=timezone.utc).isoformat()
            cursor = conn.execute(
                "INSERT INTO positions"
                " (symbol, source, entry_price, shares, entry_date, strategy, status)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open')",
                (symbol, source, entry_price, shares, now, strategy),
            )
            return cursor.lastrowid or -1
    except sqlite3.Error as exc:
        logger.error("open_position(%s) failed: %s", symbol, exc)
        return -1


def close_position(position_id: int, exit_price: float) -> dict[str, Any]:
    """
    Mark a position as closed, record the trade, and return the trade dict.

    Returns ``{}`` if the position is not found or the operation fails.
    """
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE id = ? AND status = 'open'",
                (position_id,),
            ).fetchone()

            if row is None:
                logger.warning(
                    "close_position: no open position with id=%d", position_id
                )
                return {}

            pos = dict(row)
            exit_date = datetime.now(tz=timezone.utc).isoformat()
            pnl: float = (exit_price - pos["entry_price"]) * pos["shares"]
            pnl_pct: float = (
                (exit_price - pos["entry_price"]) / pos["entry_price"] * 100.0
            )

            conn.execute(
                "INSERT INTO trades"
                " (symbol, source, strategy, entry_price, exit_price, shares,"
                "  entry_date, exit_date, pnl, pnl_pct)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pos["symbol"],
                    pos["source"],
                    pos["strategy"],
                    pos["entry_price"],
                    exit_price,
                    pos["shares"],
                    pos["entry_date"],
                    exit_date,
                    pnl,
                    pnl_pct,
                ),
            )
            conn.execute(
                "UPDATE positions SET status = 'closed' WHERE id = ?",
                (position_id,),
            )

            return {
                "symbol": pos["symbol"],
                "source": pos["source"],
                "strategy": pos["strategy"],
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "shares": pos["shares"],
                "entry_date": pos["entry_date"],
                "exit_date": exit_date,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
    except sqlite3.Error as exc:
        logger.error("close_position(%d) failed: %s", position_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Read-only queries
# ---------------------------------------------------------------------------


def get_open_positions() -> list[dict[str, Any]]:
    """Return all open positions ordered by entry date."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_date"
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_open_positions failed: %s", exc)
        return []


def get_trade_history() -> list[dict[str, Any]]:
    """Return all closed trades, newest first."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY exit_date DESC"
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_trade_history failed: %s", exc)
        return []
