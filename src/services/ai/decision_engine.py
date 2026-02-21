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
