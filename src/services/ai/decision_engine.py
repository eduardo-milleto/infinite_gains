from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.enums import AIFallbackMode
from src.core.types import AIDecision, AITradingContext, MarketContext, Signal
from src.db.repository import AIDecisionRepo
from src.services.ai.context_builder import ContextBuilder
from src.services.ai.minimax_client import MiniMaxClient
from src.services.ai.prompt_builder import PromptBuilder
from src.services.ai.response_parser import ResponseParser

logger = structlog.get_logger(__name__)

AlertCallback = Callable[[str], Awaitable[None]]


class DecisionEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        minimax_client: MiniMaxClient,
        context_builder: ContextBuilder,
        prompt_builder: PromptBuilder,
        response_parser: ResponseParser,
        alert_callback: AlertCallback | None = None,
    ) -> None:
        self._settings = settings
        self._minimax_client = minimax_client
        self._context_builder = context_builder
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._alert_callback = alert_callback
        self._consecutive_failures = 0

    async def close(self) -> None:
        await self._context_builder.close()
        await self._minimax_client.close()

    async def evaluate(
        self,
        *,
        signal_id: int,
        signal: Signal,
        market_context: MarketContext,
        now_utc: datetime,
        session: AsyncSession,
    ) -> tuple[AIDecision, int]:
        context = await self._context_builder.build(
            signal_id=signal_id,
            signal=signal,
            market_context=market_context,
            now_utc=now_utc,
            session=session,
        )

        if not self._settings.minimax_enabled:
            decision = self._fallback(context, reason="AI disabled by feature flag")
            row = await self._persist_decision(
                session=session,
                signal_id=signal_id,
                decision=decision,
                latency_ms=0,
                raw_response_hash=self._hash_payload({"fallback": "disabled"}),
                model_id=self._settings.minimax_model,
            )
            return decision, row.id

        started = perf_counter()
        raw_payload: dict[str, object] | None = None

        try:
            system_prompt = self._prompt_builder.build_system_prompt()
            user_prompt = self._prompt_builder.build_user_prompt(context)
            raw_payload = await asyncio.wait_for(
                self._minimax_client.create_decision(system_prompt=system_prompt, user_prompt=user_prompt),
                timeout=self._settings.ai_max_latency_ms / 1000,
            )
            raw_content = self._minimax_client.extract_content(raw_payload)
            decision = self._response_parser.parse(raw_content, context)
            self._consecutive_failures = 0
        except Exception as exc:
            self._consecutive_failures += 1
            logger.warning("ai_decision_fallback", error=str(exc), failures=self._consecutive_failures)
            decision = self._fallback(context, reason=f"AI fallback: {exc}")
            if self._consecutive_failures >= self._settings.ai_max_consecutive_failures:
                if self._alert_callback is not None:
                    await self._alert_callback(
                        f"AI consecutive failures reached {self._consecutive_failures}"
                    )

        elapsed_ms = int((perf_counter() - started) * 1000)
        raw_response_hash = self._hash_payload(raw_payload or {"fallback": True, "reason": decision.reasoning})
        row = await self._persist_decision(
            session=session,
            signal_id=signal_id,
            decision=decision,
            latency_ms=elapsed_ms,
            raw_response_hash=raw_response_hash,
            model_id=self._settings.minimax_model,
        )
        return decision, row.id

    async def select_market(
        self,
        *,
        signal: Signal,
        candidates: list[MarketContext],
        now_utc: datetime,
    ) -> MarketContext:
        if not candidates:
            raise ValueError("No market candidates provided")
        if len(candidates) == 1:
            return candidates[0]
        if not self._settings.minimax_enabled or not self._settings.ai_market_selection_enabled:
            return self._fallback_market_selection(signal=signal, candidates=candidates, now_utc=now_utc)

        started = perf_counter()
        raw_payload: dict[str, object] | None = None
        fallback = self._fallback_market_selection(signal=signal, candidates=candidates, now_utc=now_utc)
        try:
            system_prompt, user_prompt = self._build_market_selection_prompts(
                signal=signal,
                candidates=candidates,
                now_utc=now_utc,
            )
            raw_payload = await asyncio.wait_for(
                self._minimax_client.create_decision(system_prompt=system_prompt, user_prompt=user_prompt),
                timeout=self._settings.ai_max_latency_ms / 1000,
            )
            raw_content = self._minimax_client.extract_content(raw_payload)
            chosen_slug = self._parse_selected_market_slug(raw_content)
            for candidate in candidates:
                if candidate.market_slug == chosen_slug:
                    logger.info(
                        "ai_market_selected",
                        market_slug=candidate.market_slug,
                        latency_ms=int((perf_counter() - started) * 1000),
                    )
                    return candidate
            logger.warning("ai_market_selection_unknown_slug", chosen_slug=chosen_slug)
        except Exception as exc:
            logger.warning("ai_market_selection_fallback", error=str(exc))

        logger.info(
            "ai_market_selected_fallback",
            market_slug=fallback.market_slug,
            latency_ms=int((perf_counter() - started) * 1000),
            raw_hash=self._hash_payload(raw_payload or {"fallback": True}),
        )
        return fallback

    async def link_trade(self, *, session: AsyncSession, ai_decision_id: int, trade_id: int) -> None:
        repo = AIDecisionRepo(session)
        await repo.attach_trade(ai_decision_id, trade_id)

    async def settle_trade_outcome(
        self,
        *,
        session: AsyncSession,
        trade_id: int,
        outcome_pnl: Decimal,
        settled_at: datetime,
    ) -> None:
        repo = AIDecisionRepo(session)
        await repo.settle_outcome_by_trade_id(
            trade_id=trade_id,
            outcome_pnl=outcome_pnl,
            settled_at=settled_at,
        )

    def _fallback(self, context: AITradingContext, *, reason: str) -> AIDecision:
        mode = self._settings.ai_fallback_mode
        proceed = mode == AIFallbackMode.PROCEED
        if mode == AIFallbackMode.TELEGRAM:
            reason = f"{reason}. Manual Telegram review required."
            proceed = False
        return self._response_parser.fallback_decision(context, proceed=proceed, reason=reason)

    async def _persist_decision(
        self,
        *,
        session: AsyncSession,
        signal_id: int,
        decision: AIDecision,
        latency_ms: int,
        raw_response_hash: str,
        model_id: str,
    ):
        repo = AIDecisionRepo(session)
        return await repo.create(
            signal_id=signal_id,
            evaluated_at=datetime.now(tz=timezone.utc),
            model_id=model_id,
            fallback_used=decision.fallback_used,
            latency_ms=latency_ms,
            raw_response_hash=raw_response_hash,
            decision=decision,
        )

    @staticmethod
    def _hash_payload(payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _build_market_selection_prompts(
        self,
        *,
        signal: Signal,
        candidates: list[MarketContext],
        now_utc: datetime,
    ) -> tuple[str, str]:
        system_prompt = (
            "You select the best Polymarket BTC up/down market for a single trade. "
            "Optimize for executable quality: low spread, enough time before close, and favorable entry price "
            "for the requested direction. Return strict JSON only."
        )
        payload = {
            "signal_type": signal.signal_type.value,
            "now_utc": now_utc.isoformat(),
            "max_spread": str(self._settings.market_max_spread),
            "no_trade_before_close_secs": self._settings.market_no_trade_before_close_secs,
            "candidates": [
                {
                    "market_slug": candidate.market_slug,
                    "spread": str(candidate.spread),
                    "up_price": str(candidate.up_price),
                    "down_price": str(candidate.down_price),
                    "seconds_to_close": int((candidate.market_end_time - now_utc).total_seconds()),
                }
                for candidate in candidates[:20]
            ],
            "schema": {"chosen_market_slug": "string", "confidence": "0-100", "reasoning": "short string"},
        }
        user_prompt = json.dumps(payload, ensure_ascii=True)
        return system_prompt, user_prompt

    @staticmethod
    def _parse_selected_market_slug(raw_content: str) -> str:
        parsed = json.loads(raw_content)
        if not isinstance(parsed, dict):
            raise ValueError("AI market selection response is not an object")
        slug = str(parsed.get("chosen_market_slug", "")).strip()
        if not slug:
            raise ValueError("AI market selection response missing chosen_market_slug")
        return slug

    def _fallback_market_selection(
        self,
        *,
        signal: Signal,
        candidates: list[MarketContext],
        now_utc: datetime,
    ) -> MarketContext:
        direction_is_up = signal.direction is not None and signal.direction.value == "UP"

        def score(candidate: MarketContext) -> tuple[Decimal, int]:
            seconds_to_close = int((candidate.market_end_time - now_utc).total_seconds())
            side_price = candidate.up_price if direction_is_up else candidate.down_price
            close_penalty = 1 if seconds_to_close <= self._settings.market_no_trade_before_close_secs else 0
            # Lower score is better: tighter spread, cheaper side price for selected direction, more time before close.
            return (
                candidate.spread + (side_price / Decimal("10")) + (Decimal(close_penalty) * Decimal("10")),
                -seconds_to_close,
            )

        return min(candidates, key=score)
