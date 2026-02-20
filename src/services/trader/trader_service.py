from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from time import perf_counter
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from src.config.settings import Settings
from src.core.clock import utc_now
from src.core.enums import OrderStatus, ProposalStatus, SignalType
from src.core.exceptions import APIFailureError, MarketDiscoveryError, RiskVetoError
from src.db.engine import Database
from src.db.repository import ConfigRepo, MarketSessionRepo, SignalRepo, TradeRepo
from src.services.execution.order_manager import OrderManager
from src.services.indicators.signal_engine import SignalEngine
from src.services.indicators.taapi_client import TaapiClient
from src.services.market_discovery.market_finder import MarketFinder
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker
from src.services.risk.risk_engine import RiskEngine

logger = structlog.get_logger(__name__)

TRADES_TOTAL = Counter("trades_total", "Total orders submitted")
TRADES_WON = Counter("trades_won", "Total won trades")
TRADES_LOST = Counter("trades_lost", "Total lost trades")
PNL_USDC_TOTAL = Gauge("pnl_usdc_total", "Accumulated pnl in USDC")
SIGNALS_EVALUATED = Counter("signals_evaluated", "Signals evaluated")
SIGNALS_VETOED = Counter("signals_vetoed", "Signals vetoed by risk")
KILL_SWITCH_ACTIVE = Gauge("kill_switch_active", "Kill switch state (0/1)")
API_ERRORS_TOTAL = Counter("api_errors_total", "External API errors")
WS_RECONNECTS = Counter("ws_reconnects", "Websocket reconnects")
INDICATOR_FETCH_SECONDS = Histogram("indicator_fetch_seconds", "Time to fetch TA indicators")
ORDER_PLACEMENT_SECONDS = Histogram("order_placement_seconds", "Time to place order")
DAILY_LOSS_USDC = Gauge("daily_loss_usdc", "Current daily loss in USDC")
TRADES_TODAY = Gauge("trades_today", "Current trades today")
OPEN_POSITIONS = Gauge("open_positions", "Current open positions")

AlertCallback = Callable[[str], Awaitable[None]]


