from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from src.config.settings import Settings
from src.core.enums import ProposalStatus
from src.core.types import ApprovalProposal
from src.db.engine import Database
from src.db.models import ConfigHistoryModel
from src.db.repository import ConfigRepo

AlertCallback = Callable[[str], Awaitable[None]]


class ApprovalWorkflow:
    def __init__(self, *, settings: Settings, database: Database, alert_callback: AlertCallback | None = None) -> None:
        self._settings = settings
        self._database = database
        self._alert_callback = alert_callback

    async def stage_proposals(self, proposals: list[ApprovalProposal]) -> int:
        if not proposals:
            return 0

        async with self._database.session() as session:
            repo = ConfigRepo(session)
            for proposal in proposals:
                await repo.create_change(
                    config_section=proposal.section,
                    param_key=proposal.param_key,
                    old_value=proposal.old_value,
                    new_value=proposal.new_value,
                    changed_by=proposal.changed_by,
                    proposal_id=proposal.proposal_id,
                    justification=proposal.justification,
                    status=ProposalStatus.PENDING,
                )

        if self._alert_callback is not None:
            for proposal in proposals:
                await self._alert_callback(
                    f"New proposal {proposal.proposal_id}: {proposal.param_key} {proposal.old_value} -> {proposal.new_value}"
                )

        return len(proposals)

    async def approve(self, proposal_id: str, approved_by: str) -> bool:
        async with self._database.session() as session:
            rows = await self._fetch_rows(session, proposal_id)
            if not rows:
                return False

            for row in rows:
                self._apply_setting_change(row.param_key, row.new_value)

            repo = ConfigRepo(session)
            await repo.set_proposal_status(
                proposal_id,
                status=ProposalStatus.APPROVED,
                approved_by=approved_by,
            )

        if self._alert_callback is not None:
            await self._alert_callback(f"Proposal approved: {proposal_id} by {approved_by}")
        return True

    async def reject(self, proposal_id: str, rejected_by: str) -> bool:
        async with self._database.session() as session:
            repo = ConfigRepo(session)
            updated = await repo.set_proposal_status(
                proposal_id,
                status=ProposalStatus.REJECTED,
                approved_by=rejected_by,
            )
        if updated and self._alert_callback is not None:
            await self._alert_callback(f"Proposal rejected: {proposal_id} by {rejected_by}")
        return updated > 0

    async def list_pending(self) -> list[ConfigHistoryModel]:
        async with self._database.session() as session:
            repo = ConfigRepo(session)
            return await repo.list_pending()

    async def _fetch_rows(self, session, proposal_id: str) -> list[ConfigHistoryModel]:
        query = select(ConfigHistoryModel).where(ConfigHistoryModel.proposal_id == proposal_id)
        rows = (await session.execute(query)).scalars().all()
        return list(rows)

    def _apply_setting_change(self, key: str, raw_value: str) -> None:
        if not hasattr(self._settings, key):
            return
        current = getattr(self._settings, key)
        casted = self._cast_value(raw_value, current)
        setattr(self._settings, key, casted)

    @staticmethod
    def _cast_value(raw_value: str, current: Any) -> Any:
        if isinstance(current, bool):
            return raw_value.lower() in {"true", "1", "yes", "on"}
        if isinstance(current, int):
            return int(raw_value)
        if isinstance(current, float):
            return float(raw_value)
        if isinstance(current, Decimal):
            return Decimal(raw_value)
        return raw_value
