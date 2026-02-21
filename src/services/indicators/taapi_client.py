from __future__ import annotations

import asyncio
from datetime import timezone
from decimal import Decimal
from typing import Any

import httpx

from src.config.settings import Settings
from src.core.clock import utc_floor_hour, utc_now
from src.core.exceptions import APIFailureError
from src.core.types import IndicatorSnapshot


class TaapiClient:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 10.0, max_retries: int = 3) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._base_url = "https://api.taapi.io"
        self._client = httpx.AsyncClient(timeout=self._timeout_seconds, http2=True)
        self._semaphore = asyncio.Semaphore(3)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(1, self._max_retries + 1):
                try:
                    response = await self._client.get(f"{self._base_url}/{endpoint}", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        raise APIFailureError(f"TAAPI error response: {payload['error']}")
                    if not isinstance(payload, dict):
                        raise APIFailureError("TAAPI response is not a JSON object")
                    return payload
                except (httpx.HTTPError, APIFailureError) as exc:
                    last_error = exc
                    if attempt >= self._max_retries:
                        break
                    await asyncio.sleep(0.5 * attempt)

        raise APIFailureError(f"TAAPI request failed after retries: {last_error}")

    async def _fetch_rsi(self, backtrack: int) -> Decimal:
        payload = await self._request(
            "rsi",
            {
                "secret": self._settings.taapi_secret.get_secret_value(),
                "exchange": self._settings.taapi_exchange,
                "symbol": self._settings.taapi_symbol,
                "interval": self._settings.taapi_interval,
                "backtrack": backtrack,
                "period": self._settings.strategy_rsi_period,
            },
        )
        value = payload.get("value")
        if value is None:
            raise APIFailureError("TAAPI RSI response missing 'value'")
        return Decimal(str(value))

    async def _fetch_stochastic(self, backtrack: int) -> tuple[Decimal, Decimal]:
        payload = await self._request(
            "stoch",
            {
                "secret": self._settings.taapi_secret.get_secret_value(),
                "exchange": self._settings.taapi_exchange,
                "symbol": self._settings.taapi_symbol,
                "interval": self._settings.taapi_interval,
                "backtrack": backtrack,
                "kPeriod": self._settings.strategy_stoch_k_period,
                "dPeriod": self._settings.strategy_stoch_d_period,
                "kSmooth": self._settings.strategy_stoch_k_smooth,
            },
        )

        k_value = payload.get("valueK")
        d_value = payload.get("valueD")
        if k_value is None or d_value is None:
            # Backward compatibility with older response naming.
            k_value = payload.get("valueFastK")
            d_value = payload.get("valueFastD")
        if k_value is None or d_value is None:
            raise APIFailureError("TAAPI stochastic response missing K/D values")
        return Decimal(str(k_value)), Decimal(str(d_value))

    async def fetch_snapshot(self) -> IndicatorSnapshot:
        rsi_curr, rsi_prev = await asyncio.gather(self._fetch_rsi(0), self._fetch_rsi(self._settings.taapi_backtrack))
        (k_curr, d_curr), (k_prev, d_prev) = await asyncio.gather(
            self._fetch_stochastic(0),
            self._fetch_stochastic(self._settings.taapi_backtrack),
        )

        now_utc = utc_now().astimezone(timezone.utc)
        return IndicatorSnapshot(
            evaluated_at=now_utc,
            candle_open_utc=utc_floor_hour(now_utc),
            rsi_prev=rsi_prev,
            rsi_curr=rsi_curr,
            stoch_k_prev=k_prev,
            stoch_d_prev=d_prev,
            stoch_k_curr=k_curr,
            stoch_d_curr=d_curr,
        )
