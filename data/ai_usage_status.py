"""LLM provider usage and budget status.

OpenAI exposes official organization usage/cost endpoints, not a simple
"remaining credit" endpoint. This module reports current-month spend against
locally configured budget thresholds so the trading gate can fail visibly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp
import structlog

from config.settings import Settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AIUsageStatus:
    provider: str
    model: str
    configured: bool
    usage_supported: bool
    available: bool
    status: str
    message: str
    current_month_cost_usd: float | None = None
    monthly_budget_usd: float | None = None
    remaining_budget_usd: float | None = None
    min_remaining_usd: float | None = None
    checked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "usage_supported": self.usage_supported,
            "available": self.available,
            "status": self.status,
            "message": self.message,
            "current_month_cost_usd": self.current_month_cost_usd,
            "monthly_budget_usd": self.monthly_budget_usd,
            "remaining_budget_usd": self.remaining_budget_usd,
            "min_remaining_usd": self.min_remaining_usd,
            "checked_at": self.checked_at,
        }


class AIUsageStatusService:
    """Fetch provider usage and evaluate configured budget thresholds."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_status(self) -> AIUsageStatus:
        provider = self._settings.ai_report_provider.lower()
        checked_at = datetime.now(UTC).isoformat()

        if provider == "disabled":
            return AIUsageStatus(
                provider=provider,
                model=self._settings.ai_report_model,
                configured=False,
                usage_supported=False,
                available=False,
                status="disabled",
                message="AI 리포트 provider가 비활성화되어 있습니다.",
                checked_at=checked_at,
            )
        if provider == "openai":
            return await self._get_openai_status(checked_at)
        if provider == "anthropic":
            return self._get_anthropic_status(checked_at)

        return AIUsageStatus(
            provider=provider,
            model=self._settings.ai_report_model,
            configured=False,
            usage_supported=False,
            available=False,
            status="error",
            message=f"지원하지 않는 AI 리포트 provider입니다: {provider}",
            checked_at=checked_at,
        )

    async def _get_openai_status(self, checked_at: str) -> AIUsageStatus:
        api_key = self._settings.openai_admin_api_key or self._settings.openai_api_key
        if not api_key:
            return AIUsageStatus(
                provider="openai",
                model=self._settings.ai_report_model,
                configured=False,
                usage_supported=True,
                available=False,
                status="missing_key",
                message="OPENAI_API_KEY 또는 OPENAI_ADMIN_API_KEY가 설정되어 있지 않습니다.",
                checked_at=checked_at,
            )

        budget = self._settings.ai_report_monthly_budget_usd
        min_remaining = self._settings.ai_report_min_remaining_usd
        cost = await self._fetch_openai_month_cost(api_key)
        remaining = (budget - cost) if budget > 0 else None

        if budget > 0 and remaining is not None and remaining < min_remaining:
            return AIUsageStatus(
                provider="openai",
                model=self._settings.ai_report_model,
                configured=True,
                usage_supported=True,
                available=False,
                status="budget_low",
                message="AI 리포트 예산 잔여분이 최소 기준보다 낮습니다.",
                current_month_cost_usd=round(cost, 4),
                monthly_budget_usd=budget,
                remaining_budget_usd=round(remaining, 4),
                min_remaining_usd=min_remaining,
                checked_at=checked_at,
            )

        return AIUsageStatus(
            provider="openai",
            model=self._settings.ai_report_model,
            configured=True,
            usage_supported=True,
            available=True,
            status="ok",
            message="OpenAI 비용 조회가 정상입니다.",
            current_month_cost_usd=round(cost, 4),
            monthly_budget_usd=budget if budget > 0 else None,
            remaining_budget_usd=round(remaining, 4) if remaining is not None else None,
            min_remaining_usd=min_remaining if budget > 0 else None,
            checked_at=checked_at,
        )

    def _get_anthropic_status(self, checked_at: str) -> AIUsageStatus:
        configured = bool(self._settings.anthropic_api_key)
        return AIUsageStatus(
            provider="anthropic",
            model=self._settings.ai_report_model,
            configured=configured,
            usage_supported=False,
            available=configured,
            status="ok" if configured else "missing_key",
            message=(
                "Anthropic 키는 설정되어 있지만 이 앱은 잔액/비용 조회를 지원하지 않습니다."
                if configured
                else "ANTHROPIC_API_KEY가 설정되어 있지 않습니다."
            ),
            checked_at=checked_at,
        )

    async def _fetch_openai_month_cost(self, api_key: str) -> float:
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        params = {
            "start_time": str(int(start.timestamp())),
            "end_time": str(int(now.timestamp())),
            "bucket_width": "1d",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session,
            session.get(
                "https://api.openai.com/v1/organization/costs",
                headers=headers,
                params=params,
            ) as resp,
        ):
            body = await resp.text()
            if resp.status >= 400:
                logger.warning("openai_cost_status_failed", status=resp.status, body=body[:500])
                raise RuntimeError(f"OpenAI 비용 조회 실패: HTTP {resp.status}")
        data = json.loads(body)
        return _sum_openai_costs(data)


def _sum_openai_costs(data: dict[str, Any]) -> float:
    total = 0.0
    for bucket in data.get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount") or {}
            if str(amount.get("currency", "usd")).lower() == "usd":
                total += float(amount.get("value") or 0.0)
    return total


class CachedAIUsageStatusService:
    """Small TTL wrapper to avoid polling provider cost APIs every dashboard tick."""

    def __init__(self, settings: Settings, ttl_seconds: float = 300.0) -> None:
        self._service = AIUsageStatusService(settings)
        self._ttl_seconds = ttl_seconds
        self._cached: AIUsageStatus | None = None
        self._cached_at = 0.0

    async def get_status(self) -> AIUsageStatus:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached
        try:
            status = await self._service.get_status()
        except Exception as exc:
            status = AIUsageStatus(
                provider=self._service._settings.ai_report_provider.lower(),
                model=self._service._settings.ai_report_model,
                configured=bool(
                    self._service._settings.openai_api_key
                    or self._service._settings.openai_admin_api_key
                    or self._service._settings.anthropic_api_key
                ),
                usage_supported=self._service._settings.ai_report_provider.lower() == "openai",
                available=False,
                status="error",
                message=str(exc),
                checked_at=datetime.now(UTC).isoformat(),
            )
        self._cached = status
        self._cached_at = now
        return status
