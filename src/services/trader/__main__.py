from __future__ import annotations

import asyncio

import structlog

from src.config.settings import get_settings
from src.core.logging import configure_logging
from src.db.engine import Database
from src.services.execution.clob_client import ClobClientWrapper
from src.services.execution.order_manager import OrderManager
from src.services.execution.paper_trader import PaperTrader
from src.services.execution.ws_fill_tracker import WSFillTracker
from src.services.indicators.signal_engine import SignalEngine
from src.services.indicators.taapi_client import TaapiClient
from src.services.market_discovery.gamma_client import GammaClient
from src.services.market_discovery.market_finder import MarketFinder
from src.services.market_discovery.market_validator import MarketValidator
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker
from src.services.risk.risk_engine import RiskEngine
from src.services.trader.trader_service import TraderService, WS_RECONNECTS

logger = structlog.get_logger(__name__)


async def _run() -> None:
    settings = get_settings()
    database = Database(settings)
    gamma_client = GammaClient()
    taapi_client = TaapiClient(settings)
    position_tracker = PositionTracker()

    async def on_kill_switch(reason: str, tripped_at) -> None:
        logger.error("kill_switch_tripped", reason=reason, tripped_at=tripped_at.isoformat())

    kill_switch = KillSwitch(on_trip=on_kill_switch)

    validator = MarketValidator(settings)
    market_finder = MarketFinder(gamma_client, validator)
    signal_engine = SignalEngine(settings)
    risk_engine = RiskEngine(settings, kill_switch, position_tracker)

    ws_fill_tracker: WSFillTracker | None = None
    if settings.is_live:
        execution_client = ClobClientWrapper(settings)
    else:
        execution_client = PaperTrader()

    order_manager = OrderManager(execution_client)

    async def alert_callback(message: str) -> None:
        logger.info("trader_alert", message=message)

    trader = TraderService(
        settings=settings,
        database=database,
        market_finder=market_finder,
        taapi_client=taapi_client,
        signal_engine=signal_engine,
        risk_engine=risk_engine,
        order_manager=order_manager,
        kill_switch=kill_switch,
        position_tracker=position_tracker,
        alert_callback=alert_callback,
    )

    try:
        if settings.is_live:
            ws_fill_tracker = WSFillTracker(
                ws_url=settings.poly_ws_host,
                api_key=settings.poly_api_key.get_secret_value(),
                api_secret=settings.poly_api_secret.get_secret_value(),
                api_passphrase=settings.poly_api_passphrase.get_secret_value(),
                on_fill_event=trader.handle_fill_event,
                on_reconnect=_on_ws_reconnect,
            )
            await ws_fill_tracker.start()
        await trader.run_forever()
    finally:
        if ws_fill_tracker is not None:
            await ws_fill_tracker.stop()
        await taapi_client.close()
        await gamma_client.close()
        await database.dispose()


async def _on_ws_reconnect() -> None:
    WS_RECONNECTS.inc()
    logger.warning("ws_fill_tracker_reconnect")


def main() -> None:
    configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
