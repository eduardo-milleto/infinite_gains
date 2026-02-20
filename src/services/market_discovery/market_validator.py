from __future__ import annotations

from datetime import datetime

from src.config.settings import Settings
from src.core.exceptions import MarketDiscoveryError
from src.core.types import MarketContext


class MarketValidator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate(self, context: MarketContext, *, now_utc: datetime) -> None:
        source = context.resolution_source.lower()
        if "binance" not in source:
            raise MarketDiscoveryError("Resolved market source is not Binance")

        if context.spread > self._settings.market_max_spread:
            raise MarketDiscoveryError("Market spread exceeds max allowed threshold")

        secs_to_close = (context.market_end_time - now_utc).total_seconds()
        if secs_to_close <= self._settings.market_no_trade_before_close_secs:
            raise MarketDiscoveryError("Market too close to close time")
