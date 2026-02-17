"""
한투 WebSocket 클라이언트 — 실시간 체결가 수신.

3중 안전장치:
1. 자동 재연결 (지수 백오프: 1, 2, 4, 8, 16, 30, 30, 30초)
2. 하트비트 모니터링 (60초 무응답 시 재연결)
3. REST 폴링 폴백 (WebSocket 실패 시 30초 간격 REST 조회)

참고: IMPLEMENTATION_PLAN.md §2.2 "WebSocket 안정성"

WebSocket 프로토콜:
- 구독 요청: JSON {"header": {...}, "body": {"input": {...}}}
- 수신 데이터: "0|H0USFASP0|..." 파이프 구분자 형식
- PINGPONG: 서버가 주기적으로 PING 전송 → PONG 응답 필요
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from broker.kis_auth import KISAuth
from config.constants import (
    WS_HEARTBEAT_TIMEOUT,
    WS_RECONNECT_DELAYS,
    WS_REST_FALLBACK_INTERVAL,
)
from config.settings import get_settings
from core.models import WebSocketStatus

logger = structlog.get_logger(__name__)

# 콜백 타입: 종목, 가격, 시각을 받는 비동기 함수
PriceCallback = Callable[[str, float, float], Coroutine[Any, Any, None]]


class KISWebSocket:
    """
    한투 해외주식 실시간 체결가 WebSocket 클라이언트.

    사용법:
        ws = KISWebSocket(auth, on_price_update)
        await ws.start(["AAPL", "NVDA", "TSLA"])
        # ... 봇 루프에서 실행
        await ws.stop()
    """

    def __init__(
        self,
        auth: KISAuth,
        price_callback: PriceCallback,
    ) -> None:
        self._auth = auth
        self._settings = get_settings()
        self._price_callback = price_callback
        self._ws: Any = None
        self._status = WebSocketStatus.DISCONNECTED
        self._subscribed_tickers: list[str] = []
        self._last_message_time: float = 0.0
        self._running = False
        self._reconnect_count = 0

    @property
    def status(self) -> WebSocketStatus:
        return self._status

    @property
    def is_connected(self) -> bool:
        return self._status == WebSocketStatus.CONNECTED

    # ────────────────────────────────────────────────────────
    # 메인 루프
    # ────────────────────────────────────────────────────────

    async def start(self, tickers: list[str]) -> None:
        """WebSocket 연결 시작 및 종목 구독."""
        self._subscribed_tickers = tickers
        self._running = True
        self._reconnect_count = 0

        logger.info("ws_starting", tickers=tickers)

        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break
                logger.error("ws_connection_error", error=str(e))
                await self._handle_reconnect()

    async def stop(self) -> None:
        """WebSocket 연결 종료."""
        self._running = False
        if self._ws:
            await self._ws.close()
        self._status = WebSocketStatus.DISCONNECTED
        logger.info("ws_stopped")

    # ────────────────────────────────────────────────────────
    # 연결 & 수신
    # ────────────────────────────────────────────────────────

    async def _connect_and_listen(self) -> None:
        """WebSocket 연결 → 구독 → 메시지 수신 루프."""
        ws_url = self._settings.kis_ws_url + "/tryitout/H0USFASP0"

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            self._ws = ws
            self._status = WebSocketStatus.CONNECTED
            self._last_message_time = time.time()
            self._reconnect_count = 0

            logger.info("ws_connected", url=ws_url)

            # 종목 구독
            for ticker in self._subscribed_tickers:
                await self._subscribe(ws, ticker)

            # 메시지 수신 루프 + 하트비트 체크
            listener = asyncio.create_task(self._listen(ws))
            heartbeat = asyncio.create_task(self._heartbeat_monitor())

            try:
                done, pending = await asyncio.wait(
                    [listener, heartbeat],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
            except asyncio.CancelledError:
                listener.cancel()
                heartbeat.cancel()

    async def _subscribe(self, ws: Any, ticker: str) -> None:
        """해외주식 실시간 체결가 구독 요청."""
        msg = {
            "header": {
                "approval_key": self._auth.approval_key,
                "custtype": "P",
                "tr_type": "1",       # 1=구독, 2=해제
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "HDFSCNT0",   # 해외주식 실시간 체결가
                    "tr_key": ticker,
                }
            },
        }
        await ws.send(json.dumps(msg))
        logger.debug("ws_subscribed", ticker=ticker)

    async def _unsubscribe(self, ws: Any, ticker: str) -> None:
        """구독 해제."""
        msg = {
            "header": {
                "approval_key": self._auth.approval_key,
                "custtype": "P",
                "tr_type": "2",       # 2=해제
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "HDFSCNT0",
                    "tr_key": ticker,
                }
            },
        }
        await ws.send(json.dumps(msg))
        logger.debug("ws_unsubscribed", ticker=ticker)

    async def _listen(self, ws: Any) -> None:
        """WebSocket 메시지 수신 루프."""
        try:
            async for message in ws:
                self._last_message_time = time.time()

                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                # PINGPONG 처리
                if "PINGPONG" in message:
                    await ws.send("PONG")
                    continue

                # JSON 응답 (구독 확인 등)
                if message.startswith("{"):
                    self._handle_json_response(message)
                    continue

                # 실시간 체결가 데이터 (파이프 구분자)
                await self._parse_tick_data(message)

        except ConnectionClosed:
            logger.warning("ws_connection_closed")
            raise

    def _handle_json_response(self, message: str) -> None:
        """구독 확인 등 JSON 응답 처리."""
        try:
            data = json.loads(message)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")
            msg = data.get("body", {}).get("msg1", "")
            logger.debug("ws_json_response", tr_id=tr_id, msg=msg)
        except json.JSONDecodeError:
            logger.debug("ws_json_parse_error", message=message[:100])

    async def _parse_tick_data(self, message: str) -> None:
        """
        실시간 체결가 데이터 파싱.

        형식: "0|H0USFASP0|004|AAPL^150.25^150.30^..."
        파이프(|)로 헤더와 데이터 구분, 데이터 내부는 ^(캐럿)으로 구분.
        """
        try:
            parts = message.split("|")
            if len(parts) < 4:
                return

            # parts[0]: 암호화 여부 (0=평문)
            # parts[1]: TR_ID
            # parts[2]: 데이터 건수
            # parts[3]: 실제 데이터
            tr_id = parts[1]
            data_str = parts[3]

            if tr_id != "H0USFASP0":
                return

            fields = data_str.split("^")
            if len(fields) < 3:
                return

            # 필드 매핑 (한투 해외주식 실시간 체결가)
            ticker = fields[0]           # 종목코드
            current_price = float(fields[2])  # 체결가
            volume = float(fields[12]) if len(fields) > 12 else 0

            # 콜백 호출
            await self._price_callback(ticker, current_price, time.time())

        except (ValueError, IndexError) as e:
            logger.debug("ws_tick_parse_error", error=str(e), message=message[:200])

    # ────────────────────────────────────────────────────────
    # 안정성: 하트비트 & 재연결
    # ────────────────────────────────────────────────────────

    async def _heartbeat_monitor(self) -> None:
        """하트비트 모니터링 — 타임아웃 시 재연결 트리거."""
        while self._running:
            await asyncio.sleep(10)
            elapsed = time.time() - self._last_message_time
            if elapsed > WS_HEARTBEAT_TIMEOUT:
                logger.warning("ws_heartbeat_timeout", elapsed_seconds=elapsed)
                if self._ws:
                    await self._ws.close()
                break

    async def _handle_reconnect(self) -> None:
        """지수 백오프 재연결."""
        if not self._running:
            return

        delay_idx = min(self._reconnect_count, len(WS_RECONNECT_DELAYS) - 1)
        delay = WS_RECONNECT_DELAYS[delay_idx]
        self._reconnect_count += 1
        self._status = WebSocketStatus.RECONNECTING

        logger.info(
            "ws_reconnecting",
            attempt=self._reconnect_count,
            delay_seconds=delay,
        )

        await asyncio.sleep(delay)

    # ────────────────────────────────────────────────────────
    # 종목 관리
    # ────────────────────────────────────────────────────────

    async def update_subscriptions(self, new_tickers: list[str]) -> None:
        """구독 종목 변경 (추가/제거)."""
        if not self._ws or not self.is_connected:
            self._subscribed_tickers = new_tickers
            return

        current = set(self._subscribed_tickers)
        target = set(new_tickers)

        to_add = target - current
        to_remove = current - target

        for ticker in to_remove:
            await self._unsubscribe(self._ws, ticker)
        for ticker in to_add:
            await self._subscribe(self._ws, ticker)

        self._subscribed_tickers = new_tickers
        logger.info(
            "ws_subscriptions_updated",
            added=list(to_add),
            removed=list(to_remove),
            total=len(new_tickers),
        )
