"""
paper_trader.db
===============
SQLite persistence layer for the multi-bot paper trading engine.

Uses only the standard-library ``sqlite3`` module.  All public functions
are wrapped in try/except blocks so that database failures never crash the
calling code — they log the error and return a safe sentinel value instead.

Database file
-------------
``paper_trader.db`` is created at the project root (one level above the
``paper_trader/`` package directory).

Tables
------
portfolio : bot_id TEXT PRIMARY KEY, created_at, initial_capital REAL,
            current_capital REAL
positions : id, bot_id TEXT, symbol, source, entry_price REAL, shares REAL,
            entry_date TEXT, strategy TEXT, status TEXT (open/closed)
trades    : id, bot_id TEXT, symbol, source, strategy, entry_price REAL,
            exit_price REAL, shares REAL, entry_date TEXT, exit_date TEXT,
            pnl REAL, pnl_pct REAL, reason TEXT

Backward compatibility
----------------------
When an existing ``paper_trader.db`` is detected (tables already present),
``_migrate_schema`` adds the new columns via ``ALTER TABLE … ADD COLUMN``
statements that are silently ignored if the column already exists.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from paper_trader.bots import BotConfig

logger = logging.getLogger(__name__)

# Database lives at the project root so both containers share a single bind-mount.
_DB_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "paper_trader.db",
)

# DDL for a clean (new) database.
_DDL: str = """
CREATE TABLE IF NOT EXISTS portfolio (
    bot_id          TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    current_capital REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      TEXT    NOT NULL DEFAULT '',
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
    bot_id      TEXT    NOT NULL DEFAULT '',
    symbol      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    exit_price  REAL    NOT NULL,
    shares      REAL    NOT NULL,
    entry_date  TEXT    NOT NULL,
    exit_date   TEXT    NOT NULL,
    pnl         REAL    NOT NULL,
    pnl_pct     REAL    NOT NULL,
    reason      TEXT    NOT NULL DEFAULT 'signal'
);
"""


def _connect() -> sqlite3.Connection:
    """Return a connection with row_factory set to ``sqlite3.Row``."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """
    Return the set of column names for ``table`` using ``PRAGMA table_info``.

    Returns an empty set if the table does not exist.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _portfolio_has_bot_id_pk(conn: sqlite3.Connection) -> bool:
    """
    Return ``True`` when the portfolio table already uses ``bot_id`` as its
    PRIMARY KEY (the new schema).  Detects the old auto-increment schema by
    inspecting ``PRAGMA table_info`` — if ``bot_id`` is absent OR its ``pk``
    rank is 0 (not a PK column), the table is considered legacy.
    """
    rows = conn.execute("PRAGMA table_info(portfolio)").fetchall()
    if not rows:          # table does not exist yet
        return True       # nothing to migrate; DDL will create it correctly
    for row in rows:
        if row["name"] == "bot_id" and row["pk"] > 0:
            return True
    return False


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Bring an existing database up to the current multi-bot schema.

    Strategy
    --------
    1. **portfolio**: if the table exists but uses the old auto-increment PK
       (no ``bot_id`` PK column), drop it and let ``_DDL`` recreate it on
       the next ``executescript`` call.  Any old single-bot data is discarded
       because it cannot be mapped to a ``bot_id`` reliably.

    2. **positions / trades**: use ``PRAGMA table_info`` to check whether each
       required column is present before issuing ``ALTER TABLE``; this avoids
       the ``OperationalError: duplicate column name`` that made the original
       try/except approach fragile.
    """
    # ------------------------------------------------------------------
    # 1. Portfolio schema check — drop legacy table if necessary
    # ------------------------------------------------------------------
    if not _portfolio_has_bot_id_pk(conn):
        logger.warning(
            "Legacy portfolio schema detected (no bot_id PK). "
            "Dropping and recreating portfolio table."
        )
        conn.execute("DROP TABLE IF EXISTS portfolio")
        conn.execute(
            """
            CREATE TABLE portfolio (
                bot_id          TEXT PRIMARY KEY,
                created_at      TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                current_capital REAL NOT NULL
            )
            """
        )

    # ------------------------------------------------------------------
    # 2. positions — add missing columns
    # ------------------------------------------------------------------
    pos_cols = _table_columns(conn, "positions")
    _add_if_missing: list[tuple[str, str, str]] = [
        ("positions", "bot_id", "TEXT NOT NULL DEFAULT ''"),
        ("trades",    "bot_id", "TEXT NOT NULL DEFAULT ''"),
        ("trades",    "reason", "TEXT NOT NULL DEFAULT 'signal'"),
    ]
    trade_cols = _table_columns(conn, "trades")
    col_cache: dict[str, set[str]] = {"positions": pos_cols, "trades": trade_cols}

    for table, column, definition in _add_if_missing:
        existing = col_cache.get(table, set())
        if not existing:
            # Table does not exist yet; DDL will create it with the correct schema.
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            logger.info("Schema migration: added %s.%s", table, column)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db(bots: "dict[str, BotConfig]") -> None:
    """
    Create all tables and seed one portfolio row per bot if not already present.

    Safe to call multiple times — idempotent for both fresh and existing databases.

    Parameters
    ----------
    bots:
        The full ``BOTS`` registry from ``paper_trader.bots``.
    """
    try:
        with _connect() as conn:
            # Migration must run *before* CREATE TABLE IF NOT EXISTS so that
            # a legacy portfolio table is dropped first (otherwise the DDL
            # no-ops and the bad schema persists).
            _migrate_schema(conn)
            conn.executescript(_DDL)

            now = datetime.now(tz=timezone.utc).isoformat()
            for bot_id, cfg in bots.items():
                existing = conn.execute(
                    "SELECT 1 FROM portfolio WHERE bot_id = ?", (bot_id,)
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO portfolio"
                        " (bot_id, created_at, initial_capital, current_capital)"
                        " VALUES (?, ?, ?, ?)",
                        (bot_id, now, cfg.initial_capital, cfg.initial_capital),
                    )
    except sqlite3.Error as exc:
        logger.error("init_db failed: %s", exc)


# ---------------------------------------------------------------------------
# Portfolio queries / mutations
# ---------------------------------------------------------------------------


def get_portfolio(bot_id: str) -> dict[str, Any]:
    """Return the portfolio row for ``bot_id`` as a dict, or ``{}`` on failure."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio WHERE bot_id = ?", (bot_id,)
            ).fetchone()
            return dict(row) if row else {}
    except sqlite3.Error as exc:
        logger.error("get_portfolio(%s) failed: %s", bot_id, exc)
        return {}


