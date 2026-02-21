from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import select
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.config.settings import Settings
from src.core.enums import ConfigChangedBy, ExitMode, OpenClawProposalStatus, ProposalStatus
from src.db.engine import Database
from src.db.models import PerformanceMetricsModel
from src.db.repository import AIDecisionRepo, ConfigRepo, OpenClawProposalRepo, TradeRepo
from src.services.learning.approval_workflow import ApprovalWorkflow
from src.services.openclaw.analyzer import OpenClawAnalyzer
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


def _apply_runtime_change(settings: Settings, key: str, raw_value: str) -> None:
    if not hasattr(settings, key):
        return
    current = getattr(settings, key)
    casted = _cast_runtime_value(raw_value, current)
    setattr(settings, key, casted)


def _cast_runtime_value(raw_value: str, current: object) -> object:
    if isinstance(current, Enum):
        enum_type = type(current)
        return enum_type(raw_value)
    if isinstance(current, bool):
        return raw_value.lower() in {"true", "1", "yes", "on"}
    if isinstance(current, int):
        return int(raw_value)
    if isinstance(current, float):
        return float(raw_value)
    if isinstance(current, Decimal):
        return Decimal(raw_value)
    return raw_value


async def _record_change(
    deps: CommandDependencies,
    *,
    config_section: str,
    param_key: str,
    new_value: str,
    username: str,
    justification: str,
) -> None:
    async with deps.database.session() as session:
        repo = ConfigRepo(session)
        old_value = await repo.get_latest_value(
            config_section=config_section,
            param_key=param_key,
            status=ProposalStatus.APPROVED,
        )
        await repo.create_change(
            config_section=config_section,
            param_key=param_key,
            old_value=old_value,
            new_value=new_value,
            changed_by=ConfigChangedBy.HUMAN_TELEGRAM.value,
            proposal_id=None,
            justification=justification,
            approved_by=username,
            status=ProposalStatus.APPROVED,
        )


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
            f"minimax_enabled={deps.settings.minimax_enabled}\n"
            f"exit_mode={deps.settings.exit_mode.value}\n"
            f"trades_today={deps.position_tracker.trades_today}\n"
            f"open_positions={deps.position_tracker.open_positions}"
        )
        await _reply(update, text)

    @guard
    async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        username = update.effective_user.username if update.effective_user else "unknown"
        await _record_change(
            deps,
            config_section="control",
            param_key="kill_switch_state",
            new_value="TRIPPED",
            username=username,
            justification="Paused via Telegram /pause",
        )
        await deps.kill_switch.trip("Paused via Telegram command")
        await _reply(update, "Kill switch activated")

    @guard
    async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        username = update.effective_user.username if update.effective_user else "unknown"
        await _record_change(
            deps,
            config_section="control",
            param_key="kill_switch_state",
            new_value="RESET",
            username=username,
            justification="Resumed via Telegram /resume",
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
    async def cmd_ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            ai_repo = AIDecisionRepo(session)
            stats = await ai_repo.summary_stats()
        text = (
            f"minimax_enabled={deps.settings.minimax_enabled}\n"
            f"model={deps.settings.minimax_model}\n"
            f"fallback_mode={deps.settings.ai_fallback_mode.value}\n"
            f"total_decisions={stats['total_decisions']}\n"
            f"veto_rate={stats['veto_rate']}\n"
            f"avg_latency_ms={stats['avg_latency_ms']}\n"
            f"fallback_used={stats['fallback_count']}"
        )
        await _reply(update, text)

    @guard
    async def cmd_ai_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        target: bool
        if context.args:
            arg = context.args[0].lower()
            if arg not in {"on", "off"}:
                await _reply(update, "Usage: /ai_toggle [on|off]")
                return
            target = arg == "on"
        else:
            target = not deps.settings.minimax_enabled

        username = update.effective_user.username if update.effective_user else "unknown"
        await _record_change(
            deps,
            config_section="ai",
            param_key="minimax_enabled",
            new_value=str(target).lower(),
            username=username,
            justification="Changed via Telegram /ai_toggle",
        )

        deps.settings.minimax_enabled = target
        await _reply(update, f"AI toggled: minimax_enabled={target}")

    @guard
    async def cmd_ai_reasoning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /ai_reasoning <trade_id>")
            return
        try:
            trade_id = int(context.args[0])
        except ValueError:
            await _reply(update, "trade_id must be an integer")
            return

        async with deps.database.session() as session:
            ai_repo = AIDecisionRepo(session)
            row = await ai_repo.get_by_trade_id(trade_id)

        if row is None:
            await _reply(update, f"No AI decision found for trade_id={trade_id}")
            return

        text = (
            f"trade_id={trade_id}\n"
            f"proceed={row.proceed}\n"
            f"edge={row.edge}\n"
            f"confidence={row.confidence}\n"
            f"position_size_factor={row.position_size_factor}\n"
            f"suggested_profit_target_cents={row.suggested_profit_target_cents}\n"
            f"suggested_stop_loss_cents={row.suggested_stop_loss_cents}\n"
            f"fallback_used={row.fallback_used}\n"
            f"outcome_pnl={row.outcome_pnl}\n"
            f"warning_flags={row.warning_flags}\n"
            f"reasoning={row.reasoning}"
        )
        await _reply(update, text)

    @guard
    async def cmd_exit_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            trade_repo = TradeRepo(session)
            exits = await trade_repo.list_recent_exits(limit=5)

        lines = [
            f"mode={deps.settings.exit_mode.value}",
            f"target={deps.settings.exit_profit_target_cents}c stop={deps.settings.exit_stop_loss_cents}c",
            f"time_before_close={deps.settings.exit_time_before_close_secs}s",
            f"reversal={deps.settings.exit_on_signal_reversal}",
            "last_exits:",
        ]
        if exits:
            for trade in exits:
                lines.append(
                    f"trade={trade.id} reason={trade.exit_reason} pnl={trade.pnl_usdc} "
                    f"entry={trade.price_entry} exit={trade.price_exit}"
                )
        else:
            lines.append("none")

        await _reply(update, "\n".join(lines))

    @guard
    async def cmd_exit_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /exit_mode scalp|hold")
            return
        arg = context.args[0].lower()
        if arg not in {"scalp", "hold"}:
            await _reply(update, "Usage: /exit_mode scalp|hold")
            return
        mode = ExitMode.SCALP if arg == "scalp" else ExitMode.HOLD
        username = update.effective_user.username if update.effective_user else "unknown"

        await _record_change(
            deps,
            config_section="exit",
            param_key="exit_mode",
            new_value=mode.value,
            username=username,
            justification="Changed via Telegram /exit_mode",
        )
        deps.settings.exit_mode = mode
        await _reply(update, f"Exit mode updated: {mode.value}")

    @guard
    async def cmd_exit_params(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /exit_params target=<cents> stop=<cents>")
            return

        target: int | None = None
        stop: int | None = None
        for arg in context.args:
            if arg.startswith("target="):
                try:
                    target = int(arg.split("=", 1)[1])
                except ValueError:
                    await _reply(update, "Invalid target value")
                    return
            elif arg.startswith("stop="):
                try:
                    stop = int(arg.split("=", 1)[1])
                except ValueError:
                    await _reply(update, "Invalid stop value")
                    return

        if target is None and stop is None:
            await _reply(update, "Usage: /exit_params target=<cents> stop=<cents>")
            return

        username = update.effective_user.username if update.effective_user else "unknown"

        if target is not None:
            clamped_target = max(deps.settings.exit_min_profit_cents, min(deps.settings.exit_max_profit_cents, target))
            await _record_change(
                deps,
                config_section="exit",
                param_key="exit_profit_target_cents",
                new_value=str(clamped_target),
                username=username,
                justification="Changed via Telegram /exit_params target",
            )
            deps.settings.exit_profit_target_cents = clamped_target

        if stop is not None:
            clamped_stop = max(deps.settings.exit_min_stop_cents, min(deps.settings.exit_max_stop_cents, stop))
            await _record_change(
                deps,
                config_section="exit",
                param_key="exit_stop_loss_cents",
                new_value=str(clamped_stop),
                username=username,
                justification="Changed via Telegram /exit_params stop",
            )
            deps.settings.exit_stop_loss_cents = clamped_stop

        await _reply(
            update,
            f"Exit params updated: target={deps.settings.exit_profit_target_cents} stop={deps.settings.exit_stop_loss_cents}",
        )

    @guard
    async def cmd_oc_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            repo = OpenClawProposalRepo(session)
            pending = await repo.pending_count()
            recent = await repo.list_recent(limit=3)

        lines = [f"openclaw_enabled={deps.settings.openclaw_enabled}", f"pending={pending}"]
        for row in recent:
            lines.append(f"#{row.id} {row.status} {row.analysis_type} {row.proposed_at.isoformat()}")
        await _reply(update, "\n".join(lines))

    @guard
    async def cmd_oc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        analyzer = OpenClawAnalyzer(deps.settings, deps.database)
        created = await analyzer.run_cycle(force=True)
        await _reply(update, f"OpenClaw analysis complete. proposals_created={created}")

    @guard
    async def cmd_oc_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /oc_approve <id>")
            return
        try:
            proposal_id = int(context.args[0])
        except ValueError:
            await _reply(update, "proposal id must be integer")
            return

        username = update.effective_user.username if update.effective_user else "unknown"

        async with deps.database.session() as session:
            proposal_repo = OpenClawProposalRepo(session)
            config_repo = ConfigRepo(session)
            proposal = await proposal_repo.get_by_id(proposal_id)
            if proposal is None:
                await _reply(update, f"OpenClaw proposal not found: {proposal_id}")
                return
            if proposal.status != OpenClawProposalStatus.PENDING.value:
                await _reply(update, f"Proposal {proposal_id} is not pending")
                return

            structured = proposal.structured_change
            config_section = str(structured.get("config_section", "openclaw"))
            param_key = str(structured.get("param_key", ""))
            new_value = str(structured.get("new_value", ""))
            old_value = str(structured.get("old_value", "")) or None
            justification = str(structured.get("justification", "Approved OpenClaw proposal"))

            if not param_key or not new_value:
                await _reply(update, f"Proposal {proposal_id} has invalid structured_change")
                return

            await config_repo.create_change(
                config_section=config_section,
                param_key=param_key,
                old_value=old_value,
                new_value=new_value,
                changed_by=ConfigChangedBy.HUMAN_TELEGRAM.value,
                proposal_id=None,
                justification=f"OpenClaw #{proposal_id}: {justification}",
                approved_by=username,
                status=ProposalStatus.APPROVED,
            )

            await proposal_repo.set_status(
                proposal_id=proposal_id,
                status=OpenClawProposalStatus.APPLIED,
                approved_by=username,
                approved_at=datetime.now(tz=timezone.utc),
                applied_at=datetime.now(tz=timezone.utc),
            )

        _apply_runtime_change(deps.settings, param_key, new_value)
        await _reply(update, f"OpenClaw proposal applied: {proposal_id}")

    @guard
    async def cmd_oc_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await _reply(update, "Usage: /oc_reject <id> [reason]")
            return
        try:
            proposal_id = int(context.args[0])
        except ValueError:
            await _reply(update, "proposal id must be integer")
            return

        reason = " ".join(context.args[1:]).strip() or "Rejected via Telegram"
        username = update.effective_user.username if update.effective_user else "unknown"

        async with deps.database.session() as session:
            repo = OpenClawProposalRepo(session)
            ok = await repo.set_status(
                proposal_id=proposal_id,
                status=OpenClawProposalStatus.REJECTED,
                approved_by=username,
                approved_at=datetime.now(tz=timezone.utc),
                outcome_note=reason,
            )

        if not ok:
            await _reply(update, f"OpenClaw proposal not found: {proposal_id}")
            return

        await _reply(update, f"OpenClaw proposal rejected: {proposal_id}")

    @guard
    async def cmd_oc_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        async with deps.database.session() as session:
            repo = OpenClawProposalRepo(session)
            rows = await repo.list_recent(limit=10)

        if not rows:
            await _reply(update, "No OpenClaw proposals yet")
            return

        lines = [
            f"#{row.id} {row.status} {row.analysis_type} outcome={row.outcome_note or '-'}"
            for row in rows
        ]
        await _reply(update, "\n".join(lines))

    @guard
    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        await _reply(
            update,
            "/status /pause /resume /pending /approve /reject /perf "
            "/ai_status /ai_toggle /ai_reasoning "
            "/exit_status /exit_mode /exit_params "
            "/oc_status /oc_approve /oc_reject /oc_analyze /oc_history"
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
        CommandHandler("ai_status", cmd_ai_status),
        CommandHandler("ai_toggle", cmd_ai_toggle),
        CommandHandler("ai_reasoning", cmd_ai_reasoning),
        CommandHandler("exit_status", cmd_exit_status),
        CommandHandler("exit_mode", cmd_exit_mode),
        CommandHandler("exit_params", cmd_exit_params),
        CommandHandler("oc_status", cmd_oc_status),
        CommandHandler("oc_approve", cmd_oc_approve),
        CommandHandler("oc_reject", cmd_oc_reject),
        CommandHandler("oc_analyze", cmd_oc_analyze),
        CommandHandler("oc_history", cmd_oc_history),
        CommandHandler("help", cmd_help),
    ]
