from __future__ import annotations

import json
from dataclasses import asdict

from src.core.types import AITradingContext


class PromptBuilder:
    def build_system_prompt(self) -> str:
        return (
            "You are an AI trading analyst for Polymarket BTC 1H direction markets. "
            "Resolution rule: market settles UP when Binance BTC/USDT 1H candle close >= open. "
            "Compute edge as direction_probability - market_price. "
            "direction_probability must remain in [0.35, 0.65]. "
            "Return raw JSON only, matching the requested schema exactly. "
            "Be conservative and prioritize avoiding bad trades over forcing entries."
        )

    def build_user_prompt(self, context: AITradingContext) -> str:
        payload = asdict(context)
        return (
            "Evaluate whether to proceed with this trade using edge over market price.\n"
            "Use schema:\n"
            "{\n"
            '  "proceed": bool,\n'
            '  "direction_probability": float [0.35-0.65],\n'
            '  "market_price": float,\n'
            '  "edge": float,\n'
            '  "confidence": int [0-100],\n'
            '  "position_size_factor": float [0.50-1.00],\n'
            '  "suggested_profit_target_cents": int,\n'
            '  "suggested_stop_loss_cents": int,\n'
            '  "reasoning": "2-4 sentences",\n'
            '  "warning_flags": ["LOW_CONFIDENCE"|"LOW_EDGE"|"COUNTER_TREND"|"HIGH_SPREAD"|"NEAR_CLOSE"|"THIN_BOOK"|"POOR_RECENT_PERFORMANCE"|"AI_UNCERTAINTY"|"CONFLICTING_SIGNALS"]\n'
            "}\n\n"
            "Structured context:\n"
            f"{json.dumps(payload, default=str, indent=2)}"
        )
