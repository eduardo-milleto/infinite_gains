from __future__ import annotations

import asyncio
from typing import Any

import httpx

from src.config.settings import Settings
from src.core.exceptions import APIFailureError


class MiniMaxClient:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 10.0, max_retries: int = 2) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self._settings.minimax_api_base_url.rstrip("/"),
            timeout=self._timeout_seconds,
            http2=True,
            headers={
                "Authorization": f"Bearer {self._settings.minimax_api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
        self._semaphore = asyncio.Semaphore(3)

    async def close(self) -> None:
        await self._client.aclose()

    async def create_decision(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self._settings.minimax_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        return await self._post_with_retry(payload)

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(1, self._max_retries + 1):
                try:
                    response = await self._client.post("/chat/completions", json=payload)
                    response.raise_for_status()
                    parsed = response.json()
                    if not isinstance(parsed, dict):
                        raise APIFailureError("MiniMax response is not a JSON object")
                    return parsed
                except (httpx.HTTPError, APIFailureError) as exc:
                    last_error = exc
                    if attempt >= self._max_retries:
                        break
                    await asyncio.sleep(0.4 * attempt)

        raise APIFailureError(f"MiniMax API failed: {last_error}")

    @staticmethod
    def extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                text = first.get("text")
                if isinstance(text, str):
                    return text

        reply = payload.get("reply")
        if isinstance(reply, str):
            return reply

        raise APIFailureError("MiniMax response does not contain text content")
