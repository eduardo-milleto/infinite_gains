from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.core.exceptions import APIFailureError
from src.core.types import AIDecision, AITradingContext

_ALLOWED_FLAGS = {
    "LOW_CONFIDENCE",
    "LOW_EDGE",
    "COUNTER_TREND",
    "HIGH_SPREAD",
    "NEAR_CLOSE",
    "THIN_BOOK",
    "POOR_RECENT_PERFORMANCE",
    "AI_UNCERTAINTY",
    "CONFLICTING_SIGNALS",
}


class ResponseParser:
    def parse(self, raw_content: str, context: AITradingContext, *, fallback_used: bool = False) -> AIDecision:
        payload = self._load_json(raw_content)

        proceed = bool(payload.get("proceed", False))
        direction_probability = self._clamp_decimal(payload.get("direction_probability"), Decimal("0.35"), Decimal("0.65"), default=Decimal("0.50"))
        market_price = self._clamp_decimal(payload.get("market_price"), Decimal("0.00"), Decimal("1.00"), default=context.target_market_price)
        confidence = self._clamp_int(payload.get("confidence"), 0, 100, default=50)
        position_size_factor = self._clamp_decimal(payload.get("position_size_factor"), Decimal("0.50"), Decimal("1.00"), default=Decimal("0.75"))
        suggested_profit_target_cents = self._clamp_optional_int(
            payload.get("suggested_profit_target_cents"),
            1,
            100,
        )
        suggested_stop_loss_cents = self._clamp_optional_int(
            payload.get("suggested_stop_loss_cents"),
            1,
            100,
        )

        edge = (direction_probability - market_price).quantize(Decimal("0.0001"))

        reasoning = str(payload.get("reasoning", "AI reasoning unavailable"))
        warning_flags = self._parse_warning_flags(payload.get("warning_flags"))

        return AIDecision(
            proceed=proceed,
            direction_probability=direction_probability,
            market_price=market_price,
            edge=edge,
            confidence=confidence,
            position_size_factor=position_size_factor,
            reasoning=reasoning,
            warning_flags=tuple(warning_flags),
            suggested_profit_target_cents=suggested_profit_target_cents,
            suggested_stop_loss_cents=suggested_stop_loss_cents,
            fallback_used=fallback_used,
        )

    def fallback_decision(self, context: AITradingContext, *, proceed: bool, reason: str) -> AIDecision:
        base_market_price = context.target_market_price.quantize(Decimal("0.0001"))
        probability = base_market_price
        edge = (probability - base_market_price).quantize(Decimal("0.0001"))
        flags = ["AI_UNCERTAINTY"]
        return AIDecision(
            proceed=proceed,
            direction_probability=probability,
            market_price=base_market_price,
            edge=edge,
            confidence=0,
            position_size_factor=Decimal("0.50"),
            reasoning=reason,
            warning_flags=tuple(flags),
            suggested_profit_target_cents=None,
            suggested_stop_loss_cents=None,
            fallback_used=True,
        )

    @staticmethod
    def _load_json(raw_content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise APIFailureError(f"AI response is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise APIFailureError("AI response JSON must be an object")
        return parsed

    @staticmethod
    def _clamp_decimal(raw: Any, low: Decimal, high: Decimal, *, default: Decimal) -> Decimal:
        try:
            value = Decimal(str(raw))
        except Exception:
            value = default
        if value < low:
            return low
        if value > high:
            return high
        return value.quantize(Decimal("0.0001"))

    @staticmethod
    def _clamp_int(raw: Any, low: int, high: int, *, default: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        if value < low:
            return low
        if value > high:
            return high
        return value

    @staticmethod
    def _parse_warning_flags(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        parsed: list[str] = []
        for item in raw:
            item_str = str(item)
            if item_str in _ALLOWED_FLAGS and item_str not in parsed:
                parsed.append(item_str)
        return parsed

    @staticmethod
    def _clamp_optional_int(raw: Any, low: int, high: int) -> int | None:
        if raw is None:
            return None
        try:
            value = int(raw)
        except Exception:
            return None
        if value < low:
            return low
        if value > high:
            return high
        return value
