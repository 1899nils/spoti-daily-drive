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


def schedule_all(times: list[str]) -> None:
    """Replace all scheduled builds with jobs for each HH:MM in times."""
    scheduler.remove_all_jobs()
    for i, time_str in enumerate(times):
        hour, minute = (int(x) for x in time_str.split(":"))
        scheduler.add_job(
            _run_build,
            CronTrigger(hour=hour, minute=minute),
            id=f"daily_build_{i}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Scheduler: build scheduled at %02d:%02d", hour, minute)


def start_scheduler() -> None:
    config = load_config()
    schedule_all(config.get("schedule_times", ["06:00"]))
    if not scheduler.running:
        scheduler.start()
