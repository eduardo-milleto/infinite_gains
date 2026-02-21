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

    async def list_markets(self, *, limit: int = 200, **kwargs):
        del limit
        del kwargs
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


@pytest.mark.asyncio
async def test_market_finder_accepts_hourly_slug_and_string_clob_ids() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = [
        {
            "question": "BTC Up or Down - Feb 21, 2PM ET",
            "slug": "btc-up-or-down-february-21-2pm-et",
            "conditionId": "cond-hourly",
            "clobTokenIds": "[\"token-up\",\"token-down\"]",
            "bestBid": "0.49",
            "bestAsk": "0.51",
            "tickSize": "0.01",
            "rules": "This market resolves according to Binance BTC/USDT price.",
            "endDate": (now + timedelta(minutes=25)).isoformat(),
        }
    ]

    finder = MarketFinder(FakeGammaClient(payload), MarketValidator(Settings()))
    context = await finder.discover_next_market(now_utc=now)

    assert context.market_slug == "btc-up-or-down-february-21-2pm-et"
    assert context.token_id_up == "token-up"
    assert context.token_id_down == "token-down"
