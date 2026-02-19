"""
Korea Investment Securities (한국투자증권) API Authentication.

Handles:
- OAuth 2.0 access token issuance and renewal (24-hour expiry)
- WebSocket approval key issuance
- Hash key generation for order requests
- Automatic token refresh before expiry

Reference:
- REST: POST /oauth2/tokenP → access_token
- WS:   POST /oauth2/Approval → approval_key
- Hash: POST /uapi/hashkey → hashkey (request body hashing)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta

import aiohttp
import structlog

from config.settings import get_settings

logger = structlog.get_logger(__name__)

# Token refresh buffer: renew 1 hour before expiry
TOKEN_REFRESH_BUFFER_SECONDS = 3600

# Retry config for rate-limited token requests (KIS: 1 request per minute)
_TOKEN_MAX_RETRIES = 5
_TOKEN_RETRY_BASE_DELAY_SECONDS = 65  # slightly over 60s to ensure cooldown
_TOKEN_RETRY_BACKOFF_FACTOR = 1.5  # exponential backoff: 65 → 97 → 146 → 219 → 328


class KISAuth:
    """
    Manages KIS API authentication state.

    Usage:
        auth = KISAuth()
        await auth.initialize()

        # Use in requests:
        headers = auth.get_auth_headers(tr_id="JTTT1002U")
        ws_key = auth.approval_key
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._approval_key: str | None = None

    async def initialize(self) -> None:
        """
        Initialize authentication: obtain access token and WebSocket approval key.
        Call this once at bot startup.
        """
        await self.refresh_access_token()
        await self.refresh_approval_key()
        logger.info(
            "kis_auth_initialized",
            mode=self._settings.trading_mode.value,
            token_expires=datetime.fromtimestamp(self._token_expires_at).isoformat(),
        )

    @property
    def access_token(self) -> str:
        """Current access token. Raises if not initialized."""
        if not self._access_token:
            raise RuntimeError("KIS auth not initialized. Call initialize() first.")
        return self._access_token

    @property
    def approval_key(self) -> str:
        """WebSocket approval key. Raises if not initialized."""
        if not self._approval_key:
            raise RuntimeError("KIS auth not initialized. Call initialize() first.")
        return self._approval_key

    @property
    def is_token_expired(self) -> bool:
        """Check if the access token is expired or about to expire."""
        return time.time() >= (self._token_expires_at - TOKEN_REFRESH_BUFFER_SECONDS)

    async def ensure_token_valid(self) -> None:
        """Refresh token if expired or about to expire."""
        if self.is_token_expired:
            logger.info("kis_token_refreshing", reason="expired_or_near_expiry")
            await self.refresh_access_token()

    async def refresh_access_token(self) -> None:
        """
        Request a new OAuth access token from KIS API.

        POST /oauth2/tokenP
        Body: {grant_type, appkey, appsecret}
        Response: {access_token, token_type, expires_in, access_token_token_expired}

        한투 API는 토큰 발급을 1분당 1회로 제한(EGW00133).
        403 에러 시 65초 대기 후 재시도하며, 최대 3회까지 시도한다.
        """
        url = f"{self._settings.kis_rest_base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._settings.active_app_key,
            "appsecret": self._settings.active_app_secret,
        }

        last_error: Exception | None = None
        data: dict = {}

        for attempt in range(1, _TOKEN_MAX_RETRIES + 1):
            delay = _TOKEN_RETRY_BASE_DELAY_SECONDS * (
                _TOKEN_RETRY_BACKOFF_FACTOR ** (attempt - 1)
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=body) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            break

                        text = await resp.text()

                        if resp.status == 403 and "EGW00133" in text:
                            logger.warning(
                                "kis_token_rate_limited",
                                attempt=attempt,
                                max_retries=_TOKEN_MAX_RETRIES,
                                retry_delay=int(delay),
                            )
                            last_error = RuntimeError(
                                f"KIS token rate limited: {resp.status} {text}"
                            )
                            if attempt < _TOKEN_MAX_RETRIES:
                                await asyncio.sleep(delay)
                                continue
                            raise last_error

                        logger.error(
                            "kis_token_request_failed",
                            status=resp.status,
                            body=text,
                        )
                        raise RuntimeError(
                            f"KIS token request failed: {resp.status} {text}"
                        )

            except aiohttp.ClientError as exc:
                logger.error(
                    "kis_token_network_error",
                    attempt=attempt,
                    error=str(exc),
                )
                last_error = exc
                if attempt < _TOKEN_MAX_RETRIES:
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(
                    f"KIS token request network error after {_TOKEN_MAX_RETRIES} attempts"
                ) from exc
        else:
            raise last_error or RuntimeError("KIS token request failed after all retries")

        self._access_token = data["access_token"]

        # Parse expiry: KIS returns "access_token_token_expired" as ISO datetime string
        # e.g., "2026-02-15 14:28:27"
        expired_str = data.get("access_token_token_expired", "")
        if expired_str:
            try:
                expires_dt = datetime.strptime(expired_str, "%Y-%m-%d %H:%M:%S")
                self._token_expires_at = expires_dt.timestamp()
            except ValueError:
                # Fallback: assume 24 hours from now
                self._token_expires_at = time.time() + 86400
        else:
            # Fallback using expires_in (seconds)
            expires_in = data.get("expires_in", 86400)
            self._token_expires_at = time.time() + expires_in

        logger.info(
            "kis_token_obtained",
            expires_at=datetime.fromtimestamp(self._token_expires_at).isoformat(),
            token_prefix=self._access_token[:20] + "...",
        )

    async def refresh_approval_key(self) -> None:
        """
        Request a WebSocket approval key.

        POST /oauth2/Approval
        Body: {grant_type, appkey, secretkey}
        Response: {approval_key}

        토큰과 마찬가지로 rate limit 대비 재시도 로직 포함.
        """
        url = f"{self._settings.kis_rest_base_url}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._settings.active_app_key,
            "secretkey": self._settings.active_app_secret,
        }

        last_error: Exception | None = None

        for attempt in range(1, _TOKEN_MAX_RETRIES + 1):
            delay = _TOKEN_RETRY_BASE_DELAY_SECONDS * (
                _TOKEN_RETRY_BACKOFF_FACTOR ** (attempt - 1)
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=body) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self._approval_key = data["approval_key"]
                            logger.info("kis_approval_key_obtained")
                            return

                        text = await resp.text()

                        if resp.status == 403:
                            logger.warning(
                                "kis_approval_key_rate_limited",
                                attempt=attempt,
                                retry_delay=int(delay),
                            )
                            last_error = RuntimeError(
                                f"KIS approval key rate limited: {resp.status} {text}"
                            )
                            if attempt < _TOKEN_MAX_RETRIES:
                                await asyncio.sleep(delay)
                                continue
                            raise last_error

                        logger.error(
                            "kis_approval_key_failed",
                            status=resp.status,
                            body=text,
                        )
                        raise RuntimeError(
                            f"KIS approval key request failed: {resp.status} {text}"
                        )

            except aiohttp.ClientError as exc:
                logger.error(
                    "kis_approval_key_network_error",
                    attempt=attempt,
                    error=str(exc),
                )
                last_error = exc
                if attempt < _TOKEN_MAX_RETRIES:
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(
                    f"KIS approval key network error after {_TOKEN_MAX_RETRIES} attempts"
                ) from exc

        raise last_error or RuntimeError("KIS approval key failed after all retries")

    async def get_hashkey(self, body: dict) -> str:
        """
        Get hash key for an order request body.

        POST /uapi/hashkey
        Required for order submission to prevent tampering.

        Args:
            body: The order request body to hash

        Returns:
            The hash key string
        """
        url = f"{self._settings.kis_rest_base_url}/uapi/hashkey"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self._settings.active_app_key,
            "appsecret": self._settings.active_app_secret,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("kis_hashkey_failed", status=resp.status, body=text)
                    raise RuntimeError(f"KIS hashkey request failed: {resp.status} {text}")

                data = await resp.json()

        return data["HASH"]

    def get_auth_headers(self, tr_id: str) -> dict[str, str]:
        """
        Build standard authentication headers for KIS REST API requests.

        Args:
            tr_id: Transaction ID (e.g., "JTTT1002U" for overseas stock order)

        Returns:
            Headers dict ready to use with aiohttp
        """
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self._settings.active_app_key,
            "appsecret": self._settings.active_app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # Personal account
        }
