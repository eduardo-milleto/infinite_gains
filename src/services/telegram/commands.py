from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.config.settings import Settings
from src.core.enums import ConfigChangedBy, ProposalStatus
from src.db.engine import Database
from src.db.models import PerformanceMetricsModel
from src.db.repository import ConfigRepo
from src.services.learning.approval_workflow import ApprovalWorkflow
from src.services.risk.kill_switch import KillSwitch
from src.services.risk.position_tracker import PositionTracker

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


@dataclass
class CommandDependencies:
    settings: Settings
    database: Database
    kill_switch: KillSwitch
    position_tracker: PositionTracker
    approval_workflow: ApprovalWorkflow


def _is_authorized(update: Update, settings: Settings) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return False
    return chat_id in settings.telegram_allowed_chat_ids


def auth_required(deps: CommandDependencies) -> Callable[[HandlerFn], HandlerFn]:
    def decorator(func: HandlerFn) -> HandlerFn:
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not _is_authorized(update, deps.settings):
                if update.effective_message is not None:
                    await update.effective_message.reply_text("Unauthorized chat")
                return
            await func(update, context)

        return wrapper

    return decorator


async def _reply(update: Update, text: str) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(text)


def build_command_handlers(deps: CommandDependencies) -> list[CommandHandler]:
    guard = auth_required(deps)

    @guard
    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        await _reply(update, "Infinite Gains bot online")

    @guard
    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            config_repo = ConfigRepo(session)
            control_state = await config_repo.get_latest_value(
                config_section="control",
                param_key="kill_switch_state",
                status=ProposalStatus.APPROVED,
            )
        control_state_value = control_state or "NONE"
        text = (
            f"mode={deps.settings.trading_mode.value}\n"
            f"kill_switch={deps.kill_switch.is_tripped}\n"
            f"control_state={control_state_value}\n"
            f"trades_today={deps.position_tracker.trades_today}\n"
            f"open_positions={deps.position_tracker.open_positions}"
        )
        await _reply(update, text)

    @guard
    async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        username = update.effective_user.username if update.effective_user else "unknown"
        async with deps.database.session() as session:
            repo = ConfigRepo(session)
            old_value = await repo.get_latest_value(
                config_section="control",
                param_key="kill_switch_state",
                status=ProposalStatus.APPROVED,
            )
            await repo.create_change(
                config_section="control",
                param_key="kill_switch_state",
                old_value=old_value,
                new_value="TRIPPED",
                changed_by=ConfigChangedBy.HUMAN_TELEGRAM.value,
                proposal_id=None,
                justification="Paused via Telegram /pause",
                approved_by=username,
                status=ProposalStatus.APPROVED,
            )
        await deps.kill_switch.trip("Paused via Telegram command")
        await _reply(update, "Kill switch activated")

    @guard
    async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        username = update.effective_user.username if update.effective_user else "unknown"
        async with deps.database.session() as session:
            repo = ConfigRepo(session)
            old_value = await repo.get_latest_value(
                config_section="control",
                param_key="kill_switch_state",
                status=ProposalStatus.APPROVED,
            )
            await repo.create_change(
                config_section="control",
                param_key="kill_switch_state",
                old_value=old_value,
                new_value="RESET",
                changed_by=ConfigChangedBy.HUMAN_TELEGRAM.value,
                proposal_id=None,
                justification="Resumed via Telegram /resume",
                approved_by=username,
                status=ProposalStatus.APPROVED,
            )
        await deps.kill_switch.reset()
        await _reply(update, "Kill switch reset")

    @guard
    async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        rows = await deps.approval_workflow.list_pending()
        if not rows:
            await _reply(update, "No pending proposals")
            return
        lines = [
            f"{row.proposal_id}: {row.param_key} {row.old_value} -> {row.new_value}"
            for row in rows
            if row.proposal_id
        ]
        await _reply(update, "\n".join(lines))

    @guard
    async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /approve <proposal_id>")
            return
        proposal_id = context.args[0]
        username = update.effective_user.username if update.effective_user else "unknown"
        approved = await deps.approval_workflow.approve(proposal_id, approved_by=username)
        if approved:
            await _reply(update, f"Proposal approved: {proposal_id}")
        else:
            await _reply(update, f"Proposal not found: {proposal_id}")

    @guard
    async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /reject <proposal_id>")
            return
        proposal_id = context.args[0]
        username = update.effective_user.username if update.effective_user else "unknown"
        rejected = await deps.approval_workflow.reject(proposal_id, rejected_by=username)
        if rejected:
            await _reply(update, f"Proposal rejected: {proposal_id}")
        else:
            await _reply(update, f"Proposal not found: {proposal_id}")

    @guard
    async def cmd_perf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            query = select(PerformanceMetricsModel).order_by(PerformanceMetricsModel.metric_date.desc()).limit(1)
            metric = (await session.execute(query)).scalars().first()

        if metric is None:
            await _reply(update, "No performance metrics yet")
            return

        text = (
            f"date={metric.metric_date}\n"
            f"trades={metric.total_trades} wins={metric.wins} losses={metric.losses}\n"
            f"win_rate={metric.win_rate}\n"
            f"net_pnl={metric.net_pnl_usdc}"
        )
        await _reply(update, text)

    @guard
    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        await _reply(
            update,
            "/status /pause /resume /pending /approve /reject /perf"
        )

    return [
        CommandHandler("start", cmd_start),
        CommandHandler("status", cmd_status),
        CommandHandler("pause", cmd_pause),
        CommandHandler("resume", cmd_resume),
        CommandHandler("pending", cmd_pending),
        CommandHandler("approve", cmd_approve),
        CommandHandler("reject", cmd_reject),
        CommandHandler("perf", cmd_perf),
        CommandHandler("help", cmd_help),
    ]
