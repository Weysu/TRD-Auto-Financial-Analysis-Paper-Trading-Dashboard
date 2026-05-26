import logging
import signal
import time

import schedule

from paper_trader.bots import BOTS
from paper_trader.db import init_db
from paper_trader.executor import check_and_execute
from paper_trader.portfolio import Portfolio

logger = logging.getLogger(__name__)


def _make_bot_job(bot_id: str):
    """Return a zero-argument callable that runs one cycle for a single bot."""
    def _job():
        bot_cfg = BOTS[bot_id]
        portfolio = Portfolio(bot_cfg)
        ohlcv_cache: dict = {}
        logger.info("[%s] Cycle starting", bot_id)
        try:
            actions = check_and_execute(portfolio, bot_cfg, ohlcv_cache=ohlcv_cache)
            logger.info("[%s] Cycle complete — %d actions", bot_id, len(actions))
        except Exception as exc:
            logger.error("[%s] Cycle failed: %s", bot_id, exc, exc_info=True)
    return _job


def _setup_schedules() -> None:
    """Register one job per bot using its configured cycle_hours."""
    for bot_id, bot_cfg in BOTS.items():
        job = _make_bot_job(bot_id)
        schedule.every(bot_cfg.cycle_hours).hours.do(job)
        logger.info(
            "[%s] Scheduled every %dh", bot_id, bot_cfg.cycle_hours
        )


def _run_all_immediately() -> None:
    """Run every bot once at startup without waiting for the first scheduled slot."""
    for bot_id in BOTS:
        _make_bot_job(bot_id)()


def _handle_sigterm(signum, frame):
    logger.info("SIGTERM received — shutting down cleanly.")
    raise SystemExit(0)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    signal.signal(signal.SIGTERM, _handle_sigterm)

    init_db()
    _setup_schedules()
    _run_all_immediately()

    logger.info("Engine running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

