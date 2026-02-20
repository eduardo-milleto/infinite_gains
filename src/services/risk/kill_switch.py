from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from src.core.clock import utc_now
from src.core.exceptions import KillSwitchError

KillSwitchCallback = Callable[[str, datetime], Awaitable[None]]


class KillSwitch:
    def __init__(self, on_trip: KillSwitchCallback | None = None) -> None:
        self._on_trip = on_trip
        self._is_tripped = False
        self._reason: str | None = None
        self._tripped_at: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def is_tripped(self) -> bool:
        return self._is_tripped

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def tripped_at(self) -> datetime | None:
        return self._tripped_at

    async def trip(self, reason: str) -> None:
        async with self._lock:
            if self._is_tripped:
                return
            self._is_tripped = True
            self._reason = reason
            self._tripped_at = utc_now()

        if self._on_trip is not None:
            await self._on_trip(reason, self._tripped_at)

    async def reset(self) -> None:
        async with self._lock:
            self._is_tripped = False
            self._reason = None
            self._tripped_at = None

    def assert_healthy(self) -> None:
        if self._is_tripped:
            raise KillSwitchError(f"Kill switch is tripped: {self._reason}")
