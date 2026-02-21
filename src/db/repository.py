from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import OpenClawProposalStatus, OrderStatus, ProposalStatus, SignalType, TradingMode
from src.core.types import AIDecision, IndicatorSnapshot, OrderResult
from src.db.models import (
    AIDecisionModel,
    ConfigHistoryModel,
    MarketSessionModel,
    OpenClawProposalModel,
    PerformanceMetricsModel,
    SignalModel,
    TradeModel,
)


class SignalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        snapshot: IndicatorSnapshot,
        signal_type: SignalType,
        filter_result: str | None,
        market_slug: str,
        spread_at_eval: Decimal | None,
        trading_mode: TradingMode,
    ) -> SignalModel:
        row = SignalModel(
            evaluated_at=snapshot.evaluated_at,
            candle_open_utc=snapshot.candle_open_utc,
            rsi_prev=snapshot.rsi_prev,
            rsi_curr=snapshot.rsi_curr,
            stoch_k_prev=snapshot.stoch_k_prev,
            stoch_d_prev=snapshot.stoch_d_prev,
            stoch_k_curr=snapshot.stoch_k_curr,
            stoch_d_curr=snapshot.stoch_d_curr,
            signal_type=signal_type.value,
            filter_result=filter_result,
            market_slug=market_slug,
            spread_at_eval=spread_at_eval,
            trading_mode=trading_mode.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class TradeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        signal_id: int,
        market_slug: str,
        condition_id: str,
        candle_open_utc: datetime,
        trading_mode: TradingMode,
        order_result: OrderResult,
    ) -> TradeModel:
        row = TradeModel(
            signal_id=signal_id,
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=order_result.token_id,
            direction=order_result.direction.value,
            candle_open_utc=candle_open_utc,
            order_id=order_result.order_id,
            price=order_result.price,
            price_entry=order_result.price,
            size_usdc=order_result.size_usdc,
            size_filled_usdc=order_result.size_filled_usdc,
            status=order_result.status.value,
            failure_reason=order_result.failure_reason,
            trading_mode=trading_mode.value,
            raw_order_response=order_result.raw_response,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_status(
        self,
        trade_id: int,
        status: OrderStatus,
        *,
        size_filled_usdc: Decimal | None = None,
        raw_fill_event: dict[str, object] | None = None,
        pnl_usdc: Decimal | None = None,
        fees_usdc: Decimal | None = None,
        resolved_direction: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        row = await self.session.get(TradeModel, trade_id)
        if row is None:
            return
        row.status = status.value
        if size_filled_usdc is not None:
            row.size_filled_usdc = size_filled_usdc
        if raw_fill_event is not None:
            row.raw_fill_event = raw_fill_event
        if pnl_usdc is not None:
            row.pnl_usdc = pnl_usdc
        if fees_usdc is not None:
            row.fees_usdc = fees_usdc
        if resolved_direction is not None:
            row.resolved_direction = resolved_direction
        if failure_reason is not None:
            row.failure_reason = failure_reason
        await self.session.flush()

    async def update_by_order_id(
        self,
        order_id: str,
        *,
        status: OrderStatus,
        size_filled_usdc: Decimal | None = None,
        raw_fill_event: dict[str, object] | None = None,
        pnl_usdc: Decimal | None = None,
        fees_usdc: Decimal | None = None,
        resolved_direction: str | None = None,
        failure_reason: str | None = None,
        price_exit: Decimal | None = None,
        exit_reason: str | None = None,
        exit_confirmed_at: datetime | None = None,
    ) -> TradeModel | None:
        query = select(TradeModel).where(TradeModel.order_id == order_id).limit(1)
        row = (await self.session.execute(query)).scalars().first()
        if row is None:
            return None
        if row.status == OrderStatus.SETTLED.value and status == OrderStatus.SETTLED:
            return None

        row.status = status.value
        if size_filled_usdc is not None:
            row.size_filled_usdc = size_filled_usdc
        if raw_fill_event is not None:
            row.raw_fill_event = raw_fill_event
        if pnl_usdc is not None:
            row.pnl_usdc = pnl_usdc
        if fees_usdc is not None:
            row.fees_usdc = fees_usdc
        if resolved_direction is not None:
            row.resolved_direction = resolved_direction
        if failure_reason is not None:
            row.failure_reason = failure_reason
        if price_exit is not None:
            row.price_exit = price_exit
        if exit_reason is not None:
            row.exit_reason = exit_reason
        if exit_confirmed_at is not None:
            row.exit_confirmed_at = exit_confirmed_at
        await self.session.flush()
        return row

    async def count_trades_for_day(self, day_utc: date) -> int:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(func.count()).select_from(TradeModel).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        return int((await self.session.execute(query)).scalar_one())

    async def count_open_positions(self) -> int:
        query = select(func.count()).select_from(TradeModel).where(
            TradeModel.status.in_([OrderStatus.SUBMITTED.value, OrderStatus.MATCHED.value, OrderStatus.CONFIRMED.value])
        )
        return int((await self.session.execute(query)).scalar_one())

    async def sum_daily_pnl(self, day_utc: date) -> Decimal:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(func.coalesce(func.sum(TradeModel.pnl_usdc), 0)).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        result = (await self.session.execute(query)).scalar_one()
        return Decimal(str(result))

    async def get_last_trade_time(self) -> datetime | None:
        query = select(func.max(TradeModel.candle_open_utc))
        return (await self.session.execute(query)).scalar_one()

    async def list_settled_for_day(self, day_utc: date) -> list[TradeModel]:
        start = datetime(day_utc.year, day_utc.month, day_utc.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = select(TradeModel).where(
            and_(TradeModel.candle_open_utc >= start, TradeModel.candle_open_utc <= end)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def get_by_id(self, trade_id: int) -> TradeModel | None:
        return await self.session.get(TradeModel, trade_id)

    async def list_open_positions(self) -> list[TradeModel]:
        query = select(TradeModel).where(
            TradeModel.status.in_(
                [
                    OrderStatus.SUBMITTED.value,
                    OrderStatus.MATCHED.value,
                    OrderStatus.CONFIRMED.value,
                ]
            )
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def update_exit(
        self,
        *,
        trade_id: int,
        price_exit: Decimal,
        exit_reason: str,
        exit_requested_at: datetime,
        exit_confirmed_at: datetime,
        hold_duration_secs: int,
        exit_order_id: str | None,
        pnl_usdc: Decimal,
        status: OrderStatus = OrderStatus.SETTLED,
    ) -> TradeModel | None:
        row = await self.session.get(TradeModel, trade_id)
        if row is None:
            return None

        row.price_exit = price_exit
        row.exit_reason = exit_reason
        row.exit_requested_at = exit_requested_at
        row.exit_confirmed_at = exit_confirmed_at
        row.hold_duration_secs = hold_duration_secs
        row.exit_order_id = exit_order_id
        row.pnl_usdc = pnl_usdc
        row.status = status.value
        await self.session.flush()
        return row

    async def list_recent_exits(self, *, limit: int = 10) -> list[TradeModel]:
        query = (
            select(TradeModel)
            .where(TradeModel.exit_reason.is_not(None))
            .order_by(TradeModel.exit_confirmed_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)


class AIDecisionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        signal_id: int,
        evaluated_at: datetime,
        model_id: str,
        fallback_used: bool,
        latency_ms: int,
        raw_response_hash: str,
        decision: AIDecision,
        trade_id: int | None = None,
    ) -> AIDecisionModel:
        row = AIDecisionModel(
            signal_id=signal_id,
            trade_id=trade_id,
            evaluated_at=evaluated_at,
            model_id=model_id,
            fallback_used=fallback_used,
            latency_ms=latency_ms,
            raw_response_hash=raw_response_hash,
            proceed=decision.proceed,
            direction_probability=decision.direction_probability,
            market_price=decision.market_price,
            edge=decision.edge,
            confidence=decision.confidence,
            position_size_factor=decision.position_size_factor,
            reasoning=decision.reasoning,
            warning_flags=list(decision.warning_flags),
            suggested_profit_target_cents=decision.suggested_profit_target_cents,
            suggested_stop_loss_cents=decision.suggested_stop_loss_cents,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def attach_trade(self, ai_decision_id: int, trade_id: int) -> None:
        row = await self.session.get(AIDecisionModel, ai_decision_id)
        if row is None:
            return
        row.trade_id = trade_id
        await self.session.flush()

    async def settle_outcome_by_trade_id(
        self,
        *,
        trade_id: int,
        outcome_pnl: Decimal,
        settled_at: datetime,
    ) -> None:
        query = select(AIDecisionModel).where(AIDecisionModel.trade_id == trade_id)
        row = (await self.session.execute(query)).scalars().first()
        if row is None:
            return
        row.outcome_pnl = outcome_pnl
        row.outcome_settled_at = settled_at
        await self.session.flush()

    async def get_by_trade_id(self, trade_id: int) -> AIDecisionModel | None:
        query = (
            select(AIDecisionModel)
            .where(AIDecisionModel.trade_id == trade_id)
            .order_by(AIDecisionModel.evaluated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(query)).scalars().first()

    async def summary_stats(self) -> dict[str, Decimal | int]:
        total_query = select(func.count()).select_from(AIDecisionModel)
        total = int((await self.session.execute(total_query)).scalar_one())

        veto_query = select(func.count()).select_from(AIDecisionModel).where(AIDecisionModel.proceed.is_(False))
        veto_count = int((await self.session.execute(veto_query)).scalar_one())

        avg_latency_query = select(func.coalesce(func.avg(AIDecisionModel.latency_ms), 0))
        avg_latency = Decimal(str((await self.session.execute(avg_latency_query)).scalar_one()))

        fallback_query = select(func.count()).select_from(AIDecisionModel).where(AIDecisionModel.fallback_used.is_(True))
        fallback_count = int((await self.session.execute(fallback_query)).scalar_one())

        veto_rate = Decimal("0") if total == 0 else Decimal(veto_count) / Decimal(total)
        return {
            "total_decisions": total,
            "veto_count": veto_count,
            "veto_rate": veto_rate,
            "avg_latency_ms": avg_latency,
            "fallback_count": fallback_count,
        }

    async def list_settled_since(self, since_utc: datetime) -> list[AIDecisionModel]:
        query = select(AIDecisionModel).where(
            AIDecisionModel.outcome_settled_at.is_not(None),
            AIDecisionModel.outcome_settled_at >= since_utc,
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def consecutive_fallback_count(self, *, model_id: str, limit: int = 50) -> int:
        query = (
            select(AIDecisionModel)
            .where(AIDecisionModel.model_id == model_id)
            .order_by(AIDecisionModel.evaluated_at.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(query)).scalars().all())
        count = 0
        for row in rows:
            if row.fallback_used:
                count += 1
                continue
            break
        return count


class OpenClawProposalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        proposed_at: datetime,
        analysis_type: str,
        findings: dict[str, object],
        proposal_text: str,
        structured_change: dict[str, object],
        evidence_window_days: int,
        status: OpenClawProposalStatus = OpenClawProposalStatus.PENDING,
    ) -> OpenClawProposalModel:
        row = OpenClawProposalModel(
            proposed_at=proposed_at,
            analysis_type=analysis_type,
            findings=findings,
            proposal_text=proposal_text,
            structured_change=structured_change,
            status=status.value,
            evidence_window_days=evidence_window_days,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_pending(self, *, limit: int = 20) -> list[OpenClawProposalModel]:
        query = (
            select(OpenClawProposalModel)
            .where(OpenClawProposalModel.status == OpenClawProposalStatus.PENDING.value)
            .order_by(OpenClawProposalModel.proposed_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def list_recent(self, *, limit: int = 10) -> list[OpenClawProposalModel]:
        query = (
            select(OpenClawProposalModel)
            .order_by(OpenClawProposalModel.proposed_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def get_by_id(self, proposal_id: int) -> OpenClawProposalModel | None:
        return await self.session.get(OpenClawProposalModel, proposal_id)

    async def set_status(
        self,
        *,
        proposal_id: int,
        status: OpenClawProposalStatus,
        approved_by: str | None = None,
        approved_at: datetime | None = None,
        applied_at: datetime | None = None,
        outcome_note: str | None = None,
    ) -> bool:
        row = await self.session.get(OpenClawProposalModel, proposal_id)
        if row is None:
            return False
        row.status = status.value
        if approved_by is not None:
            row.approved_by = approved_by
        if approved_at is not None:
            row.approved_at = approved_at
        if applied_at is not None:
            row.applied_at = applied_at
        if outcome_note is not None:
            row.outcome_note = outcome_note
        await self.session.flush()
        return True

    async def pending_count(self) -> int:
        query = select(func.count()).select_from(OpenClawProposalModel).where(
            OpenClawProposalModel.status == OpenClawProposalStatus.PENDING.value
        )
        return int((await self.session.execute(query)).scalar_one())


class ConfigRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_change(
        self,
        *,
        config_section: str,
        param_key: str,
        old_value: str | None,
        new_value: str,
        changed_by: str,
        proposal_id: str | None,
        justification: str,
        approved_by: str | None = None,
        status: ProposalStatus = ProposalStatus.PENDING,
    ) -> ConfigHistoryModel:
        row = ConfigHistoryModel(
            changed_at=datetime.now(tz=timezone.utc),
            config_section=config_section,
            param_key=param_key,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            approved_by=approved_by,
            proposal_id=proposal_id,
            justification=justification,
            status=status.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def set_proposal_status(
        self,
        proposal_id: str,
        *,
        status: ProposalStatus,
        approved_by: str | None,
    ) -> int:
        query = select(ConfigHistoryModel).where(ConfigHistoryModel.proposal_id == proposal_id)
        rows = (await self.session.execute(query)).scalars().all()
        for row in rows:
            row.status = status.value
            row.approved_by = approved_by
        await self.session.flush()
        return len(rows)

    async def list_pending(self) -> list[ConfigHistoryModel]:
        query = select(ConfigHistoryModel).where(ConfigHistoryModel.status == ProposalStatus.PENDING.value)
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows)

    async def get_latest_value(
        self,
        *,
        config_section: str,
        param_key: str,
        status: ProposalStatus | None = None,
    ) -> str | None:
        query = select(ConfigHistoryModel).where(
            ConfigHistoryModel.config_section == config_section,
            ConfigHistoryModel.param_key == param_key,
        )
        if status is not None:
            query = query.where(ConfigHistoryModel.status == status.value)
        query = query.order_by(ConfigHistoryModel.changed_at.desc()).limit(1)
        row = (await self.session.execute(query)).scalars().first()
        return row.new_value if row else None


class PerformanceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_metric(
        self,
        *,
        metric_date: date,
        total_trades: int,
        wins: int,
        losses: int,
        win_rate: Decimal,
        gross_pnl_usdc: Decimal,
        fees_usdc: Decimal,
        net_pnl_usdc: Decimal,
        max_drawdown_usdc: Decimal,
        signals_generated: int,
        signals_filtered: int,
        avg_spread_at_entry: Decimal | None,
        strategy_snapshot: dict[str, str],
        risk_snapshot: dict[str, str],
    ) -> PerformanceMetricsModel:
        row = await self.session.get(PerformanceMetricsModel, metric_date)
        payload = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "gross_pnl_usdc": gross_pnl_usdc,
            "fees_usdc": fees_usdc,
            "net_pnl_usdc": net_pnl_usdc,
            "max_drawdown_usdc": max_drawdown_usdc,
            "signals_generated": signals_generated,
            "signals_filtered": signals_filtered,
            "avg_spread_at_entry": avg_spread_at_entry,
            "strategy_snapshot": strategy_snapshot,
            "risk_snapshot": risk_snapshot,
        }
        if row is None:
            row = PerformanceMetricsModel(metric_date=metric_date, **payload)
            self.session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        await self.session.flush()
        return row


class MarketSessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        candle_open_utc: datetime,
        market_slug: str,
        condition_id: str,
        token_id_up: str,
        token_id_down: str,
        resolution_source: str,
        tick_size: Decimal,
        market_end_time: datetime,
    ) -> MarketSessionModel:
        row = await self.session.get(MarketSessionModel, candle_open_utc)
        if row is None:
            row = MarketSessionModel(
                candle_open_utc=candle_open_utc,
                market_slug=market_slug,
                condition_id=condition_id,
                token_id_up=token_id_up,
                token_id_down=token_id_down,
                resolution_source=resolution_source,
                tick_size=tick_size,
                market_end_time=market_end_time,
            )
            self.session.add(row)
        else:
            row.market_slug = market_slug
            row.condition_id = condition_id
            row.token_id_up = token_id_up
            row.token_id_down = token_id_down
            row.resolution_source = resolution_source
            row.tick_size = tick_size
            row.market_end_time = market_end_time
        await self.session.flush()
        return row

    async def get_by_candle_open(self, candle_open_utc: datetime) -> MarketSessionModel | None:
        return await self.session.get(MarketSessionModel, candle_open_utc)
