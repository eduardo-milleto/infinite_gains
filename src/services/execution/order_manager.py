from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from src.core.enums import TradeDirection
from src.core.types import MarketContext, OrderResult


class ExecutionClient(Protocol):
    async def place_limit_order(
        self,
        *,
        direction: TradeDirection,
        token_id: str,
        price: Decimal,
        size_usdc: Decimal,
    ) -> OrderResult: ...


class OrderManager:
    def __init__(self, client: ExecutionClient) -> None:
        self._client = client

    async def place_entry_order(
        self,
        *,
        direction: TradeDirection,
        size_usdc: Decimal,
        market_context: MarketContext,
    ) -> OrderResult:
        token_id = market_context.token_id_up if direction == TradeDirection.UP else market_context.token_id_down
        if direction == TradeDirection.UP:
            price = Decimal("0.53")
        else:
            price = Decimal("0.47")
        return await self._client.place_limit_order(
            direction=direction,
            token_id=token_id,
            price=price,
            size_usdc=size_usdc,
        )
