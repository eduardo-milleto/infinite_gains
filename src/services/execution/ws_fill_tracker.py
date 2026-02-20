from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
ReconnectCallback = Callable[[], Awaitable[None]]


class WSFillTracker:
    def __init__(
        self,
        *,
        ws_url: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        on_fill_event: EventCallback,
        on_reconnect: ReconnectCallback | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._on_fill_event = on_fill_event
        self._on_reconnect = on_reconnect
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="ws-fill-tracker")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                await self._consume_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._on_reconnect is not None:
                    await self._on_reconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _consume_once(self) -> None:
        async with websockets.connect(self._ws_url, ping_interval=15, ping_timeout=10) as websocket:
            await websocket.send(json.dumps(self._build_subscribe_payload()))
            while not self._stopped.is_set():
                raw = await websocket.recv()
                message = json.loads(raw)
                if isinstance(message, dict) and message.get("type") == "fill":
                    await self._on_fill_event(message)

    def _build_subscribe_payload(self) -> dict[str, Any]:
        return {
            "type": "subscribe",
            "channel": "USER",
            "auth": {
                "apiKey": self._api_key,
                "secret": self._api_secret,
                "passphrase": self._api_passphrase,
            },
        }
