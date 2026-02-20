from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.config.settings import Settings
from src.core.exceptions import MarketDiscoveryError
from src.services.market_discovery.market_finder import MarketFinder
from src.services.market_discovery.market_validator import MarketValidator


class FakeGammaClient:
    def __init__(self, payload):
        self.payload = payload

    async def list_markets(self, *, limit: int = 200):
        del limit
        return self.payload


@pytest.mark.asyncio
async def test_market_finder_discovers_market() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = [
        {
            "question": "Will BTC go up this hour?",
            "slug": "btc-1h-up-or-down",
            "conditionId": "cond",
            "clobTokenIds": ["up", "down"],
            "bestBid": "0.48",
            "bestAsk": "0.50",
            "tickSize": "0.01",
            "resolutionSource": "Binance",
            "endDate": (now + timedelta(minutes=30)).isoformat(),
        }
    ]

    finder = MarketFinder(FakeGammaClient(payload), MarketValidator(Settings()))
    context = await finder.discover_next_market(now_utc=now)

    assert context.market_slug == "btc-1h-up-or-down"
    assert context.token_id_up == "up"
    assert context.token_id_down == "down"


@pytest.mark.asyncio
async def test_market_finder_raises_when_none_found() -> None:
    finder = MarketFinder(FakeGammaClient([]), MarketValidator(Settings()))

    with pytest.raises(MarketDiscoveryError):
        await finder.discover_next_market()
