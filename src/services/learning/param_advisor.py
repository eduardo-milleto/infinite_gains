from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.config.settings import Settings
from src.core.enums import ConfigChangedBy
from src.core.types import ApprovalProposal
from src.db.models import PerformanceMetricsModel


class ParamAdvisor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate_proposals(self, metrics: PerformanceMetricsModel) -> list[ApprovalProposal]:
        proposals: list[ApprovalProposal] = []

        if metrics.total_trades >= 4 and metrics.win_rate < Decimal("0.40"):
            next_limit = max(2, self._settings.risk_max_trades_per_day - 1)
            if next_limit != self._settings.risk_max_trades_per_day:
                proposals.append(
                    ApprovalProposal(
                        proposal_id=str(uuid4()),
                        section="risk",
                        param_key="risk_max_trades_per_day",
                        old_value=str(self._settings.risk_max_trades_per_day),
                        new_value=str(next_limit),
                        justification="Win rate below 40% with enough samples; reduce daily exposure.",
                        changed_by=ConfigChangedBy.SYSTEM_LEARNING.value,
                        trading_mode=self._settings.trading_mode,
                    )
                )

        if metrics.signals_generated > 0:
            filter_ratio = Decimal(metrics.signals_filtered) / Decimal(metrics.signals_generated)
            if filter_ratio > Decimal("0.70"):
                increased_spread = self._settings.market_max_spread + Decimal("0.005")
                proposals.append(
                    ApprovalProposal(
                        proposal_id=str(uuid4()),
                        section="market",
                        param_key="market_max_spread",
                        old_value=str(self._settings.market_max_spread),
                        new_value=str(increased_spread.quantize(Decimal("0.001"))),
                        justification="High filter ratio suggests spread gate is too restrictive.",
                        changed_by=ConfigChangedBy.SYSTEM_LEARNING.value,
                        trading_mode=self._settings.trading_mode,
                    )
                )

        return proposals
