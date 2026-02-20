from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.enums import OrderStatus, TradeDirection
from src.services.execution.paper_trader import PaperTrader


@pytest.mark.asyncio
async def test_paper_trader_places_and_cancels_order() -> None:
    trader = PaperTrader()

    order = await trader.place_limit_order(
        direction=TradeDirection.UP,
        token_id="up-token",
        price=Decimal("0.55"),
        size_usdc=Decimal("10"),
    )

    assert order.status == OrderStatus.SUBMITTED
    assert order.order_id is not None

    result = await trader.cancel_order(order.order_id)
    assert result["cancelled"] == "true"
