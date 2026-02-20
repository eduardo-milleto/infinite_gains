from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class PositionTracker:
    _day: date | None = None
    _trades_today: int = 0
    _open_positions: int = 0
    _daily_pnl: Decimal = Decimal("0")
    _last_trade_time: datetime | None = None
    _trades_by_candle: dict[datetime, int] = field(default_factory=dict)

    def sync_day(self, now: datetime) -> None:
        today = now.date()
        if self._day == today:
            return
        self._day = today
        self._trades_today = 0
        self._daily_pnl = Decimal("0")
        self._trades_by_candle.clear()

    def register_trade(self, candle_open_utc: datetime, now: datetime) -> None:
        self.sync_day(now)
        self._trades_today += 1
        self._last_trade_time = now
        self._trades_by_candle[candle_open_utc] = self._trades_by_candle.get(candle_open_utc, 0) + 1

    def register_open_position(self) -> None:
        self._open_positions += 1

    def register_closed_position(self, pnl_usdc: Decimal) -> None:
        if self._open_positions > 0:
            self._open_positions -= 1
        self._daily_pnl += pnl_usdc

    @property
    def trades_today(self) -> int:
        return self._trades_today

    @property
    def open_positions(self) -> int:
        return self._open_positions

    @property
    def daily_pnl(self) -> Decimal:
        return self._daily_pnl

    @property
    def last_trade_time(self) -> datetime | None:
        return self._last_trade_time

    def trades_in_candle(self, candle_open_utc: datetime) -> int:
        return self._trades_by_candle.get(candle_open_utc, 0)
