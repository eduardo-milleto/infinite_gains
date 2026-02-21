from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.config.settings import Settings
from src.core.enums import OrderStatus, TradeDirection
from src.core.exceptions import APIFailureError
from src.core.types import OrderResult


class ClobClientWrapper:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings) -> Any:
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except ImportError as exc:
            raise APIFailureError("py-clob-client is required for LIVE mode") from exc

        private_key = settings.poly_private_key.get_secret_value()
        api_creds = ApiCreds(
            api_key=settings.poly_api_key.get_secret_value(),
            api_secret=settings.poly_api_secret.get_secret_value(),
            api_passphrase=settings.poly_api_passphrase.get_secret_value(),
        )

        try:
            client = ClobClient(
                host=settings.poly_clob_host,
                chain_id=settings.poly_chain_id,
                key=private_key,
                creds=api_creds,
                funder=settings.poly_funder_address,
            )
        except TypeError:
            client = ClobClient(
                settings.poly_clob_host,
                settings.poly_chain_id,
                private_key,
            )
        return client

    async def place_limit_order(
        self,
        *,
        direction: TradeDirection,
        token_id: str,
        price: Decimal,
        size_usdc: Decimal,
        side: str = "BUY",
    ) -> OrderResult:
        payload = {
            "token_id": token_id,
            "price": str(price),
            "size": str(size_usdc),
            "side": side,
            "direction": direction.value,
        }
        try:
            raw_response = await self._submit_order(payload)
            scrubbed = self._scrub(raw_response)
            order_id = self._extract_order_id(raw_response)
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.SUBMITTED,
                direction=direction,
                token_id=token_id,
                price=price,
                size_usdc=size_usdc,
                raw_response=scrubbed,
            )
        except Exception as exc:
            scrubbed_failure = self._scrub({"error": str(exc), "payload": payload})
            return OrderResult(
                order_id=f"failed-{uuid4()}",
                status=OrderStatus.FAILED,
                direction=direction,
                token_id=token_id,
                price=price,
                size_usdc=size_usdc,
                failure_reason=str(exc),
                raw_response=scrubbed_failure,
            )

    async def get_token_price(self, token_id: str) -> Decimal:
        methods: list[tuple[str, tuple[Any, ...]]] = [
            ("get_price", (token_id,)),
            ("get_token_price", (token_id,)),
            ("get_last_trade_price", (token_id,)),
            ("get_order_book", (token_id,)),
            ("get_orderbook", (token_id,)),
            ("get_book", (token_id,)),
        ]

        for method_name, args in methods:
            method = getattr(self._client, method_name, None)
            if method is None:
                continue
            try:
                raw = await asyncio.to_thread(method, *args)
            except Exception:
                continue
            price = self._extract_price(raw)
            if price is not None:
                return price

        raise APIFailureError("Unable to fetch token price from CLOB client")

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        method = getattr(self._client, "cancel", None) or getattr(self._client, "cancel_order", None)
        if method is None:
            raise APIFailureError("CLOB client cancel method unavailable")
        result = await asyncio.to_thread(method, order_id)
        return self._scrub(result)

    async def _submit_order(self, payload: dict[str, str]) -> dict[str, Any]:
        create_order = getattr(self._client, "create_order", None)
        post_order = getattr(self._client, "post_order", None)
        place_order = getattr(self._client, "place_order", None)

        if create_order is not None and post_order is not None:
            signed = await asyncio.to_thread(create_order, payload)
            posted = await asyncio.to_thread(post_order, signed)
            if isinstance(posted, dict):
                return posted
            return {"result": posted}

        if place_order is not None:
            placed = await asyncio.to_thread(place_order, payload)
            if isinstance(placed, dict):
                return placed
            return {"result": placed}

        raise APIFailureError("CLOB client has no supported order placement method")

    @staticmethod
    def _extract_order_id(payload: dict[str, Any]) -> str:
        for key in ("orderID", "orderId", "id"):
            value = payload.get(key)
            if value:
                return str(value)
        return f"live-{uuid4()}"

    @classmethod
    def _extract_price(cls, payload: Any) -> Decimal | None:
        if isinstance(payload, Decimal):
            return payload
        if isinstance(payload, (int, float, str)):
            try:
                return Decimal(str(payload))
            except Exception:
                return None

        if isinstance(payload, dict):
            for key in ("price", "lastPrice", "last_price", "mid", "markPrice", "mark_price"):
                value = payload.get(key)
                if value is not None:
                    try:
                        return Decimal(str(value))
                    except Exception:
                        continue
            bid = payload.get("bestBid") or payload.get("best_bid")
            ask = payload.get("bestAsk") or payload.get("best_ask")
            if bid is not None and ask is not None:
                try:
                    return (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")
                except Exception:
                    return None
        return None

    @classmethod
    def _scrub(cls, payload: Any) -> Any:
        if isinstance(payload, dict):
            scrubbed: dict[str, Any] = {}
            for key, value in payload.items():
                key_lc = key.lower()
                if any(marker in key_lc for marker in ("key", "secret", "signature", "private")):
                    continue
                scrubbed[key] = cls._scrub(value)
            return scrubbed
        if isinstance(payload, list):
            return [cls._scrub(item) for item in payload]
        if isinstance(payload, str) and payload.startswith("0x") and len(payload) >= 64:
            return "[REDACTED_HEX]"
        return payload
