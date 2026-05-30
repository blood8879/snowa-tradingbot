"""
Application settings loaded from environment variables (.env file).

Uses pydantic-settings for type-safe configuration with validation.
All settings are centralized here — no magic strings elsewhere in the codebase.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """Trading mode: paper (모의투자) or live (실전)."""

    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """
    Central configuration for the trading bot.

    Loads values from .env file, with sensible defaults where appropriate.
    Sensitive values (API keys) have no defaults and MUST be provided.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Trading Mode ─────────────────────────────────────────
    trading_mode: TradingMode = TradingMode.PAPER

    # ── KIS API — Live ───────────────────────────────────────
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""  # format: "12345678-01"

    # ── KIS API — Paper ──────────────────────────────────────
    kis_paper_app_key: str = ""
    kis_paper_app_secret: str = ""
    kis_paper_account_no: str = ""

    # ── Telegram ─────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── AI Stock Reports ─────────────────────────────────────
    ai_report_provider: str = "openai"  # openai, anthropic, or disabled
    ai_report_model: str = "gpt-4.1-mini"
    ai_report_prompt_version: str = "canslim_ko_v4"
    ai_report_auto_generate: bool = True
    ai_report_trade_gate_enabled: bool = True
    ai_report_filter_watchlist_to_pass: bool = True
    ai_report_monthly_budget_usd: float = 0.0
    ai_report_min_remaining_usd: float = 0.0
    openai_api_key: str = ""
    openai_admin_api_key: str = ""
    anthropic_api_key: str = ""

    # ── Screening Data Refresh ───────────────────────────────
    screening_max_stale_fundamental_targets: int = 500
    screening_max_kr_dart_prefetch_targets: int = 150

    # ── Database ─────────────────────────────────────────────
    db_path: str = "data/snowa.db"

    # ── Logging ──────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/snowa_bot.log"

    # ── Derived Properties ───────────────────────────────────

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TradingMode.PAPER

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    @property
    def active_app_key(self) -> str:
        """Return the API key for the current trading mode."""
        return self.kis_paper_app_key if self.is_paper else self.kis_app_key

    @property
    def active_app_secret(self) -> str:
        """Return the API secret for the current trading mode."""
        return self.kis_paper_app_secret if self.is_paper else self.kis_app_secret

    @property
    def active_account_no(self) -> str:
        """Return the account number for the current trading mode."""
        return self.kis_paper_account_no if self.is_paper else self.kis_account_no

    @property
    def account_number(self) -> str:
        """Account number part (8 digits before hyphen)."""
        return self.active_account_no.split("-")[0] if "-" in self.active_account_no else self.active_account_no

    @property
    def account_product_code(self) -> str:
        """Product code part (2 digits after hyphen)."""
        parts = self.active_account_no.split("-")
        return parts[1] if len(parts) > 1 else "01"

    @property
    def kis_rest_base_url(self) -> str:
        """REST API base URL for the current trading mode."""
        if self.is_paper:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"

    @property
    def kis_ws_url(self) -> str:
        """WebSocket URL for the current trading mode."""
        if self.is_paper:
            return "ws://ops.koreainvestment.com:31000"
        return "ws://ops.koreainvestment.com:21000"

    @property
    def db_full_path(self) -> Path:
        """Resolved absolute path for the SQLite database."""
        return Path(self.db_path).resolve()

    @property
    def log_full_path(self) -> Path:
        """Resolved absolute path for the log file."""
        return Path(self.log_file).resolve()


# Singleton instance — import this throughout the app
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from .env (useful for testing)."""
    global _settings
    _settings = Settings()
    return _settings
