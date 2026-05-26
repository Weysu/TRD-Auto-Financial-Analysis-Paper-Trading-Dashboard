"""
paper_trader.engine
===================
Multi-bot scheduling loop.

Creates one ``Portfolio`` instance per bot at start-up, then runs a full
signal-scan-and-execute cycle every 4 hours.  Each bot runs sequentially
inside the cycle with a 2-second pause between them; a per-bot try/except
guarantees that one failing bot cannot abort the others.

Entry point
-----------
Run as a module::

    python -m paper_trader.engine

or, via the ``paper_engine`` Docker service::

    python -m paper_trader.engine
"""

from __future__ import annotations

import logging
import os
import sys
import time

import schedule

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_TRDAUTO = os.path.join(_PROJECT_ROOT, "trd_auto")

for _p in (_PROJECT_ROOT, _TRDAUTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Local imports (after path bootstrap)
# ---------------------------------------------------------------------------
from paper_trader.bots import BOTS  # noqa: E402
from paper_trader.executor import check_and_execute  # noqa: E402
from paper_trader.portfolio import Portfolio  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot portfolio registry (initialised once at startup)
# ---------------------------------------------------------------------------
_portfolios: dict[str, Portfolio] = {}


def _init_portfolios() -> None:
    """Create one Portfolio per bot and register it in ``_portfolios``."""
    for bot_id, bot_cfg in BOTS.items():
        _portfolios[bot_id] = Portfolio(bot_cfg)
    logger.info("Initialised %d bot portfolios.", len(_portfolios))


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------


def _run_cycle() -> None:
    """Execute one full signal-scan cycle across all bots."""
    logger.info("=== Starting trading cycle ===")

    # Shared OHLCV cache for this cycle — avoids redundant API calls across
    # bots that operate on the same (source, symbol, timeframe) combination.
    # The dict is discarded at the end of the function so stale data never
    # carries over to the next cycle.
    ohlcv_cache: dict[tuple[str, str, str], object] = {}

    for bot_id, bot_cfg in BOTS.items():
        portfolio = _portfolios.get(bot_id)
        if portfolio is None:
            logger.error("No portfolio for bot_id=%r — skipping.", bot_id)
            continue

        logger.info("--- Bot: %s (%s) ---", bot_cfg.name, bot_id)
        try:
            actions = check_and_execute(portfolio, bot_cfg, ohlcv_cache=ohlcv_cache)
            if actions:
                for act in actions:
                    logger.info(
                        "[%s] %s %s @ %.4f  score=%s  reason=%s",
                        bot_id,
                        act.get("action", "?").upper(),
                        act.get("symbol", "?"),
                        act.get("price", 0.0),
                        act.get("score"),
                        act.get("reason", "?"),
                    )
            else:
                logger.info("[%s] No trades this cycle.", bot_id)
        except Exception as exc:
            logger.error("[%s] Cycle failed: %s", bot_id, exc, exc_info=True)

        # Brief pause to avoid hammering rate-limited APIs.
        time.sleep(2)

    logger.info("=== Cycle complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Paper trading engine starting up…")
    _init_portfolios()

    # Run immediately on startup so there is data from the first second.
    _run_cycle()

    # Then repeat every 4 hours.
    schedule.every(4).hours.do(_run_cycle)
    logger.info("Scheduler armed — next run in 4 hours.")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

