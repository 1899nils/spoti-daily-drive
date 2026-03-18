"""APScheduler setup for daily playlist builds."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .builder import build_playlist
from .config import load_config

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _run_build() -> None:
    logger.info("Scheduler: starting daily playlist build")
    result = build_playlist()
    if result["ok"]:
        logger.info("Scheduler: playlist built — %d items", result["total"])
    else:
        logger.error("Scheduler: build failed — %s", result.get("error"))


def schedule_daily(time_str: str) -> None:
    """Schedule (or reschedule) the daily build at HH:MM."""
    hour, minute = (int(x) for x in time_str.split(":"))
    scheduler.remove_all_jobs()
    scheduler.add_job(
        _run_build,
        CronTrigger(hour=hour, minute=minute),
        id="daily_build",
        replace_existing=True,
    )
    logger.info("Scheduler: daily build set for %02d:%02d", hour, minute)


def start_scheduler() -> None:
    config = load_config()
    schedule_daily(config.get("schedule_time", "06:00"))
    if not scheduler.running:
        scheduler.start()
