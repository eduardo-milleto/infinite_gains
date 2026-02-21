from __future__ import annotations

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config.settings import get_settings
from src.core.logging import configure_logging
from src.db.engine import Database
from src.services.openclaw.analyzer import OpenClawAnalyzer

logger = structlog.get_logger(__name__)


async def run_cycle() -> None:
    settings = get_settings()
    database = Database(settings)
    analyzer = OpenClawAnalyzer(settings, database)
    created = await analyzer.run_cycle()
    logger.info("openclaw_scheduled_cycle", created=created)
    await database.dispose()


async def _run() -> None:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_cycle, IntervalTrigger(hours=settings.openclaw_schedule_hours))
    scheduler.start()

    logger.info("openclaw_service_started", every_hours=settings.openclaw_schedule_hours)
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
