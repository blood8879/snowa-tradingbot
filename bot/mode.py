"""
Paper/Live trading mode management.

Provides:
- Mode querying (current mode, is_paper, is_live)
- Mode persistence in database
- Mode-dependent configuration resolution
- Safety checks before mode switching

The trading mode determines:
- Which KIS API credentials are used (paper vs live keys)
- Which REST base URL is used (paper vs live endpoint)
- Which WebSocket URL is used
- Initial capital amount
"""

from __future__ import annotations

import structlog

from config.settings import TradingMode, get_settings
from core.database import Database

logger = structlog.get_logger(__name__)


class ModeManager:
    """
    Manages Paper/Live mode state.

    The mode is primarily set via TRADING_MODE env var (in .env).
    The database stores the active mode for runtime queries and
    provides a safety gate for mode switches.

    Usage:
        mode = ModeManager(db)
        await mode.initialize()

        if mode.is_paper:
            ...  # paper trading logic

        # Switch mode (requires confirmation)
        await mode.switch_to(TradingMode.LIVE, confirm=True)
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._settings = get_settings()
        self._current_mode: TradingMode = self._settings.trading_mode

    async def initialize(self) -> None:
        """
        Initialize mode from settings and persist to database.
        On startup, the .env TRADING_MODE takes precedence.
        """
        # Persist current mode to DB
        await self._db.set_state("trading_mode", self._current_mode.value)

        logger.info(
            "mode_initialized",
            mode=self._current_mode.value,
            rest_url=self._settings.kis_rest_base_url,
            ws_url=self._settings.kis_ws_url,
        )

    @property
    def current_mode(self) -> TradingMode:
        return self._current_mode

    @property
    def is_paper(self) -> bool:
        return self._current_mode == TradingMode.PAPER

    @property
    def is_live(self) -> bool:
        return self._current_mode == TradingMode.LIVE

    @property
    def mode_label(self) -> str:
        """Human-readable mode label (for Telegram, logs, etc.)."""
        return "🟡 Paper" if self.is_paper else "🔴 LIVE"

    async def switch_to(self, target_mode: TradingMode, *, confirm: bool = False) -> bool:
        """
        Switch trading mode.

        Args:
            target_mode: The mode to switch to
            confirm: Safety flag — must be True to proceed

        Returns:
            True if switch was successful, False if rejected

        Safety:
        - Switching to LIVE requires confirm=True
        - Cannot switch while positions are open (checked by caller)
        - Mode change is persisted to database
        """
        if target_mode == self._current_mode:
            logger.info("mode_switch_noop", current=self._current_mode.value)
            return True

        if target_mode == TradingMode.LIVE and not confirm:
            logger.warning(
                "mode_switch_rejected",
                reason="switching to LIVE requires explicit confirmation",
                target=target_mode.value,
            )
            return False

        old_mode = self._current_mode
        self._current_mode = target_mode

        # Persist to database
        await self._db.set_state("trading_mode", target_mode.value)

        logger.warning(
            "mode_switched",
            from_mode=old_mode.value,
            to_mode=target_mode.value,
        )

        return True

    def get_mode_info(self) -> dict[str, str]:
        """Get mode details for status display."""
        return {
            "mode": self._current_mode.value,
            "label": self.mode_label,
            "capital": "N/A",  # 실제 잔고는 계좌 조회로 확인
            "rest_url": self._settings.kis_rest_base_url,
            "ws_url": self._settings.kis_ws_url,
            "account": self._settings.active_account_no,
        }
