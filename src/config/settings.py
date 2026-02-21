from __future__ import annotations

from functools import lru_cache
from decimal import Decimal
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.enums import AIFallbackMode, ExitMode, TradingMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "infinite_gains"
    postgres_user: str = "infinite_gains"
    postgres_password: SecretStr = Field(default=SecretStr("change-me"), repr=False)
    database_url: str = "postgresql+asyncpg://infinite_gains:change-me@postgres:5432/infinite_gains"

    poly_private_key: SecretStr = Field(default=SecretStr(""), repr=False)
    poly_funder_address: str = ""
    poly_chain_id: int = 137
    poly_clob_host: str = "https://clob.polymarket.com"
    poly_ws_host: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    poly_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    poly_api_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    poly_api_passphrase: SecretStr = Field(default=SecretStr(""), repr=False)

    taapi_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    taapi_exchange: str = "binance"
    taapi_symbol: str = "BTC/USDT"
    taapi_interval: str = "1h"
    taapi_backtrack: int = 1

    telegram_bot_token: SecretStr = Field(default=SecretStr(""), repr=False)
    telegram_allowed_chat_ids: tuple[int, ...] = ()
    telegram_admin_user_id: int = 0

    trading_mode: TradingMode = TradingMode.PAPER

    risk_max_trade_usdc: Decimal = Decimal("10.00")
    risk_max_daily_loss_usdc: Decimal = Decimal("15.00")
    risk_max_trades_per_day: int = 6
    risk_max_open_positions: int = 1
    risk_cooldown_seconds: int = 300

    strategy_rsi_period: int = 14
    strategy_rsi_oversold: Decimal = Decimal("30")
    strategy_rsi_overbought: Decimal = Decimal("70")
    strategy_stoch_k_period: int = 14
    strategy_stoch_d_period: int = 3
    strategy_stoch_k_smooth: int = 3
    strategy_stoch_oversold: Decimal = Decimal("20")
    strategy_stoch_overbought: Decimal = Decimal("80")

    market_max_spread: Decimal = Decimal("0.03")
    market_no_trade_before_close_secs: int = 120
    market_max_trades_per_candle: int = 1

    scheduler_poll_interval_secs: int = 60

    metrics_port: int = 8080
    web_api_host: str = "0.0.0.0"
    web_api_port: int = 8081
    grafana_admin_user: str = "admin"
    grafana_admin_password: SecretStr = Field(default=SecretStr("admin"), repr=False)

    minimax_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    minimax_model: str = "MiniMax-Text-01"
    minimax_enabled: bool = False
    minimax_api_base_url: str = "https://api.minimax.chat/v1"
    ai_fallback_mode: AIFallbackMode = AIFallbackMode.VETO
    ai_min_edge: Decimal = Decimal("0.05")
    ai_min_confidence: int = 55
    ai_max_latency_ms: int = 10000
    ai_candle_history_count: int = 12
    ai_max_consecutive_failures: int = 3

    exit_mode: ExitMode = ExitMode.SCALP
    exit_profit_target_cents: int = 10
    exit_stop_loss_cents: int = 5
    exit_time_before_close_secs: int = 600
    exit_on_signal_reversal: bool = True
    exit_min_profit_cents: int = 5
    exit_max_profit_cents: int = 20
    exit_min_stop_cents: int = 3
    exit_max_stop_cents: int = 15
    position_monitor_interval_secs: int = 30

    openclaw_enabled: bool = False
    openclaw_schedule_hours: int = 6
    openclaw_min_trades_for_analysis: int = 20
    analyst_ro_password: SecretStr = Field(default=SecretStr("analyst-change-me"), repr=False)

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, value: Any) -> tuple[int, ...]:
        if isinstance(value, tuple):
            return value
        if isinstance(value, list):
            return tuple(int(item) for item in value)
        if isinstance(value, str):
            raw = [item.strip() for item in value.split(",") if item.strip()]
            return tuple(int(item) for item in raw)
        if value in (None, ""):
            return ()
        raise ValueError("Invalid TELEGRAM_ALLOWED_CHAT_IDS format")

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    def snapshot_strategy(self) -> dict[str, str]:
        return {
            "rsi_period": str(self.strategy_rsi_period),
            "rsi_oversold": str(self.strategy_rsi_oversold),
            "rsi_overbought": str(self.strategy_rsi_overbought),
            "stoch_k_period": str(self.strategy_stoch_k_period),
            "stoch_d_period": str(self.strategy_stoch_d_period),
            "stoch_k_smooth": str(self.strategy_stoch_k_smooth),
            "stoch_oversold": str(self.strategy_stoch_oversold),
            "stoch_overbought": str(self.strategy_stoch_overbought),
        }

    def snapshot_risk(self) -> dict[str, str]:
        return {
            "max_trade_usdc": str(self.risk_max_trade_usdc),
            "max_daily_loss_usdc": str(self.risk_max_daily_loss_usdc),
            "max_trades_per_day": str(self.risk_max_trades_per_day),
            "max_open_positions": str(self.risk_max_open_positions),
            "cooldown_seconds": str(self.risk_cooldown_seconds),
        }

    def snapshot_ai(self) -> dict[str, str]:
        return {
            "minimax_enabled": str(self.minimax_enabled),
            "minimax_model": self.minimax_model,
            "ai_fallback_mode": self.ai_fallback_mode.value,
            "ai_min_edge": str(self.ai_min_edge),
            "ai_min_confidence": str(self.ai_min_confidence),
            "ai_max_latency_ms": str(self.ai_max_latency_ms),
            "ai_candle_history_count": str(self.ai_candle_history_count),
            "ai_max_consecutive_failures": str(self.ai_max_consecutive_failures),
        }

    def snapshot_exit(self) -> dict[str, str]:
        return {
            "exit_mode": self.exit_mode.value,
            "exit_profit_target_cents": str(self.exit_profit_target_cents),
            "exit_stop_loss_cents": str(self.exit_stop_loss_cents),
            "exit_time_before_close_secs": str(self.exit_time_before_close_secs),
            "exit_on_signal_reversal": str(self.exit_on_signal_reversal),
            "exit_min_profit_cents": str(self.exit_min_profit_cents),
            "exit_max_profit_cents": str(self.exit_max_profit_cents),
            "exit_min_stop_cents": str(self.exit_min_stop_cents),
            "exit_max_stop_cents": str(self.exit_max_stop_cents),
            "position_monitor_interval_secs": str(self.position_monitor_interval_secs),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
