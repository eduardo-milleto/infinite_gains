from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.core.exceptions import MarketDiscoveryError
from src.core.types import MarketContext
from src.services.market_discovery.gamma_client import GammaClient
from src.services.market_discovery.market_validator import MarketValidator


class MarketFinder:
    _LOWER_TIMEFRAME_MARKERS = ("1 minute", "1m", "5 minute", "5m", "15 minute", "15m", "30 minute", "30m")
    _UPPER_TIMEFRAME_MARKERS = ("day", "daily", "week", "weekly", "month", "monthly")
    _HOURLY_TEXT_MARKERS = ("hour", "hourly", "1h", "60 minute", "60m")
    _UP_DOWN_MARKERS = ("up or down", "up/down")
    _SLUG_TIME_MARKER_RE = re.compile(r"(?:^|-)(?:[1-9]|1[0-2])(?:am|pm)(?:-|$)")
    _INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)

    def __init__(
        self,
        gamma_client: GammaClient,
        validator: MarketValidator,
        *,
        target_interval: str = "1h",
    ) -> None:
        self._gamma_client = gamma_client
        self._validator = validator
        self._target_interval = target_interval.lower()
        self._target_interval_seconds = self._parse_interval_seconds(self._target_interval)

    async def discover_next_market(self, *, now_utc: datetime | None = None) -> MarketContext:
        now = now_utc or datetime.now(tz=timezone.utc)
        markets = await self._gamma_client.list_markets(limit=500, active=True, closed=False)
        candidates = self._extract_candidates(markets, now_utc=now)

        if not candidates:
            # Fallback query: some Gamma payloads omit `active` semantics for intraday contracts.
            fallback_markets = await self._gamma_client.list_markets(limit=500, active=None, closed=False)
            candidates = self._extract_candidates(fallback_markets, now_utc=now)
            if fallback_markets:
                markets = fallback_markets

        if not candidates:
            sample = ", ".join(self._sample_market_names(markets))
            raise MarketDiscoveryError(
                f"No active BTC hourly market found{f' (sample={sample})' if sample else ''}"
            )

        candidates.sort(key=lambda item: item.market_end_time)
        chosen = candidates[0]
        self._validator.validate(chosen, now_utc=now)
        return chosen

    def _extract_candidates(self, markets: list[dict[str, Any]], *, now_utc: datetime) -> list[MarketContext]:
        candidates: list[MarketContext] = []
        for market in markets:
            context = self._to_market_context(market)
            if context is None:
                continue
            if context.market_end_time <= now_utc:
                continue
            candidates.append(context)
        return candidates

    @staticmethod
    def _sample_market_names(markets: list[dict[str, Any]], *, limit: int = 5) -> tuple[str, ...]:
        names: list[str] = []
        for market in markets:
            candidate = str(market.get("slug") or market.get("question") or market.get("title") or "").strip()
            if candidate:
                names.append(candidate)
            if len(names) >= limit:
                break
        return tuple(names)

    def _to_market_context(self, market: dict[str, Any]) -> MarketContext | None:
        title = self._build_market_text_blob(market)
        if not self._is_target_btc_hourly_market(market, title):
            return None

        condition_id = self._extract_condition_id(market)
        slug = str(market.get("slug") or market.get("market_slug") or market.get("id") or condition_id)
        market_end_time_raw = self._extract_market_end_time_raw(market)
        if not condition_id or not slug or market_end_time_raw is None:
            return None

        market_end_time = self._parse_datetime(market_end_time_raw)

        token_id_up, token_id_down = self._extract_token_ids(market)
        if not token_id_up or not token_id_down:
            return None

        spread = self._extract_spread(market)
        tick_size = Decimal(str(market.get("tickSize") or market.get("tick_size") or "0.01"))
        resolution_source = self._extract_resolution_source(market)
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

    @staticmethod
    def _build_market_text_blob(market: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("question", "title", "slug", "market_slug", "ticker", "description", "rules"):
            value = market.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)

        events = market.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                for key in (
                    "title",
                    "slug",
                    "ticker",
                    "description",
                    "rules",
                    "resolutionSource",
                    "resolution_source",
                ):
                    value = event.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(value)

        return " ".join(parts).lower()

    def _is_target_btc_hourly_market(self, market: dict[str, Any], title: str) -> bool:
        if "btc" not in title and "bitcoin" not in title:
            return False

        if not self._has_up_down_semantics(market, title):
            return False

        if any(token in title for token in self._UPPER_TIMEFRAME_MARKERS):
            return False

        if self._target_interval_seconds >= 3600 and any(token in title for token in self._LOWER_TIMEFRAME_MARKERS):
            return False

        if self._target_interval_seconds == 3600 and any(token in title for token in self._HOURLY_TEXT_MARKERS):
            return True

        if self._target_interval_seconds == 300 and any(token in title for token in ("5 minute", "5m", "five minute")):
            return True

        slug = str(market.get("slug") or market.get("market_slug") or "").lower()
        if self._looks_like_hourly_slug(slug):
            return True

        duration_seconds = self._extract_duration_seconds(market)
        if duration_seconds is not None and self._duration_matches_target(duration_seconds):
            return True

        return False

    def _duration_matches_target(self, duration_seconds: float) -> bool:
        tolerance = max(60, int(self._target_interval_seconds * Decimal("0.35")))
        min_allowed = max(60, self._target_interval_seconds - tolerance)
        max_allowed = self._target_interval_seconds + tolerance
        return min_allowed <= duration_seconds <= max_allowed

    def _has_up_down_semantics(self, market: dict[str, Any], title: str) -> bool:
        if any(marker in title for marker in self._UP_DOWN_MARKERS):
            return True

        slug = str(market.get("slug") or market.get("market_slug") or "").lower()
        if "up-or-down" in slug or "updown" in slug:
            return True

        tokens = market.get("tokens")
        if isinstance(tokens, list):
            outcomes = {
                str(token.get("outcome") or token.get("name") or "").strip().lower()
                for token in tokens
                if isinstance(token, dict)
            }
            if {"up", "down"}.issubset(outcomes):
                return True
            if {"yes", "no"}.issubset(outcomes) and ("up" in title and "down" in title):
                return True

        return False

    def _extract_duration_seconds(self, market: dict[str, Any]) -> float | None:
        start_raw = self._extract_market_time_raw(
            market,
            keys=("startDate", "start_date", "startTime", "start_time"),
        )
        end_raw = self._extract_market_end_time_raw(market)
        if start_raw is None or end_raw is None:
            return None

        try:
            start = self._parse_datetime(start_raw)
            end = self._parse_datetime(end_raw)
        except ValueError:
            return None

        return (end - start).total_seconds()

    def _extract_market_end_time_raw(self, market: dict[str, Any]) -> Any | None:
        end = self._extract_market_time_raw(
            market,
            keys=("endDate", "end_date", "endTime", "end_time", "closeDate"),
        )
        if end is not None:
            return end

        events = market.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                end = self._extract_market_time_raw(
                    event,
                    keys=("endDate", "end_date", "endTime", "end_time", "closeDate"),
                )
                if end is not None:
                    return end

        return None

    @staticmethod
    def _extract_market_time_raw(payload: dict[str, Any], *, keys: tuple[str, ...]) -> Any | None:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _looks_like_hourly_slug(slug: str) -> bool:
        if not slug:
            return False
        if "btc" not in slug and "bitcoin" not in slug:
            return False
        if "up-or-down" not in slug and "updown" not in slug:
            return False
        if ("hour" in slug) or ("1h" in slug) or ("60m" in slug):
            return True
        if ("5-minute" in slug) or ("5m" in slug):
            return True
        if MarketFinder._SLUG_TIME_MARKER_RE.search(slug):
            return True
        return False

    @classmethod
    def _parse_interval_seconds(cls, interval: str) -> int:
        match = cls._INTERVAL_RE.match(interval)
        if not match:
            # Fallback to 1h default if someone sets uncommon TAAPI interval format.
            return 3600
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "m":
            return amount * 60
        if unit == "h":
            return amount * 3600
        if unit == "d":
            return amount * 86400
        return 3600

    def _extract_condition_id(self, market: dict[str, Any]) -> str:
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "").strip()
        if condition_id:
            return condition_id

        tokens = market.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                candidate = str(
                    token.get("conditionId")
                    or token.get("condition_id")
                    or token.get("marketConditionId")
                    or ""
                ).strip()
                if candidate:
                    return candidate

        return ""

    def _extract_token_ids(self, market: dict[str, Any]) -> tuple[str, str]:
        token_id_up = ""
        token_id_down = ""

        tokens = market.get("tokens")
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                outcome = str(token.get("outcome") or token.get("name") or "").lower()
                token_id = str(token.get("token_id") or token.get("tokenId") or token.get("id") or "").strip()
                if not token_id:
                    continue
                if outcome in {"yes", "up", "higher"}:
                    token_id_up = token_id
                elif outcome in {"no", "down", "lower"}:
                    token_id_down = token_id

        clob_ids = self._extract_clob_token_ids(market)
        if len(clob_ids) >= 2:
            if not token_id_up:
                token_id_up = clob_ids[0]
            if not token_id_down:
                token_id_down = clob_ids[1]

        return token_id_up, token_id_down

    @staticmethod
    def _extract_clob_token_ids(market: dict[str, Any]) -> list[str]:
        raw = market.get("clobTokenIds") or market.get("clob_token_ids")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]

        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            if "," in stripped:
                return [item.strip().strip('"').strip("'") for item in stripped.split(",") if item.strip()]

        return []

    @staticmethod
    def _extract_resolution_source(market: dict[str, Any]) -> str:
        direct = market.get("resolutionSource") or market.get("resolution_source")
        if isinstance(direct, str) and direct.strip():
            return direct

        for key in ("description", "rules"):
            value = market.get(key)
            if isinstance(value, str) and "binance" in value.lower():
                return "Binance"

        events = market.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_source = event.get("resolutionSource") or event.get("resolution_source")
                if isinstance(event_source, str) and event_source.strip():
                    return event_source
                for key in ("description", "rules"):
                    value = event.get(key)
                    if isinstance(value, str) and "binance" in value.lower():
                        return "Binance"

        return ""

    @staticmethod
    def _parse_datetime(value: str | int | float) -> datetime:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return parsed.astimezone(timezone.utc)

        raw = str(value).strip()
        if raw.isdigit():
            parsed = datetime.fromtimestamp(float(raw), tz=timezone.utc)
            return parsed.astimezone(timezone.utc)

        sanitized = raw.replace("Z", "+00:00")
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
                raw_price = token.get("price") or token.get("lastPrice") or token.get("bestAsk") or token.get("bestBid")
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