def update_capital(bot_id: str, new_capital: float) -> None:
    """Overwrite ``current_capital`` for the given bot."""
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE portfolio SET current_capital = ? WHERE bot_id = ?",
                (new_capital, bot_id),
            )
    except sqlite3.Error as exc:
        logger.error("update_capital(%s) failed: %s", bot_id, exc)


def get_all_portfolios() -> list[dict[str, Any]]:
    """
    Return one summary dict per bot, including live stats from positions/trades.

    Keys per row
    ------------
    bot_id, created_at, initial_capital, current_capital,
    num_open_positions (int), num_closed_trades (int), win_rate (float 0–100).
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio ORDER BY bot_id"
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                bot_id: str = row["bot_id"]
                num_open: int = conn.execute(
                    "SELECT COUNT(*) FROM positions"
                    " WHERE bot_id = ? AND status = 'open'",
                    (bot_id,),
                ).fetchone()[0]
                num_closed: int = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE bot_id = ?", (bot_id,)
                ).fetchone()[0]
                num_wins: int = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE bot_id = ? AND pnl > 0",
                    (bot_id,),
                ).fetchone()[0]
                win_rate: float = (
                    num_wins / num_closed * 100.0 if num_closed > 0 else 0.0
                )
                d = dict(row)
                d.update(
                    {
                        "num_open_positions": num_open,
                        "num_closed_trades": num_closed,
                        "win_rate": win_rate,
                    }
                )
                result.append(d)
            return result
    except sqlite3.Error as exc:
        logger.error("get_all_portfolios failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Position operations
# ---------------------------------------------------------------------------


def open_position(
    bot_id: str,
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
                " (bot_id, symbol, source, entry_price, shares, entry_date, strategy, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
                (bot_id, symbol, source, entry_price, shares, now, strategy),
            )
            return cursor.lastrowid or -1
    except sqlite3.Error as exc:
        logger.error("open_position(%s, %s) failed: %s", bot_id, symbol, exc)
        return -1


def close_position(
    position_id: int,
    exit_price: float,
    reason: str = "signal",
) -> dict[str, Any]:
    """
    Mark a position as closed, record the trade, and return the trade dict.

    Parameters
    ----------
    position_id:
        Primary key of the open position row.
    exit_price:
        Price at which the position is closed.
    reason:
        Exit reason — ``"signal"``, ``"stop_loss"``, or ``"take_profit"``.

    Returns
    -------
    dict with all trade fields, or ``{}`` if the position is not found.
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
                " (bot_id, symbol, source, strategy, entry_price, exit_price, shares,"
                "  entry_date, exit_date, pnl, pnl_pct, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pos["bot_id"],
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
                    reason,
                ),
            )
            conn.execute(
                "UPDATE positions SET status = 'closed' WHERE id = ?",
                (position_id,),
            )

            return {
                "bot_id": pos["bot_id"],
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
                "reason": reason,
            }
    except sqlite3.Error as exc:
        logger.error("close_position(%d) failed: %s", position_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Read-only queries
# ---------------------------------------------------------------------------


def get_open_positions(bot_id: str) -> list[dict[str, Any]]:
    """Return all open positions for ``bot_id``, ordered by entry date."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions"
                " WHERE bot_id = ? AND status = 'open'"
                " ORDER BY entry_date",
                (bot_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_open_positions(%s) failed: %s", bot_id, exc)
        return []


def get_trade_history(bot_id: str) -> list[dict[str, Any]]:
    """Return all closed trades for ``bot_id``, newest first."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE bot_id = ? ORDER BY exit_date DESC",
                (bot_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("get_trade_history(%s) failed: %s", bot_id, exc)
        return []

