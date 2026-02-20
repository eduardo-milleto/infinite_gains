from __future__ import annotations

import asyncio

import structlog

from src.config.settings import get_settings
from src.core.logging import configure_logging
from src.db.engine import Database
from src.services.learning.approval_workflow import ApprovalWorkflow
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker
from src.services.telegram.bot import build_application
from src.services.telegram.commands import CommandDependencies

logger = structlog.get_logger(__name__)


async def _run() -> None:
    settings = get_settings()
    database = Database(settings)
    kill_switch = KillSwitch()
    position_tracker = PositionTracker()

    async def alert_callback(message: str) -> None:
        logger.info("telegram_alert", message=message)

    workflow = ApprovalWorkflow(settings=settings, database=database, alert_callback=alert_callback)

    deps = CommandDependencies(
        settings=settings,
        database=database,
        kill_switch=kill_switch,
        position_tracker=position_tracker,
        approval_workflow=workflow,
    )

    app = build_application(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        deps=deps,
    )

    logger.info("telegram_bot_started")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await database.dispose()


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
