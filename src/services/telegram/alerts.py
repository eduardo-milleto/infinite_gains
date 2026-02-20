from __future__ import annotations

from collections.abc import Iterable

from telegram import Bot


class TelegramAlerts:
    def __init__(self, bot: Bot, allowed_chat_ids: Iterable[int]) -> None:
        self._bot = bot
        self._chat_ids = tuple(allowed_chat_ids)

    async def broadcast(self, text: str) -> None:
        for chat_id in self._chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text)

    async def notify_trade(self, text: str) -> None:
        await self.broadcast(f"[TRADE] {text}")

    async def notify_kill_switch(self, text: str) -> None:
        await self.broadcast(f"[KILL_SWITCH] {text}")

    async def notify_daily_summary(self, text: str) -> None:
        await self.broadcast(f"[DAILY] {text}")
