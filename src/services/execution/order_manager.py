from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from src.core.enums import TradeDirection
from src.core.types import MarketContext, OrderResult
from src.db.models import TradeModel


class ExecutionClient(Protocol):
    async def place_limit_order(
        self,
        *,
        direction: TradeDirection,
        token_id: str,
        price: Decimal,
        size_usdc: Decimal,
        side: str = "BUY",
    ) -> OrderResult: ...

    async def get_token_price(self, token_id: str) -> Decimal: ...


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
            price = market_context.up_price
        else:
            price = market_context.down_price
        return await self._client.place_limit_order(
            direction=direction,
            token_id=token_id,
            price=price,
            size_usdc=size_usdc,
            side="BUY",
        )

    async def place_exit_order(
        self,
        *,
        trade: TradeModel,
        exit_price: Decimal,
    ) -> OrderResult:
        direction = TradeDirection(trade.direction)
        return await self._client.place_limit_order(
            direction=direction,
            token_id=trade.token_id,
            price=exit_price,
            size_usdc=Decimal(str(trade.size_usdc)),
            side="SELL",
        )

    async def place_scale_in_order(
        self,
        *,
        trade: TradeModel,
        entry_price: Decimal,
        size_usdc: Decimal,
    ) -> OrderResult:
        direction = TradeDirection(trade.direction)
        return await self._client.place_limit_order(
            direction=direction,
            token_id=trade.token_id,
            price=entry_price,
            size_usdc=size_usdc,
            side="BUY",
        )

    async def get_token_price(self, token_id: str) -> Decimal:
        return await self._client.get_token_price(token_id)
