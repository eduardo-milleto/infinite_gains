from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.core.enums import ConfigChangedBy
from src.core.types import ApprovalProposal
from src.db.models import AIDecisionModel


class AIPromptAdvisor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate(self, *, session: AsyncSession) -> tuple[list[ApprovalProposal], list[str]]:
        proposals: list[ApprovalProposal] = []
        notifications: list[str] = []

        since_utc = datetime.now(tz=timezone.utc) - timedelta(days=7)
        decisions = await self._fetch_recent_decisions(session=session, since_utc=since_utc)
        if not decisions:
            return proposals, notifications

        total = len(decisions)
        vetoes = [row for row in decisions if not row.proceed]
        veto_rate = Decimal(len(vetoes)) / Decimal(total)

        settled = [row for row in decisions if row.outcome_pnl is not None]
        settled_net = sum((Decimal(str(row.outcome_pnl)) for row in settled), Decimal("0"))

        if (
            veto_rate >= Decimal("0.65")
            and settled_net > 0
            and self._settings.ai_min_edge > Decimal("0.03")
        ):
            next_edge = (self._settings.ai_min_edge - Decimal("0.005")).quantize(Decimal("0.001"))
            proposals.append(
                ApprovalProposal(
                    proposal_id=str(uuid4()),
                    section="ai",
                    param_key="ai_min_edge",
                    old_value=str(self._settings.ai_min_edge),
                    new_value=str(next_edge),
                    justification=(
                        "AI veto rate is high while settled AI-approved trades stayed net positive; "
                        "reduce minimum edge threshold slightly."
                    ),
                    changed_by=ConfigChangedBy.SYSTEM_LEARNING.value,
                    trading_mode=self._settings.trading_mode,
                )
            )

        high = [row for row in settled if row.confidence >= 75]
        low = [row for row in settled if row.confidence < 75]

        high_win_rate = self._win_rate(high)
        low_win_rate = self._win_rate(low)
        if (
            len(high) >= 4
            and len(low) >= 4
            and high_win_rate < low_win_rate
            and self._settings.ai_min_confidence < 90
        ):
            next_confidence = min(90, self._settings.ai_min_confidence + 5)
            proposals.append(
                ApprovalProposal(
                    proposal_id=str(uuid4()),
                    section="ai",
                    param_key="ai_min_confidence",
                    old_value=str(self._settings.ai_min_confidence),
                    new_value=str(next_confidence),
                    justification=(
                        "High-confidence decisions underperformed lower-confidence ones; "
                        "raise minimum confidence threshold."
                    ),
                    changed_by=ConfigChangedBy.SYSTEM_LEARNING.value,
                    trading_mode=self._settings.trading_mode,
                )
            )

        flag_stats = self._warning_flag_stats(settled)
        for flag, (loss_rate, total_count) in flag_stats.items():
            if total_count >= 3 and loss_rate > Decimal("0.70"):
                notifications.append(
                    f"AI warning flag {flag} has loss_rate={loss_rate} over {total_count} settled decisions; review recommended."
                )

        return proposals, notifications

    async def _fetch_recent_decisions(
        self,
        *,
        session: AsyncSession,
        since_utc: datetime,
    ) -> list[AIDecisionModel]:
        query = select(AIDecisionModel).where(AIDecisionModel.evaluated_at >= since_utc)
        rows = (await session.execute(query)).scalars().all()
        return list(rows)

    @staticmethod
    def _win_rate(rows: list[AIDecisionModel]) -> Decimal:
        if not rows:
            return Decimal("0")
        wins = 0
        for row in rows:
            pnl = Decimal(str(row.outcome_pnl or 0))
            if pnl > 0:
                wins += 1
        return Decimal(wins) / Decimal(len(rows))

    @staticmethod
    def _warning_flag_stats(rows: list[AIDecisionModel]) -> dict[str, tuple[Decimal, int]]:
        aggregate: dict[str, tuple[int, int]] = {}
        for row in rows:
            pnl = Decimal(str(row.outcome_pnl or 0))
            is_loss = pnl <= 0
            for flag in row.warning_flags or []:
                wins, total = aggregate.get(flag, (0, 0))
                if is_loss:
                    wins += 1
                total += 1
                aggregate[flag] = (wins, total)

        result: dict[str, tuple[Decimal, int]] = {}
        for flag, (losses, total) in aggregate.items():
            loss_rate = Decimal("0") if total == 0 else Decimal(losses) / Decimal(total)
            result[flag] = (loss_rate.quantize(Decimal("0.0001")), total)
        return result
