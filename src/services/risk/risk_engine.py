from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.config.settings import Settings
from src.core.enums import SignalType
from src.core.exceptions import RiskVetoError
from src.core.types import MarketContext, Signal
from src.db.repository import TradeRepo
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker


class RiskEngine:
    def __init__(self, settings: Settings, kill_switch: KillSwitch, position_tracker: PositionTracker) -> None:
        self._settings = settings
        self._kill_switch = kill_switch
        self._position_tracker = position_tracker

    async def approve_trade(
        self,
        *,
        signal: Signal,
        market_context: MarketContext,
        now_utc: datetime,
        trade_repo: TradeRepo,
    ) -> Decimal:
        self._kill_switch.assert_healthy()
        self._position_tracker.sync_day(now_utc)

        if signal.signal_type == SignalType.NONE:
            raise RiskVetoError("No trade: signal type NONE")

        if market_context.spread > self._settings.market_max_spread:
            raise RiskVetoError("Spread exceeds configured maximum")

        secs_to_close = (market_context.market_end_time - now_utc).total_seconds()
        if secs_to_close <= self._settings.market_no_trade_before_close_secs:
            raise RiskVetoError("Too close to market close")

        if self._position_tracker.trades_in_candle(signal.indicator_snapshot.candle_open_utc) >= self._settings.market_max_trades_per_candle:
            raise RiskVetoError("Trade limit per candle reached")

        if self._position_tracker.last_trade_time is not None:
            elapsed = (now_utc - self._position_tracker.last_trade_time).total_seconds()
            if elapsed < self._settings.risk_cooldown_seconds:
                raise RiskVetoError("Cooldown period still active")

        db_trades_today = await trade_repo.count_trades_for_day(now_utc.date())
        trades_today = max(db_trades_today, self._position_tracker.trades_today)
        if trades_today >= self._settings.risk_max_trades_per_day:
            raise RiskVetoError("Daily trade count limit reached")

        db_open_positions = await trade_repo.count_open_positions()
        open_positions = max(db_open_positions, self._position_tracker.open_positions)
        if open_positions >= self._settings.risk_max_open_positions:
            raise RiskVetoError("Open position limit reached")

        db_daily_pnl = await trade_repo.sum_daily_pnl(now_utc.date())
        daily_pnl = min(db_daily_pnl, self._position_tracker.daily_pnl)
        if daily_pnl <= -self._settings.risk_max_daily_loss_usdc:
            raise RiskVetoError("Daily loss limit exceeded")

        return min(self._settings.risk_max_trade_usdc, Decimal("10.00"))
