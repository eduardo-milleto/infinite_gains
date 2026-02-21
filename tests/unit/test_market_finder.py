from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.config.settings import Settings
from src.core.exceptions import MarketDiscoveryError
from src.services.market_discovery.market_finder import MarketFinder
from src.services.market_discovery.market_validator import MarketValidator


class FakeGammaClient:
    def __init__(self, payload, *, search_payload=None):
        self.payload = payload
        self.search_payload = search_payload if search_payload is not None else []
        self.calls: list[tuple[int | None, bool | None, bool | None]] = []
        self.search_calls: list[tuple[str, bool | None, bool | None]] = []

    async def list_markets(
        self,
        *,
        limit: int = 200,
        offset: int | None = None,
        order: str | None = None,
        ascending: bool | None = None,
        active: bool | None = True,
        closed: bool | None = False,
    ):
        del limit, order, ascending
        self.calls.append((offset, active, closed))
        if isinstance(self.payload, dict):
            return self.payload.get(offset or 0, [])
        return self.payload

    async def public_search(
        self,
        *,
        query: str,
        limit: int = 200,
        active: bool | None = True,
        closed: bool | None = False,
    ):
        del limit
        self.search_calls.append((query, active, closed))
        if isinstance(self.search_payload, dict):
            return self.search_payload.get(query, [])
        return self.search_payload


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


@pytest.mark.asyncio
async def test_market_finder_rejects_non_up_down_long_horizon_markets() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = [
        {
            "question": "Will Bitcoin hit $1M before GTA VI?",
            "slug": "will-bitcoin-hit-1m-before-gta-vi-872",
            "conditionId": "cond-long",
            "clobTokenIds": ["yes-token", "no-token"],
            "bestBid": "0.49",
            "bestAsk": "0.51",
            "tickSize": "0.01",
            "resolutionSource": "Binance",
            "endDate": (now + timedelta(days=365)).isoformat(),
            "tokens": [
                {"outcome": "Yes", "token_id": "yes-token"},
                {"outcome": "No", "token_id": "no-token"},
            ],
        }
    ]

    finder = MarketFinder(FakeGammaClient(payload), MarketValidator(Settings()))
    with pytest.raises(MarketDiscoveryError):
        await finder.discover_next_market(now_utc=now)


@pytest.mark.asyncio
async def test_market_finder_can_target_five_minute_contracts() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = [
        {
            "question": "Bitcoin Up or Down - 5 Minutes",
            "slug": "bitcoin-up-or-down-5-minute-1739836800",
            "conditionId": "cond-5m",
            "clobTokenIds": ["up5", "down5"],
            "bestBid": "0.50",
            "bestAsk": "0.52",
            "tickSize": "0.01",
            "resolutionSource": "Binance",
            "startDate": now.isoformat(),
            "endDate": (now + timedelta(minutes=5)).isoformat(),
        }
    ]

    finder = MarketFinder(FakeGammaClient(payload), MarketValidator(Settings()), target_interval="5m")
    context = await finder.discover_next_market(now_utc=now)

    assert context.condition_id == "cond-5m"
    assert context.token_id_up == "up5"
    assert context.token_id_down == "down5"


@pytest.mark.asyncio
async def test_market_finder_five_minute_target_rejects_hourly_market() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = [
        {
            "question": "Bitcoin Up or Down - Hourly",
            "slug": "bitcoin-up-or-down-hourly-1739836800",
            "conditionId": "cond-1h",
            "clobTokenIds": ["up1h", "down1h"],
            "bestBid": "0.50",
            "bestAsk": "0.52",
            "tickSize": "0.01",
            "resolutionSource": "Binance",
            "startDate": now.isoformat(),
            "endDate": (now + timedelta(hours=1)).isoformat(),
        }
    ]

    finder = MarketFinder(FakeGammaClient(payload), MarketValidator(Settings()), target_interval="5m")
    with pytest.raises(MarketDiscoveryError):
        await finder.discover_next_market(now_utc=now)


@pytest.mark.asyncio
async def test_market_finder_paginates_until_finding_btc_market() -> None:
    now = datetime.now(tz=timezone.utc)
    payload = {
        0: [
            {
                "question": "Will Trump deport 250000-500000 people?",
                "slug": "will-trump-deport-250000-500000-people",
                "conditionId": "cond-non-btc",
                "clobTokenIds": ["x", "y"],
                "bestBid": "0.48",
                "bestAsk": "0.50",
                "tickSize": "0.01",
                "resolutionSource": "Some source",
                "endDate": (now + timedelta(hours=1)).isoformat(),
            }
        ],
        500: [
            {
                "question": "Bitcoin Up or Down - 5 Minutes",
                "slug": "bitcoin-up-or-down-5-minute-1739836800",
                "conditionId": "cond-5m",
                "clobTokenIds": ["up5", "down5"],
                "bestBid": "0.50",
                "bestAsk": "0.52",
                "tickSize": "0.01",
                "resolutionSource": "Binance",
                "startDate": now.isoformat(),
                "endDate": (now + timedelta(minutes=5)).isoformat(),
            }
        ],
    }

    client = FakeGammaClient(payload)
    finder = MarketFinder(client, MarketValidator(Settings()), target_interval="5m")
    context = await finder.discover_next_market(now_utc=now)

    assert context.condition_id == "cond-5m"
    assert (500, True, False) in client.calls


@pytest.mark.asyncio
async def test_market_finder_prefers_public_search_when_available() -> None:
    now = datetime.now(tz=timezone.utc)
    search_payload = [
        {
            "question": "Bitcoin Up or Down - 5 Minutes",
            "slug": "bitcoin-up-or-down-5-minute-1739836800",
            "conditionId": "cond-search-5m",
            "clobTokenIds": ["up5", "down5"],
            "bestBid": "0.50",
            "bestAsk": "0.52",
            "tickSize": "0.01",
            "resolutionSource": "Binance",
            "startDate": now.isoformat(),
            "endDate": (now + timedelta(minutes=5)).isoformat(),
        }
    ]

    client = FakeGammaClient([], search_payload=search_payload)
    finder = MarketFinder(client, MarketValidator(Settings()), target_interval="5m")
    context = await finder.discover_next_market(now_utc=now)

    assert context.condition_id == "cond-search-5m"
    assert client.search_calls
    assert client.calls == []
