from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal

import structlog

from src.config.settings import Settings
from src.core.clock import utc_now
from src.core.enums import ExitMode, OrderStatus, TradeDirection
from src.core.types import ExitParameters
from src.db.engine import Database
from src.db.repository import TradeRepo
from src.services.execution.exit_engine import ExitEngine
from src.services.execution.order_manager import OrderManager
from src.services.indicators.signal_engine import SignalEngine
from src.services.indicators.taapi_client import TaapiClient

logger = structlog.get_logger(__name__)

OnExitCallback = Callable[[int, Decimal, str], Awaitable[None]]
AlertCallback = Callable[[str], Awaitable[None]]


class PositionMonitor:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        order_manager: OrderManager,
        exit_engine: ExitEngine,
        taapi_client: TaapiClient,
        signal_engine: SignalEngine,
        on_exit_callback: OnExitCallback | None = None,
        alert_callback: AlertCallback | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._order_manager = order_manager
        self._exit_engine = exit_engine
        self._taapi_client = taapi_client
        self._signal_engine = signal_engine
        self._on_exit_callback = on_exit_callback
        self._alert_callback = alert_callback
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def set_on_exit_callback(self, callback: OnExitCallback | None) -> None:
        self._on_exit_callback = callback

    async def start(
        self,
        *,
        trade_id: int,
        market_end_time: datetime,
        exit_parameters: ExitParameters,
    ) -> None:
        if self._settings.exit_mode == ExitMode.HOLD:
            return
        task = self._tasks.get(trade_id)
        if task is not None and not task.done():
            return
        self._tasks[trade_id] = asyncio.create_task(
            self._run_loop(
                trade_id=trade_id,
                market_end_time=market_end_time,
                exit_parameters=exit_parameters,
            ),
            name=f"position-monitor-{trade_id}",
        )

    async def stop_all(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _run_loop(
        self,
        *,
        trade_id: int,
        market_end_time: datetime,
        exit_parameters: ExitParameters,
    ) -> None:
        try:
            while True:
                trade = await self._load_trade(trade_id)
                if trade is None:
                    return
                if trade.status not in {
                    OrderStatus.SUBMITTED.value,
                    OrderStatus.MATCHED.value,
                    OrderStatus.CONFIRMED.value,
                }:
                    return

                current_price = await self._order_manager.get_token_price(trade.token_id)
                reversal = False
                if exit_parameters.exit_on_signal_reversal:
                    reversal = await self._detect_reversal(trade.direction)

                decision = self._exit_engine.evaluate(
                    trade=trade,
                    current_price=current_price,
                    market_end_time=market_end_time,
                    now_utc=utc_now(),
                    exit_parameters=exit_parameters,
                    reversal_detected=reversal,
                )

                if decision.should_exit and decision.reason is not None:
                    await self._execute_exit(
                        trade_id=trade_id,
                        current_price=current_price,
                        reason=decision.reason.value,
                        pnl_usdc=decision.pnl_usdc,
                        hold_duration_secs=decision.hold_duration_secs,
                    )
                    return

                await asyncio.sleep(self._settings.position_monitor_interval_secs)
        finally:
            self._tasks.pop(trade_id, None)

    async def _load_trade(self, trade_id: int):
        async with self._database.session() as session:
            repo = TradeRepo(session)
            return await repo.get_by_id(trade_id)

    async def _detect_reversal(self, direction_raw: str) -> bool:
        try:
            snapshot = await self._taapi_client.fetch_snapshot()
        except Exception:
            return False
        signal = self._signal_engine.evaluate(snapshot)
        direction = signal.direction
        if direction is None:
            return False
        trade_direction = TradeDirection(direction_raw)
        return direction != trade_direction

    async def _execute_exit(
        self,
        *,
        trade_id: int,
        current_price: Decimal,
        reason: str,
        pnl_usdc: Decimal,
        hold_duration_secs: int,
    ) -> None:
        trade = await self._load_trade(trade_id)
        if trade is None:
            return

        exit_requested_at = utc_now()
        exit_order = await self._order_manager.place_exit_order(
            trade=trade,
            exit_price=current_price,
        )
        exit_confirmed_at = utc_now()

        async with self._database.session() as session:
            repo = TradeRepo(session)
            updated = await repo.update_exit(
                trade_id=trade_id,
                price_exit=current_price,
                exit_reason=reason,
                exit_requested_at=exit_requested_at,
                exit_confirmed_at=exit_confirmed_at,
                hold_duration_secs=hold_duration_secs,
                exit_order_id=exit_order.order_id,
                pnl_usdc=pnl_usdc,
            )

        if updated is None:
            return

        if self._on_exit_callback is not None:
            await self._on_exit_callback(trade_id, pnl_usdc, reason)

        if self._alert_callback is not None:
            await self._alert_callback(
                f"Exit executed trade_id={trade_id} reason={reason} "
                f"price_exit={current_price} pnl={pnl_usdc}"
            )

        logger.info(
            "position_exit_executed",
            trade_id=trade_id,
            reason=reason,
            price_exit=str(current_price),
            pnl_usdc=str(pnl_usdc),
        )
