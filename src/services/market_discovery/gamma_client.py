from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import httpx

from src.core.exceptions import APIFailureError


class GammaClient:
    def __init__(
        self,
        base_url: str = "https://gamma-api.polymarket.com",
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=self._timeout_seconds, http2=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def list_markets(
        self,
        *,
        limit: int = 200,
        offset: int | None = None,
        order: str | None = "volume",
        ascending: bool | None = False,
        active: bool | None = True,
        closed: bool | None = False,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                params: dict[str, str | int] = {"limit": limit}
                if offset is not None:
                    params["offset"] = offset
                if order:
                    params["order"] = order
                if ascending is not None:
                    params["ascending"] = str(ascending).lower()
                if active is not None:
                    params["active"] = str(active).lower()
                if closed is not None:
                    params["closed"] = str(closed).lower()
                response = await self._client.get(
                    f"{self._base_url}/markets",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise APIFailureError("Gamma API markets response is not a list")
                return [item for item in payload if isinstance(item, dict)]
            except (httpx.HTTPError, APIFailureError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(0.5 * attempt)

        raise APIFailureError(f"Gamma API failure: {last_error}")

    async def public_search(
        self,
        *,
        query: str,
        limit: int = 200,
        active: bool | None = True,
        closed: bool | None = False,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                params: dict[str, str | int] = {"q": query, "limit": limit}
                if active is not None:
                    params["active"] = str(active).lower()
                if closed is not None:
                    params["closed"] = str(closed).lower()
                response = await self._client.get(
                    f"{self._base_url}/public-search",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                return self._extract_markets(payload)
            except (httpx.HTTPError, APIFailureError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(0.5 * attempt)

        raise APIFailureError(f"Gamma public-search failure: {last_error}")

    @classmethod
    def _extract_markets(cls, payload: Any) -> list[dict[str, Any]]:
        markets: list[dict[str, Any]] = []
        seen: set[str] = set()

        def push(item: dict[str, Any]) -> None:
            key = str(item.get("conditionId") or item.get("condition_id") or item.get("slug") or item.get("id") or "")
            if not key:
                return
            if key in seen:
                return
            seen.add(key)
            markets.append(item)

        def looks_like_market(item: dict[str, Any]) -> bool:
            has_title = bool(
                str(item.get("slug") or item.get("market_slug") or item.get("question") or item.get("title") or "").strip()
            )
            has_market_identity = any(
                key in item
                for key in (
                    "conditionId",
                    "condition_id",
                    "clobTokenIds",
                    "clob_token_ids",
                    "tokens",
                    "bestBid",
                    "bestAsk",
                    "outcomes",
                    "outcomePrices",
                )
            )
            return has_title and has_market_identity

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if looks_like_market(node):
                    push(node)
                for value in node.values():
                    visit(value)
                return
            if isinstance(node, Iterable) and not isinstance(node, (str, bytes)):
                for item in node:
                    visit(item)

        visit(payload)
        return markets
