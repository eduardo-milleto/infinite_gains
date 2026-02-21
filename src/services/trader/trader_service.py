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
from src.core.enums import AIFallbackMode, ExitMode, ExitReason, OrderStatus, ProposalStatus, SignalType
from src.core.exceptions import APIFailureError, MarketDiscoveryError, RiskVetoError
from src.core.types import AIDecision
from src.db.engine import Database
from src.db.repository import ConfigRepo, MarketSessionRepo, SignalRepo, TradeRepo
from src.services.ai.decision_engine import DecisionEngine
from src.services.execution.exit_engine import ExitEngine
from src.services.execution.order_manager import OrderManager
from src.services.execution.position_monitor import PositionMonitor
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
        exit_engine: ExitEngine | None,
        position_monitor: PositionMonitor | None,
        kill_switch: KillSwitch,
        position_tracker: PositionTracker,
        decision_engine: DecisionEngine | None = None,
        alert_callback: AlertCallback | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._market_finder = market_finder
        self._taapi_client = taapi_client
        self._signal_engine = signal_engine
        self._risk_engine = risk_engine
        self._order_manager = order_manager
        self._exit_engine = exit_engine
        self._position_monitor = position_monitor
        self._kill_switch = kill_switch
        self._position_tracker = position_tracker
        self._decision_engine = decision_engine
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

            ai_decision: AIDecision | None = None
            ai_decision_id: int | None = None
            if self._decision_engine is not None:
                ai_decision, ai_decision_id = await self._decision_engine.evaluate(
                    signal_id=signal_row.id,
                    signal=signal,
                    market_context=market_context,
                    now_utc=now_utc,
                    session=session,
                )
                if not self._ai_gate_passed(ai_decision):
                    SIGNALS_VETOED.inc()
                    signal_row.filter_result = (
                        f"AI veto: proceed={ai_decision.proceed} edge={ai_decision.edge} "
                        f"confidence={ai_decision.confidence}"
                    )
                    logger.info(
                        "ai_veto",
                        signal_id=signal_row.id,
                        proceed=ai_decision.proceed,
                        edge=str(ai_decision.edge),
                        confidence=ai_decision.confidence,
                        fallback=ai_decision.fallback_used,
                    )
                    if (
                        self._settings.ai_fallback_mode == AIFallbackMode.TELEGRAM
                        and self._alert_callback is not None
                    ):
                        await self._alert_callback(
                            f"AI review required for signal={signal_row.id}: {ai_decision.reasoning}"
                        )
                    return

            try:
                risk_approved_size = await self._risk_engine.approve_trade(
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

            approved_size = risk_approved_size
            if ai_decision is not None:
                approved_size = self._apply_ai_position_modulation(risk_approved_size, ai_decision)

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
            if ai_decision_id is not None and self._decision_engine is not None:
                await self._decision_engine.link_trade(
                    session=session,
                    ai_decision_id=ai_decision_id,
                    trade_id=trade_row.id,
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
                if (
                    self._settings.exit_mode == ExitMode.SCALP
                    and self._position_monitor is not None
                    and self._exit_engine is not None
                ):
                    exit_parameters = self._exit_engine.resolve_exit_parameters(ai_decision)
                    await self._position_monitor.start(
                        trade_id=trade_row.id,
                        market_end_time=market_context.market_end_time,
                        exit_parameters=exit_parameters,
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
            kill_switch_command = await config_repo.get_latest_value(
                config_section="control",
                param_key="kill_switch_state",
                status=ProposalStatus.APPROVED,
            )
            ai_enabled_raw = await config_repo.get_latest_value(
                config_section="ai",
                param_key="minimax_enabled",
                status=ProposalStatus.APPROVED,
            )
            ai_min_edge_raw = await config_repo.get_latest_value(
                config_section="ai",
                param_key="ai_min_edge",
                status=ProposalStatus.APPROVED,
            )
            ai_min_confidence_raw = await config_repo.get_latest_value(
                config_section="ai",
                param_key="ai_min_confidence",
                status=ProposalStatus.APPROVED,
            )
            ai_fallback_mode_raw = await config_repo.get_latest_value(
                config_section="ai",
                param_key="ai_fallback_mode",
                status=ProposalStatus.APPROVED,
            )
            exit_mode_raw = await config_repo.get_latest_value(
                config_section="exit",
                param_key="exit_mode",
                status=ProposalStatus.APPROVED,
            )
            exit_profit_raw = await config_repo.get_latest_value(
                config_section="exit",
                param_key="exit_profit_target_cents",
                status=ProposalStatus.APPROVED,
            )
            exit_stop_raw = await config_repo.get_latest_value(
                config_section="exit",
                param_key="exit_stop_loss_cents",
                status=ProposalStatus.APPROVED,
            )
            exit_reversal_raw = await config_repo.get_latest_value(
                config_section="exit",
                param_key="exit_on_signal_reversal",
                status=ProposalStatus.APPROVED,
            )

        if kill_switch_command == "TRIPPED" and not self._kill_switch.is_tripped:
            await self._kill_switch.trip("Paused via Telegram control command")
        if kill_switch_command == "RESET" and self._kill_switch.is_tripped:
            await self._kill_switch.reset()
        if ai_enabled_raw is not None:
            self._settings.minimax_enabled = ai_enabled_raw.lower() in {"true", "1", "yes", "on"}
        if ai_min_edge_raw is not None:
            try:
                self._settings.ai_min_edge = Decimal(ai_min_edge_raw)
            except Exception:
                logger.warning("invalid_ai_min_edge", value=ai_min_edge_raw)
        if ai_min_confidence_raw is not None:
            try:
                self._settings.ai_min_confidence = int(ai_min_confidence_raw)
            except Exception:
                logger.warning("invalid_ai_min_confidence", value=ai_min_confidence_raw)
        if ai_fallback_mode_raw is not None:
            try:
                self._settings.ai_fallback_mode = AIFallbackMode(ai_fallback_mode_raw)
            except Exception:
                logger.warning("invalid_ai_fallback_mode", value=ai_fallback_mode_raw)
        if exit_mode_raw is not None:
            try:
                self._settings.exit_mode = ExitMode(exit_mode_raw)
            except Exception:
                logger.warning("invalid_exit_mode", value=exit_mode_raw)
        if exit_profit_raw is not None:
            try:
                self._settings.exit_profit_target_cents = int(exit_profit_raw)
            except Exception:
                logger.warning("invalid_exit_profit_target_cents", value=exit_profit_raw)
        if exit_stop_raw is not None:
            try:
                self._settings.exit_stop_loss_cents = int(exit_stop_raw)
            except Exception:
                logger.warning("invalid_exit_stop_loss_cents", value=exit_stop_raw)
        if exit_reversal_raw is not None:
            self._settings.exit_on_signal_reversal = exit_reversal_raw.lower() in {"true", "1", "yes", "on"}

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
        fill_price_raw = event.get("price") or event.get("avg_price") or event.get("matched_price")
        price_exit = Decimal(str(fill_price_raw)) if fill_price_raw is not None else None

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
                price_exit=price_exit,
                exit_reason=ExitReason.RESOLUTION.value if status == OrderStatus.SETTLED else None,
                exit_confirmed_at=utc_now() if status == OrderStatus.SETTLED else None,
            )
            if status == OrderStatus.SETTLED and trade is not None and self._decision_engine is not None:
                net_pnl = pnl_usdc - fees_usdc
                await self._decision_engine.settle_trade_outcome(
                    session=session,
                    trade_id=trade.id,
                    outcome_pnl=net_pnl,
                    settled_at=utc_now(),
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

    async def handle_position_exit(self, trade_id: int, pnl_usdc: Decimal, reason: str) -> None:
        self._position_tracker.register_closed_position(pnl_usdc)
        TRADES_WON.inc() if pnl_usdc > 0 else TRADES_LOST.inc()
        PNL_USDC_TOTAL.set(float(self._position_tracker.daily_pnl))
        OPEN_POSITIONS.set(self._position_tracker.open_positions)
        DAILY_LOSS_USDC.set(max(0.0, float(-self._position_tracker.daily_pnl)))

        if self._decision_engine is not None:
            async with self._database.session() as session:
                await self._decision_engine.settle_trade_outcome(
                    session=session,
                    trade_id=trade_id,
                    outcome_pnl=pnl_usdc,
                    settled_at=utc_now(),
                )

        if self._alert_callback is not None:
            await self._alert_callback(
                f"Position closed trade_id={trade_id} reason={reason} pnl={pnl_usdc}"
            )

    def _ai_gate_passed(self, decision: AIDecision) -> bool:
        if (
            decision.fallback_used
            and self._settings.ai_fallback_mode == AIFallbackMode.PROCEED
            and decision.proceed
        ):
            return True
        if not decision.proceed:
            return False
        if decision.edge < self._settings.ai_min_edge:
            return False
        if decision.confidence < self._settings.ai_min_confidence:
            return False
        return True

    def _apply_ai_position_modulation(self, risk_approved_size: Decimal, decision: AIDecision) -> Decimal:
        min_edge = self._settings.ai_min_edge if self._settings.ai_min_edge > 0 else Decimal("0.01")
        edge_factor = self._clamp_decimal(decision.edge / min_edge, Decimal("0.5"), Decimal("1.0"))
        confidence_factor = self._clamp_decimal(
            Decimal(decision.confidence) / Decimal("100"),
            Decimal("0.5"),
            Decimal("1.0"),
        )
        ai_factor = self._clamp_decimal(decision.position_size_factor, Decimal("0.5"), Decimal("1.0"))
        final_factor = self._clamp_decimal(
            edge_factor * confidence_factor * ai_factor,
            Decimal("0.5"),
            Decimal("1.0"),
        )
        modulated = (risk_approved_size * final_factor).quantize(Decimal("0.01"))
        return min(risk_approved_size, modulated)

    @staticmethod
    def _clamp_decimal(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

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
