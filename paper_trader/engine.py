"""
paper_trader.engine
===================
Main scheduling loop for the paper trading engine.

Runs ``check_and_execute`` every 4 hours using the ``schedule`` library.
Each action is logged to stdout with a UTC timestamp.  All exceptions are
caught and logged so a transient network or data error never terminates the
loop.

Usage
-----
    python -m paper_trader.engine          # from project root
    python paper_trader/engine.py          # from project root

The engine is intentionally a standalone process; it does not require the
Streamlit server to be running.  The Streamlit monitor reads the same
SQLite database and reflects the state written by this process.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — must happen before any trd_auto or paper_trader imports.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_TRDAUTO = os.path.join(_PROJECT_ROOT, "trd_auto")

for _p in (_PROJECT_ROOT, _TRDAUTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Third-party / project imports (after path setup)
# ---------------------------------------------------------------------------
import schedule  # noqa: E402

from paper_trader.executor import check_and_execute  # noqa: E402
from paper_trader.portfolio import Portfolio  # noqa: E402

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s UTC  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paper_trader.engine")

# ---------------------------------------------------------------------------
# Shared portfolio instance (created once; all state lives in SQLite)
# ---------------------------------------------------------------------------
_portfolio: Portfolio = Portfolio(initial_capital=10_000.0)


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------


def _run_cycle() -> None:
    """Execute one signal-scan cycle and log every action."""
    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info("=== Cycle start  %s ===", now_utc)

    try:
        actions: list[dict[str, Any]] = check_and_execute(_portfolio)
    except Exception as exc:
        logger.exception("check_and_execute raised an unexpected error: %s", exc)
        return

    if not actions:
        logger.info("No actions taken this cycle.")
    else:
        for action in actions:
            _log_action(action)

    logger.info("=== Cycle end    %s ===", now_utc)


def _log_action(action: dict[str, Any]) -> None:
    """Format and emit a single action as an INFO log line."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    verb = action.get("action", "?").upper()
    label = action.get("label", action.get("symbol", "?"))
    price = action.get("price", float("nan"))
    score = action.get("score", "?")

    if verb == "BUY":
        shares = action.get("shares", float("nan"))
        alloc = action.get("allocation", float("nan"))
        logger.info(
            "[%s]  BUY   %-20s  score=%s  shares=%.6f  @%.4f  cost=%.2f",
            ts,
            label,
            score,
            shares,
            price,
            alloc,
        )
    elif verb == "SELL":
        pnl = action.get("pnl", float("nan"))
        pnl_pct = action.get("pnl_pct", float("nan"))
        logger.info(
            "[%s]  SELL  %-20s  score=%s  @%.4f  pnl=%.2f (%.2f%%)",
            ts,
            label,
            score,
            price,
            pnl,
            pnl_pct,
        )
    else:
        logger.info("[%s]  %s  %s", ts, verb, action)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Bootstrap the scheduler and block forever."""
    logger.info("Paper trading engine starting.  Initial capital: %.2f", _portfolio.cash)

    # Run once immediately on startup, then every 4 hours.
    _run_cycle()
    schedule.every(4).hours.do(_run_cycle)

    logger.info("Scheduler active — next run in 4 hours.  Press Ctrl+C to stop.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Engine stopped by user.")
            break
        except Exception as exc:
            logger.exception("Unexpected error in scheduler loop: %s", exc)
            # Continue running after logging the error.
            time.sleep(60)


if __name__ == "__main__":
    main()
