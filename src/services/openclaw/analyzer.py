from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import and_, select

from src.config.settings import Settings
from src.core.enums import OpenClawProposalStatus
from src.db.engine import Database
from src.db.models import OpenClawProposalModel, TradeModel
from src.db.repository import OpenClawProposalRepo

logger = structlog.get_logger(__name__)


class OpenClawAnalyzer:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database

    async def run_cycle(self, *, force: bool = False) -> int:
        if not self._settings.openclaw_enabled and not force:
            return 0

        async with self._database.session() as session:
            since = datetime.now(tz=timezone.utc) - timedelta(days=14)
            trades = await self._fetch_recent_settled_trades(session=session, since_utc=since)
            if len(trades) < self._settings.openclaw_min_trades_for_analysis and not force:
                return 0

            repo = OpenClawProposalRepo(session)
            proposals = self._build_proposals(trades)
            created_rows: list[OpenClawProposalModel] = []
            created = 0
            for proposal in proposals:
                row = await repo.create(
                    proposed_at=datetime.now(tz=timezone.utc),
                    analysis_type=proposal["analysis_type"],
                    findings=proposal["findings"],
                    proposal_text=proposal["proposal_text"],
                    structured_change=proposal["structured_change"],
                    evidence_window_days=proposal["evidence_window_days"],
                    status=OpenClawProposalStatus.PENDING,
                )
                created_rows.append(row)
                created += 1

            if created_rows:
                await self._send_telegram_summary(created_rows)

            logger.info("openclaw_cycle_complete", created=created, force=force)
            return created

    async def _fetch_recent_settled_trades(
        self,
        *,
        session,
        since_utc: datetime,
    ) -> list[TradeModel]:
        query = select(TradeModel).where(
            and_(
                TradeModel.candle_open_utc >= since_utc,
                TradeModel.pnl_usdc.is_not(None),
            )
        )
        rows = (await session.execute(query)).scalars().all()
        return list(rows)

    def _build_proposals(self, trades: list[TradeModel]) -> list[dict[str, object]]:
        if not trades:
            return []

        proposals: list[dict[str, object]] = []
        wins = sum(1 for trade in trades if Decimal(str(trade.pnl_usdc or 0)) > 0)
        win_rate = Decimal(wins) / Decimal(len(trades))

        stop_losses = sum(1 for trade in trades if str(trade.exit_reason or "") == "STOP_LOSS")
        profit_targets = sum(1 for trade in trades if str(trade.exit_reason or "") == "PROFIT_TARGET")

        if (
            win_rate < Decimal("0.50")
            and stop_losses > profit_targets
            and self._settings.exit_stop_loss_cents < self._settings.exit_max_stop_cents
        ):
            new_stop = self._settings.exit_stop_loss_cents + 1
            proposals.append(
                {
                    "analysis_type": "EXIT_CALIBRATION",
                    "findings": {
                        "window_trades": len(trades),
                        "win_rate": str(win_rate.quantize(Decimal("0.0001"))),
                        "stop_losses": stop_losses,
                        "profit_targets": profit_targets,
                    },
                    "proposal_text": (
                        "Stop loss is triggering more often than profit targets in a low-win-rate window; "
                        "increase exit_stop_loss_cents by 1 to reduce premature exits."
                    ),
                    "structured_change": {
                        "config_section": "exit",
                        "param_key": "exit_stop_loss_cents",
                        "old_value": str(self._settings.exit_stop_loss_cents),
                        "new_value": str(new_stop),
                        "justification": "OpenClaw suggested stop widening based on recent stop-loss concentration.",
                        "proposal_ref": str(uuid4()),
                    },
                    "evidence_window_days": 14,
                }
            )

        if (
            win_rate > Decimal("0.70")
            and profit_targets > stop_losses
            and self._settings.exit_profit_target_cents < self._settings.exit_max_profit_cents
        ):
            new_target = self._settings.exit_profit_target_cents + 1
            proposals.append(
                {
                    "analysis_type": "EXIT_OPTIMIZATION",
                    "findings": {
                        "window_trades": len(trades),
                        "win_rate": str(win_rate.quantize(Decimal("0.0001"))),
                        "stop_losses": stop_losses,
                        "profit_targets": profit_targets,
                    },
                    "proposal_text": (
                        "Recent trade window shows strong hit-rate on profit targets; "
                        "increase exit_profit_target_cents by 1 for better per-trade expectancy."
                    ),
                    "structured_change": {
                        "config_section": "exit",
                        "param_key": "exit_profit_target_cents",
                        "old_value": str(self._settings.exit_profit_target_cents),
                        "new_value": str(new_target),
                        "justification": "OpenClaw suggested profit target increase based on recent momentum behavior.",
                        "proposal_ref": str(uuid4()),
                    },
                    "evidence_window_days": 14,
                }
            )

        return proposals

    async def _send_telegram_summary(self, proposals: list[OpenClawProposalModel]) -> None:
        bot_token = self._settings.telegram_bot_token.get_secret_value()
        chat_ids = self._settings.telegram_allowed_chat_ids
        if not bot_token or not chat_ids:
            return

        lines = [
            "OpenClaw analysis cycle complete.",
            f"New proposals: {len(proposals)}",
        ]
        for row in proposals[:3]:
            change = row.structured_change
            param_key = str(change.get("param_key", "-"))
            old_value = str(change.get("old_value", "-"))
            new_value = str(change.get("new_value", "-"))
            lines.append(
                f"#{row.id} {row.analysis_type}: {param_key} {old_value} -> {new_value}"
            )

        if len(proposals) > 3:
            lines.append(f"... and {len(proposals) - 3} more.")
        lines.append("Use /oc_status and /oc_approve <id> in Telegram.")
        message = "\n".join(lines)

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            for chat_id in chat_ids:
                try:
                    await client.post(url, json={"chat_id": chat_id, "text": message})
                except Exception as exc:
                    logger.warning(
                        "openclaw_telegram_notify_failed",
                        chat_id=chat_id,
                        error=str(exc),
                    )
