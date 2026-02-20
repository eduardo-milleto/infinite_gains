from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.core.enums import OrderStatus, SignalType, TradeDirection, TradingMode
from src.core.types import IndicatorSnapshot, OrderResult
from src.db.repository import SignalRepo, TradeRepo


@pytest.mark.asyncio
async def test_signal_and_trade_repository(async_session) -> None:
    signal_repo = SignalRepo(async_session)
    trade_repo = TradeRepo(async_session)

    now = datetime.now(tz=timezone.utc)
    snapshot = IndicatorSnapshot(
        evaluated_at=now,
        candle_open_utc=now.replace(minute=0, second=0, microsecond=0),
        rsi_prev=Decimal("20"),
        rsi_curr=Decimal("35"),
        stoch_k_prev=Decimal("10"),
        stoch_d_prev=Decimal("11"),
        stoch_k_curr=Decimal("13"),
        stoch_d_curr=Decimal("12"),
    )

    signal = await signal_repo.create(
        snapshot=snapshot,
        signal_type=SignalType.LONG,
        filter_result=None,
        market_slug="btc-hourly",
        spread_at_eval=Decimal("0.01"),
        trading_mode=TradingMode.PAPER,
    )

    order = OrderResult(
        order_id="paper-1",
        status=OrderStatus.SUBMITTED,
        direction=TradeDirection.UP,
        token_id="up",
        price=Decimal("0.53"),
        size_usdc=Decimal("10"),
    )

    trade = await trade_repo.create(
        signal_id=signal.id,
        market_slug="btc-hourly",
        condition_id="cond",
        candle_open_utc=snapshot.candle_open_utc,
        trading_mode=TradingMode.PAPER,
        order_result=order,
    )

    assert trade.id > 0
    assert await trade_repo.count_trades_for_day(now.date()) == 1
    assert await trade_repo.count_open_positions() == 1
