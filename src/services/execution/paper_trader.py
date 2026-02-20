from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.core.enums import OrderStatus, TradeDirection
from src.core.types import OrderResult


class PaperTrader:
    def __init__(self) -> None:
        self._orders: dict[str, OrderResult] = {}

    async def place_limit_order(
        self,
        *,
        direction: TradeDirection,
        token_id: str,
        price: Decimal,
        size_usdc: Decimal,
    ) -> OrderResult:
        order_id = f"paper-{uuid4()}"
        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.SUBMITTED,
            direction=direction,
            token_id=token_id,
            price=price,
            size_usdc=size_usdc,
            size_filled_usdc=Decimal("0"),
            raw_response={
                "order_id": order_id,
                "simulated": True,
            },
        )
        self._orders[order_id] = result
        return result

    async def cancel_order(self, order_id: str) -> dict[str, str]:
        existed = order_id in self._orders
        if existed:
            del self._orders[order_id]
        return {
            "order_id": order_id,
            "cancelled": str(existed).lower(),
            "mode": "paper",
        }
