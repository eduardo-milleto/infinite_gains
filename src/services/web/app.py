from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings, get_settings
from src.core.clock import interval_to_seconds, utc_now
from src.core.enums import OrderStatus, ProposalStatus
from src.db.engine import Database
from src.db.models import AIDecisionModel, MarketSessionModel, SignalModel, TradeModel
from src.db.repository import ConfigRepo

OPEN_STATUSES = {
    OrderStatus.SUBMITTED.value,
    OrderStatus.MATCHED.value,
    OrderStatus.CONFIRMED.value,
}


def create_app() -> FastAPI:
    settings = get_settings()
    database = Database(settings)

    app = FastAPI(title="Infinite Gains Web API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.database = database

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await database.dispose()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return await _build_dashboard_snapshot(settings=settings, database=database)

    @app.websocket("/ws")
    async def ws_status(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                payload = await _build_dashboard_snapshot(settings=settings, database=database)
                await websocket.send_json(payload)
                await asyncio.sleep(5)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


async def _build_dashboard_snapshot(*, settings: Settings, database: Database) -> dict[str, Any]:
    now = utc_now()
    interval_seconds = max(60, interval_to_seconds(settings.taapi_interval))
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    today_end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)

    async with database.session() as session:
        latest_signal = await _latest_signal(session)
        latest_market = await _latest_market(
            session,
            now_utc=now,
            interval_seconds=interval_seconds,
        )
        latest_ai = await _latest_ai_decision(session)
        latest_trade = await _latest_trade(session)
        open_trade = await _latest_open_trade(session)
        recent_trades = await _recent_trades(session, limit=12)
        pnl_trades = await _recent_trades(session, limit=24, only_settled=True)
        signal_series = await _recent_signals(session, limit=12)
        kill_switch_raw = await ConfigRepo(session).get_latest_value(
            config_section="control",
            param_key="kill_switch_state",
            status=ProposalStatus.APPROVED,
        )

        trades_today = await _trades_for_day(session, today_start=today_start, today_end=today_end)
        wins_today = sum(1 for row in trades_today if _trade_pnl(row) > Decimal("0"))
        settled_today = [row for row in trades_today if row.pnl_usdc is not None]
        net_pnl_today = sum((_trade_pnl(row) for row in trades_today), Decimal("0"))
        daily_loss_used = abs(net_pnl_today) if net_pnl_today < 0 else Decimal("0")

        open_positions = await _count_open_positions(session)

        ai_total = await _count_ai(session)
        ai_veto = await _count_ai(session, proceed=False)
        ai_accuracy = await _ai_accuracy(session)
        ai_avg_latency = await _avg_ai_latency(session)
        ai_failures = await _consecutive_ai_failures(session=session, model_id=settings.minimax_model)

    market_end = latest_market.market_end_time if latest_market is not None else now
    remaining_seconds = max(0, int((market_end - now).total_seconds()))
    cooldown_remaining = _cooldown_remaining(
        now=now,
        last_trade_at=latest_trade.candle_open_utc if latest_trade is not None else None,
        cooldown_total=settings.risk_cooldown_seconds,
    )

    position_payload = _position_payload(
        open_trade=open_trade,
        latest_market=latest_market,
        settings=settings,
        now=now,
    )

    signal_payload = _signal_payload(latest_signal=latest_signal, signal_series=signal_series)
    ai_payload = _ai_payload(
        latest_ai=latest_ai,
        settings=settings,
        ai_total=ai_total,
        ai_veto=ai_veto,
        ai_accuracy=ai_accuracy,
        ai_avg_latency=ai_avg_latency,
        ai_failures=ai_failures,
    )

    daily_win_rate = 0.0
    if settled_today:
        daily_win_rate = round((wins_today / len(settled_today)) * 100, 2)

    risk_daily_cap = _to_float(settings.risk_max_daily_loss_usdc)
    risk_daily_remaining = max(0.0, risk_daily_cap - _to_float(daily_loss_used))

    return {
        "mode": settings.trading_mode.value,
        "killSwitch": "TRIPPED" if kill_switch_raw == "TRIPPED" else "HEALTHY",
        "position": position_payload,
        "daily": {
            "tradesUsed": len(trades_today),
            "tradeLimit": settings.risk_max_trades_per_day,
            "winRate": daily_win_rate,
            "netPnl": round(_to_float(net_pnl_today), 4),
            "dailyLossUsed": round(_to_float(daily_loss_used), 4),
            "dailyLossLimit": risk_daily_cap,
        },
        "risk": {
            "cooldownSeconds": cooldown_remaining,
            "maxTradeSize": _to_float(settings.risk_max_trade_usdc),
            "dailyLossRemaining": round(risk_daily_remaining, 4),
            "dailyLossCap": risk_daily_cap,
            "openSlots": open_positions,
            "maxSlots": settings.risk_max_open_positions,
        },
        "signal": signal_payload,
        "ai": ai_payload,
        "market": {
            "slug": latest_market.market_slug if latest_market is not None else "n/a",
            "candleOpen": _format_utc(latest_market.candle_open_utc) if latest_market is not None else "n/a",
            "candleClose": _format_utc(latest_market.market_end_time) if latest_market is not None else "n/a",
            "remainingSeconds": remaining_seconds,
            "intervalSeconds": interval_seconds,
            "spreadCents": round(
                _to_float(latest_signal.spread_at_eval) * 100 if latest_signal and latest_signal.spread_at_eval else 0.0,
                4,
            ),
            "upPriceCents": round(position_payload["currentPrice"] * 100, 4),
            "downPriceCents": round(max(0.0, 100 - (position_payload["currentPrice"] * 100)), 4),
            "resolutionSource": latest_market.resolution_source if latest_market is not None else "n/a",
        },
        "pnlSeries": _pnl_series(pnl_trades=pnl_trades),
        "tradeLog": [_trade_row_payload(row) for row in recent_trades],
        "systemLogs": _system_logs(now=now, latest_signal=latest_signal, latest_ai=latest_ai, latest_trade=latest_trade),
    }


async def _latest_signal(session: AsyncSession) -> SignalModel | None:
    query = select(SignalModel).order_by(SignalModel.evaluated_at.desc()).limit(1)
    return (await session.execute(query)).scalars().first()


async def _latest_market(
    session: AsyncSession,
    *,
    now_utc: datetime,
    interval_seconds: int,
) -> MarketSessionModel | None:
    lookback = timedelta(seconds=max(interval_seconds * 3, 900))
    lookahead = timedelta(seconds=max(interval_seconds * 3, 900))
    query = (
        select(MarketSessionModel)
        .where(
            and_(
                MarketSessionModel.market_end_time >= now_utc - lookback,
                MarketSessionModel.market_end_time <= now_utc + lookahead,
            )
        )
        .order_by(MarketSessionModel.market_end_time.asc())
        .limit(1)
    )
    row = (await session.execute(query)).scalars().first()
    if row is not None:
        return row
    return None


async def _latest_ai_decision(session: AsyncSession) -> AIDecisionModel | None:
    query = select(AIDecisionModel).order_by(AIDecisionModel.evaluated_at.desc()).limit(1)
    return (await session.execute(query)).scalars().first()


async def _latest_trade(session: AsyncSession) -> TradeModel | None:
    query = select(TradeModel).order_by(TradeModel.candle_open_utc.desc()).limit(1)
    return (await session.execute(query)).scalars().first()


async def _latest_open_trade(session: AsyncSession) -> TradeModel | None:
    query = (
        select(TradeModel)
        .where(TradeModel.status.in_(list(OPEN_STATUSES)))
        .order_by(TradeModel.candle_open_utc.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalars().first()


async def _recent_trades(session: AsyncSession, *, limit: int, only_settled: bool = False) -> list[TradeModel]:
    query = select(TradeModel).order_by(TradeModel.candle_open_utc.desc()).limit(limit)
    if only_settled:
        query = query.where(TradeModel.pnl_usdc.is_not(None))
    rows = (await session.execute(query)).scalars().all()
    return list(rows)


async def _recent_signals(session: AsyncSession, *, limit: int) -> list[SignalModel]:
    query = select(SignalModel).order_by(SignalModel.evaluated_at.desc()).limit(limit)
    rows = list((await session.execute(query)).scalars().all())
    rows.reverse()
    return rows


async def _trades_for_day(
    session: AsyncSession,
    *,
    today_start: datetime,
    today_end: datetime,
) -> list[TradeModel]:
    query = select(TradeModel).where(
        and_(
            TradeModel.candle_open_utc >= today_start,
            TradeModel.candle_open_utc <= today_end,
        )
    )
    rows = (await session.execute(query)).scalars().all()
    return list(rows)


async def _count_ai(session: AsyncSession, *, proceed: bool | None = None) -> int:
    query = select(func.count()).select_from(AIDecisionModel)
    if proceed is not None:
        query = query.where(AIDecisionModel.proceed.is_(proceed))
    return int((await session.execute(query)).scalar_one())


async def _count_open_positions(session: AsyncSession) -> int:
    query = select(func.count()).select_from(TradeModel).where(TradeModel.status.in_(list(OPEN_STATUSES)))
    return int((await session.execute(query)).scalar_one())


async def _avg_ai_latency(session: AsyncSession) -> float:
    query = select(func.coalesce(func.avg(AIDecisionModel.latency_ms), 0))
    value = (await session.execute(query)).scalar_one()
    return round(float(value) / 1000, 4)


async def _ai_accuracy(session: AsyncSession) -> float:
    query = select(AIDecisionModel).where(AIDecisionModel.outcome_pnl.is_not(None))
    rows = list((await session.execute(query)).scalars().all())
    if not rows:
        return 0.0
    wins = 0
    for row in rows:
        pnl = Decimal(str(row.outcome_pnl or 0))
        if pnl > 0:
            wins += 1
    return round((wins / len(rows)) * 100, 2)


async def _consecutive_ai_failures(*, session: AsyncSession, model_id: str) -> int:
    query = (
        select(AIDecisionModel)
        .where(AIDecisionModel.model_id == model_id)
        .order_by(AIDecisionModel.evaluated_at.desc())
        .limit(50)
    )
    rows = list((await session.execute(query)).scalars().all())
    count = 0
    for row in rows:
        if row.fallback_used:
            count += 1
        else:
            break
    return count


def _position_payload(
    *,
    open_trade: TradeModel | None,
    latest_market: MarketSessionModel | None,
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    if open_trade is None:
        return {
            "open": False,
            "token": "BTC UP",
            "entryPrice": 0.5,
            "currentPrice": 0.5,
            "unrealizedPnl": 0.0,
            "holdSeconds": 0,
            "exitMode": "SCALP MODE" if settings.exit_mode.value == "SCALP" else "HOLD MODE",
        }

    entry_price = _to_float(open_trade.price_entry if open_trade.price_entry is not None else open_trade.price)
    current_price = entry_price
    if open_trade.price_exit is not None:
        current_price = _to_float(open_trade.price_exit)
    elif latest_market is not None:
        # No persisted live mark price in DB yet; use conservative carry on entry.
        current_price = entry_price

    size_usdc = _to_float(open_trade.size_usdc)
    shares = size_usdc / entry_price if entry_price > 0 else 0.0
    unrealized = (current_price - entry_price) * shares
    hold_seconds = max(0, int((now - open_trade.candle_open_utc).total_seconds()))

    return {
        "open": True,
        "token": "BTC UP" if open_trade.direction == "UP" else "BTC DOWN",
        "entryPrice": round(entry_price, 6),
        "currentPrice": round(current_price, 6),
        "unrealizedPnl": round(unrealized, 6),
        "holdSeconds": hold_seconds,
        "exitMode": "SCALP MODE" if settings.exit_mode.value == "SCALP" else "HOLD MODE",
    }


def _signal_payload(*, latest_signal: SignalModel | None, signal_series: list[SignalModel]) -> dict[str, Any]:
    if latest_signal is None:
        return {
            "rsi": 50.0,
            "rsiPrev": 50.0,
            "rsiSeries": [50.0],
            "stochK": 50.0,
            "stochD": 50.0,
            "stochKSeries": [50.0],
            "stochDSeries": [50.0],
            "result": "NONE",
        }

    return {
        "rsi": round(_to_float(latest_signal.rsi_curr), 4),
        "rsiPrev": round(_to_float(latest_signal.rsi_prev), 4),
        "rsiSeries": [round(_to_float(item.rsi_curr), 4) for item in signal_series] or [round(_to_float(latest_signal.rsi_curr), 4)],
        "stochK": round(_to_float(latest_signal.stoch_k_curr), 4),
        "stochD": round(_to_float(latest_signal.stoch_d_curr), 4),
        "stochKSeries": [round(_to_float(item.stoch_k_curr), 4) for item in signal_series] or [round(_to_float(latest_signal.stoch_k_curr), 4)],
        "stochDSeries": [round(_to_float(item.stoch_d_curr), 4) for item in signal_series] or [round(_to_float(latest_signal.stoch_d_curr), 4)],
        "result": latest_signal.signal_type,
    }


def _ai_payload(
    *,
    latest_ai: AIDecisionModel | None,
    settings: Settings,
    ai_total: int,
    ai_veto: int,
    ai_accuracy: float,
    ai_avg_latency: float,
    ai_failures: int,
) -> dict[str, Any]:
    if latest_ai is None:
        return {
            "enabled": settings.minimax_enabled,
            "decision": "VETOED",
            "probability": 0.5,
            "marketPrice": 0.5,
            "edge": 0.0,
            "confidence": 0,
            "positionFactor": 0.5,
            "latencySeconds": 0.0,
            "warningFlags": [],
            "reasoning": "No AI decisions yet.",
            "totalDecisions": ai_total,
            "vetoRate": 0.0,
            "avgLatency": ai_avg_latency,
            "accuracy": ai_accuracy,
            "consecutiveFailures": ai_failures,
        }

    veto_rate = round((ai_veto / ai_total) * 100, 4) if ai_total else 0.0
    return {
        "enabled": settings.minimax_enabled,
        "decision": "PROCEED" if latest_ai.proceed else "VETOED",
        "probability": round(_to_float(latest_ai.direction_probability), 6),
        "marketPrice": round(_to_float(latest_ai.market_price), 6),
        "edge": round(_to_float(latest_ai.edge), 6),
        "confidence": latest_ai.confidence,
        "positionFactor": round(_to_float(latest_ai.position_size_factor), 6),
        "latencySeconds": round(latest_ai.latency_ms / 1000, 4),
        "warningFlags": list(latest_ai.warning_flags or []),
        "reasoning": latest_ai.reasoning,
        "totalDecisions": ai_total,
        "vetoRate": veto_rate,
        "avgLatency": ai_avg_latency,
        "accuracy": ai_accuracy,
        "consecutiveFailures": ai_failures,
    }


def _pnl_series(*, pnl_trades: list[TradeModel]) -> list[dict[str, Any]]:
    if not pnl_trades:
        return [{"time": "NOW", "pnl": 0.0}]

    rolling = Decimal("0")
    points: list[dict[str, Any]] = []
    for row in reversed(pnl_trades):
        rolling += _trade_pnl(row)
        points.append(
            {
                "time": row.candle_open_utc.strftime("%m-%d %H:%M"),
                "pnl": round(_to_float(rolling), 6),
                "trade": True,
            }
        )
    return points


def _trade_row_payload(row: TradeModel) -> dict[str, Any]:
    pnl = _trade_pnl(row)
    if row.status in OPEN_STATUSES:
        trade_status = "OPEN"
    elif row.status == OrderStatus.CANCELLED.value:
        trade_status = "CANCELLED"
    elif pnl > 0:
        trade_status = "WIN"
    else:
        trade_status = "LOSS"

    mode = "HOLD" if row.exit_reason == "RESOLUTION" else "SCALP"

    return {
        "time": row.candle_open_utc.strftime("%H:%M:%S"),
        "direction": row.direction,
        "entry": round(_to_float(row.price_entry if row.price_entry is not None else row.price), 6),
        "exit": round(_to_float(row.price_exit), 6) if row.price_exit is not None else None,
        "size": round(_to_float(row.size_usdc), 6),
        "pnl": round(_to_float(pnl), 6) if row.pnl_usdc is not None else None,
        "status": trade_status,
        "exitReason": row.exit_reason or row.failure_reason or "-",
        "mode": mode,
    }


def _system_logs(
    *,
    now: datetime,
    latest_signal: SignalModel | None,
    latest_ai: AIDecisionModel | None,
    latest_trade: TradeModel | None,
) -> list[str]:
    lines = [f"{_format_utc(now)} Dashboard snapshot refreshed"]
    if latest_signal is not None:
        lines.append(f"{_format_utc(latest_signal.evaluated_at)} Signal: {latest_signal.signal_type}")
    if latest_ai is not None:
        lines.append(
            f"{_format_utc(latest_ai.evaluated_at)} AI: {'PROCEED' if latest_ai.proceed else 'VETOED'}"
        )
    if latest_trade is not None:
        lines.append(f"{_format_utc(latest_trade.candle_open_utc)} Trade status: {latest_trade.status}")
    return lines[:5]


def _cooldown_remaining(*, now: datetime, last_trade_at: datetime | None, cooldown_total: int) -> int:
    if last_trade_at is None:
        return 0
    elapsed = int((now - last_trade_at).total_seconds())
    return max(0, cooldown_total - elapsed)


def _to_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _trade_pnl(row: TradeModel) -> Decimal:
    pnl = Decimal(str(row.pnl_usdc or 0))
    fees = Decimal(str(row.fees_usdc or 0))
    return pnl - fees


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%H:%M UTC")
