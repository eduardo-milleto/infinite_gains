from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.core.exceptions import MarketDiscoveryError
from src.core.types import MarketContext
from src.services.market_discovery.gamma_client import GammaClient
from src.services.market_discovery.market_validator import MarketValidator


class MarketFinder:
    def __init__(self, gamma_client: GammaClient, validator: MarketValidator) -> None:
        self._gamma_client = gamma_client
        self._validator = validator

    async def discover_next_market(self, *, now_utc: datetime | None = None) -> MarketContext:
        now = now_utc or datetime.now(tz=timezone.utc)
        markets = await self._gamma_client.list_markets(limit=300)

        candidates: list[MarketContext] = []
        for market in markets:
            context = self._to_market_context(market)
            if context is None:
                continue
            if context.market_end_time <= now:
                continue
            candidates.append(context)

        if not candidates:
            raise MarketDiscoveryError("No active BTC hourly market found")

        candidates.sort(key=lambda item: item.market_end_time)
        chosen = candidates[0]
        self._validator.validate(chosen, now_utc=now)
        return chosen

    def _to_market_context(self, market: dict[str, Any]) -> MarketContext | None:
        title = str(market.get("question") or market.get("title") or market.get("slug") or "").lower()
        if not self._is_target_btc_hourly_market(market, title):
            return None

        condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
        slug = str(market.get("slug") or "")
        market_end_time_raw = market.get("endDate") or market.get("end_date") or market.get("endTime")
        if not condition_id or not slug or not market_end_time_raw:
            return None

        market_end_time = self._parse_datetime(str(market_end_time_raw))

        tokens = market.get("tokens")
        token_id_up = ""
        token_id_down = ""
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                outcome = str(token.get("outcome") or token.get("name") or "").lower()
                token_id = str(token.get("token_id") or token.get("tokenId") or token.get("id") or "")
                if outcome in {"yes", "up", "higher"} and token_id:
                    token_id_up = token_id
                if outcome in {"no", "down", "lower"} and token_id:
                    token_id_down = token_id

        clob_ids = market.get("clobTokenIds") or market.get("clob_token_ids")
        if isinstance(clob_ids, list) and len(clob_ids) >= 2:
            if not token_id_up:
                token_id_up = str(clob_ids[0])
            if not token_id_down:
                token_id_down = str(clob_ids[1])

        if not token_id_up or not token_id_down:
            return None

        spread = self._extract_spread(market)
        tick_size = Decimal(str(market.get("tickSize") or market.get("tick_size") or "0.01"))
        resolution_source = str(market.get("resolutionSource") or market.get("resolution_source") or "")
        up_price, down_price = self._extract_token_prices(market)

        return MarketContext(
            market_slug=slug,
            condition_id=condition_id,
            token_id_up=token_id_up,
            token_id_down=token_id_down,
            spread=spread,
            tick_size=tick_size,
            market_end_time=market_end_time,
            resolution_source=resolution_source,
            up_price=up_price,
            down_price=down_price,
        )

    def _is_target_btc_hourly_market(self, market: dict[str, Any], title: str) -> bool:
        if "btc" not in title and "bitcoin" not in title:
            return False

        # Explicitly reject shorter intraday contracts.
        lower_timeframes = ("5 minute", "5m", "15 minute", "15m", "30 minute", "30m")
        if any(token in title for token in lower_timeframes):
            return False

        # Accept explicit hourly wording quickly.
        if "hour" in title or "1h" in title or "60 minute" in title or "60m" in title:
            return True

        # Fall back to duration-based detection when start/end exist.
        start_raw = market.get("startDate") or market.get("start_date") or market.get("startTime")
        end_raw = market.get("endDate") or market.get("end_date") or market.get("endTime")
        if not start_raw or not end_raw:
            return False

        try:
            start = self._parse_datetime(str(start_raw))
            end = self._parse_datetime(str(end_raw))
        except ValueError:
            return False

        duration_seconds = (end - start).total_seconds()
        # Hourly markets are expected around 60 minutes; keep a tolerance window.
        return 45 * 60 <= duration_seconds <= 75 * 60

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        sanitized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(sanitized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _extract_spread(market: dict[str, Any]) -> Decimal:
        direct = market.get("spread")
        if direct is not None:
            return Decimal(str(direct))

        best_bid = market.get("bestBid") or market.get("best_bid")
        best_ask = market.get("bestAsk") or market.get("best_ask")
        if best_bid is not None and best_ask is not None:
            return abs(Decimal(str(best_ask)) - Decimal(str(best_bid)))
        return Decimal("0")

    @staticmethod
    def _extract_token_prices(market: dict[str, Any]) -> tuple[Decimal, Decimal]:
        up_price: Decimal | None = None
        down_price: Decimal | None = None

        tokens = market.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                outcome = str(token.get("outcome") or token.get("name") or "").lower()
                raw_price = (
                    token.get("price")
                    or token.get("lastPrice")
                    or token.get("bestAsk")
                    or token.get("bestBid")
                )
                if raw_price is None:
                    continue
                price = Decimal(str(raw_price))
                if outcome in {"yes", "up", "higher"}:
                    up_price = price
                if outcome in {"no", "down", "lower"}:
                    down_price = price

        if up_price is None and down_price is None:
            best_bid = market.get("bestBid") or market.get("best_bid")
            best_ask = market.get("bestAsk") or market.get("best_ask")
            if best_bid is not None and best_ask is not None:
                mid = (Decimal(str(best_bid)) + Decimal(str(best_ask))) / Decimal("2")
                up_price = mid

        if up_price is None and down_price is not None:
            up_price = Decimal("1") - down_price
        if down_price is None and up_price is not None:
            down_price = Decimal("1") - up_price
        if up_price is None:
            up_price = Decimal("0.50")
        if down_price is None:
            down_price = Decimal("0.50")

        return up_price, down_price
