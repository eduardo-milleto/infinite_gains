from __future__ import annotations

import asyncio
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
        active: bool | None = True,
        closed: bool | None = False,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                params: dict[str, str | int] = {"limit": limit}
                if offset is not None:
                    params["offset"] = offset
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
