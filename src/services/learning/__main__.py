from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.settings import get_settings
from src.core.clock import utc_now
from src.core.logging import configure_logging
from src.db.engine import Database
from src.services.learning.approval_workflow import ApprovalWorkflow
from src.services.learning.ai_prompt_advisor import AIPromptAdvisor
from src.services.learning.param_advisor import ParamAdvisor
from src.services.learning.performance_analyzer import PerformanceAnalyzer

logger = structlog.get_logger(__name__)


async def run_daily_cycle() -> None:
    settings = get_settings()
    database = Database(settings)

    async def alert_callback(message: str) -> None:
        logger.info("learning_alert", message=message)

    workflow = ApprovalWorkflow(settings=settings, database=database, alert_callback=alert_callback)
    analyzer = PerformanceAnalyzer(settings)
    advisor = ParamAdvisor(settings)
    ai_advisor = AIPromptAdvisor(settings)

    target_day = (utc_now() - timedelta(days=1)).date()

    async with database.session() as session:
        metrics = await analyzer.analyze_day(metric_day=target_day, session=session)
        ai_proposals, ai_notifications = await ai_advisor.generate(session=session)

    proposals = advisor.generate_proposals(metrics) + ai_proposals
    count = await workflow.stage_proposals(proposals)
    for notification in ai_notifications:
        await alert_callback(notification)
    logger.info("learning_cycle_complete", metric_day=str(target_day), proposals_created=count)

    await database.dispose()


async def _run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_daily_cycle, CronTrigger(hour=0, minute=5))
    scheduler.start()

    logger.info("learning_service_started")
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