class TraderService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        market_finder: MarketFinder,
        taapi_client: TaapiClient,
        signal_engine: SignalEngine,
        risk_engine: RiskEngine,
        order_manager: OrderManager,
        kill_switch: KillSwitch,
        position_tracker: PositionTracker,
        alert_callback: AlertCallback | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._market_finder = market_finder
        self._taapi_client = taapi_client
        self._signal_engine = signal_engine
        self._risk_engine = risk_engine
        self._order_manager = order_manager
        self._kill_switch = kill_switch
        self._position_tracker = position_tracker
        self._alert_callback = alert_callback
        self._metrics_started = False

    async def run_forever(self) -> None:
        if not self._metrics_started:
            start_http_server(self._settings.metrics_port)
            self._metrics_started = True

        while True:
            loop_started = perf_counter()
            try:
                await self.run_tick()
            except Exception as exc:
                await self._trip_kill_switch(f"Unhandled tick error: {exc}")
                logger.exception("tick_failure", error=str(exc))

            elapsed = perf_counter() - loop_started
            sleep_for = max(0.0, self._settings.scheduler_poll_interval_secs - elapsed)
            await asyncio.sleep(sleep_for)

    async def run_tick(self) -> None:
        await self._sync_control_state()
        now_utc = utc_now()
        KILL_SWITCH_ACTIVE.set(1 if self._kill_switch.is_tripped else 0)

        try:
            market_context = await self._market_finder.discover_next_market(now_utc=now_utc)
        except MarketDiscoveryError as exc:
            API_ERRORS_TOTAL.inc()
            await self._trip_kill_switch(f"Market discovery failure: {exc}")
            raise

        try:
            fetch_started = perf_counter()
            snapshot = await self._taapi_client.fetch_snapshot()
            INDICATOR_FETCH_SECONDS.observe(perf_counter() - fetch_started)
        except APIFailureError as exc:
            API_ERRORS_TOTAL.inc()
            await self._trip_kill_switch(f"TAAPI failure: {exc}")
            raise

        signal = self._signal_engine.evaluate(snapshot)
        SIGNALS_EVALUATED.inc()

        async with self._database.session() as session:
            signal_repo = SignalRepo(session)
            trade_repo = TradeRepo(session)
            market_session_repo = MarketSessionRepo(session)

            signal_row = await signal_repo.create(
                snapshot=snapshot,
                signal_type=signal.signal_type,
                filter_result=None,
                market_slug=market_context.market_slug,
                spread_at_eval=market_context.spread,
                trading_mode=self._settings.trading_mode,
            )

            await market_session_repo.upsert(
                candle_open_utc=snapshot.candle_open_utc,
                market_slug=market_context.market_slug,
                condition_id=market_context.condition_id,
                token_id_up=market_context.token_id_up,
                token_id_down=market_context.token_id_down,
                resolution_source=market_context.resolution_source,
                tick_size=market_context.tick_size,
                market_end_time=market_context.market_end_time,
            )

            if signal.signal_type == SignalType.NONE:
                signal_row.filter_result = signal.reason
                logger.info("no_signal", reason=signal.reason)
                return

            try:
                approved_size = await self._risk_engine.approve_trade(
                    signal=signal,
                    market_context=market_context,
                    now_utc=now_utc,
                    trade_repo=trade_repo,
                )
            except RiskVetoError as exc:
                SIGNALS_VETOED.inc()
                signal_row.filter_result = str(exc)
                logger.info("trade_vetoed", reason=str(exc), signal_type=signal.signal_type.value)
                return

            direction = signal.direction
            if direction is None:
                SIGNALS_VETOED.inc()
                signal_row.filter_result = "Direction resolution failed"
                return

            order_started = perf_counter()
            order_result = await self._order_manager.place_entry_order(
                direction=direction,
                size_usdc=approved_size,
                market_context=market_context,
            )
            ORDER_PLACEMENT_SECONDS.observe(perf_counter() - order_started)

            trade_row = await trade_repo.create(
                signal_id=signal_row.id,
                market_slug=market_context.market_slug,
                condition_id=market_context.condition_id,
                candle_open_utc=snapshot.candle_open_utc,
                trading_mode=self._settings.trading_mode,
                order_result=order_result,
            )

            if order_result.status == OrderStatus.SUBMITTED:
                self._position_tracker.register_trade(snapshot.candle_open_utc, now_utc)
                self._position_tracker.register_open_position()
                TRADES_TOTAL.inc()
                TRADES_TODAY.set(self._position_tracker.trades_today)
                OPEN_POSITIONS.set(self._position_tracker.open_positions)
                DAILY_LOSS_USDC.set(max(0.0, float(-self._position_tracker.daily_pnl)))
                logger.info(
                    "order_submitted",
                    trade_id=trade_row.id,
                    order_id=order_result.order_id,
                    direction=direction.value,
                    size_usdc=str(order_result.size_usdc),
                )
                if self._alert_callback is not None:
                    await self._alert_callback(
                        f"Trade submitted [{self._settings.trading_mode.value}] {direction.value} "
                        f"{market_context.market_slug} size={order_result.size_usdc} order={order_result.order_id}"
                    )
            else:
                SIGNALS_VETOED.inc()
                signal_row.filter_result = order_result.failure_reason or "Order submission failed"
                logger.error("order_failed", reason=order_result.failure_reason, raw=order_result.raw_response)

    async def _trip_kill_switch(self, reason: str) -> None:
        await self._kill_switch.trip(reason)
        KILL_SWITCH_ACTIVE.set(1)
        if self._alert_callback is not None:
            await self._alert_callback(f"Kill switch TRIPPED: {reason}")

    async def _sync_control_state(self) -> None:
        async with self._database.session() as session:
            config_repo = ConfigRepo(session)
            command = await config_repo.get_latest_value(
                config_section="control",
                param_key="kill_switch_state",
                status=ProposalStatus.APPROVED,
            )

        if command == "TRIPPED" and not self._kill_switch.is_tripped:
            await self._kill_switch.trip("Paused via Telegram control command")
        if command == "RESET" and self._kill_switch.is_tripped:
            await self._kill_switch.reset()

    async def handle_fill_event(self, event: dict[str, Any]) -> None:
        order_id = str(event.get("orderID") or event.get("orderId") or event.get("order_id") or "")
        if not order_id:
            return

        status_raw = str(event.get("status") or "").lower()
        status = self._map_fill_status(status_raw)
        if status is None:
            return

        size_filled = Decimal(str(event.get("sizeFilled") or event.get("filled_size") or event.get("size") or "0"))
        pnl_usdc = Decimal(str(event.get("pnl") or "0"))
        fees_usdc = Decimal(str(event.get("fees") or "0"))
        resolved_direction = str(event.get("resolvedDirection") or event.get("resolved_direction") or "")
        resolved_direction_value = resolved_direction if resolved_direction else None

        async with self._database.session() as session:
            trade_repo = TradeRepo(session)
            trade = await trade_repo.update_by_order_id(
                order_id,
                status=status,
                size_filled_usdc=size_filled,
                raw_fill_event=event,
                pnl_usdc=pnl_usdc,
                fees_usdc=fees_usdc,
                resolved_direction=resolved_direction_value,
            )

        if trade is None:
            return

        if status in {OrderStatus.MATCHED, OrderStatus.CONFIRMED}:
            OPEN_POSITIONS.set(self._position_tracker.open_positions)
        if status == OrderStatus.SETTLED:
            net_pnl = pnl_usdc - fees_usdc
            self._position_tracker.register_closed_position(net_pnl)
            TRADES_WON.inc() if net_pnl > 0 else TRADES_LOST.inc()
            PNL_USDC_TOTAL.set(float(self._position_tracker.daily_pnl))
            OPEN_POSITIONS.set(self._position_tracker.open_positions)
            DAILY_LOSS_USDC.set(max(0.0, float(-self._position_tracker.daily_pnl)))
            if self._alert_callback is not None:
                direction = resolved_direction_value or "UNKNOWN"
                await self._alert_callback(
                    f"Trade settled order={order_id} direction={direction} pnl={net_pnl}"
                )

    @staticmethod
    def _map_fill_status(status_raw: str) -> OrderStatus | None:
        mapping = {
            "matched": OrderStatus.MATCHED,
            "confirmed": OrderStatus.CONFIRMED,
            "settled": OrderStatus.SETTLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "failed": OrderStatus.FAILED,
        }
        return mapping.get(status_raw)
