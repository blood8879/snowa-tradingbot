"""
한투 WebSocket 클라이언트 — 실시간 체결가 수신.

3중 안전장치:
1. 자동 재연결 (지수 백오프: 1, 2, 4, 8, 16, 30, 30, 30초)
2. 하트비트 모니터링 (60초 무응답 시 재연결)
3. REST 폴링 폴백 (WebSocket 실패 시 30초 간격 REST 조회)

참고: IMPLEMENTATION_PLAN.md §2.2 "WebSocket 안정성"

WebSocket 프로토콜:
- 구독 요청: JSON {"header": {...}, "body": {"input": {...}}}
- 수신 데이터: "0|HDFSCNT0|..." 파이프 구분자 형식
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

# REST API 거래소 코드 → WS tr_key 거래소 코드 매핑
_EXCHANGE_TO_WS: dict[str, str] = {
    "NASD": "NAS",
    "NYSE": "NYS",
    "AMEX": "AMS",
    "NAS": "NAS",
    "NYS": "NYS",
    "AMS": "AMS",
}


class KISWebSocket:
    """
    한투 해외주식 실시간 체결가 WebSocket 클라이언트.

    사용법:
        ws = KISWebSocket(auth, on_price_update)
        await ws.start({"AAPL": "NASD", "CVE": "NYSE"})
        # ... 봇 루프에서 실행
        await ws.stop()
    """

    def __init__(
        self,
        auth: KISAuth,
        price_callback: PriceCallback,
        rest_client: Any = None,
    ) -> None:
        self._auth = auth
        self._settings = get_settings()
        self._price_callback = price_callback
        self._rest_client = rest_client
        self._ws: Any = None
        self._status = WebSocketStatus.DISCONNECTED
        self._subscribed_tickers: list[str] = []
        self._ticker_exchange: dict[str, str] = {}
        self._last_message_time: float = 0.0
        self._running = False
        self._reconnect_count = 0
        self._first_tick_logged = False
        self._rest_fallback_active = False
        self._approval_invalid = False  # "invalid approval" 에러 감지 플래그

    @property
    def status(self) -> WebSocketStatus:
        return self._status

    @property
    def is_connected(self) -> bool:
        return self._status == WebSocketStatus.CONNECTED

    # ────────────────────────────────────────────────────────
    # 메인 루프
    # ────────────────────────────────────────────────────────

    async def start(self, ticker_exchanges: dict[str, str]) -> None:
        """WebSocket 연결 시작 및 종목 구독."""
        self._ticker_exchange = ticker_exchanges
        self._subscribed_tickers = list(ticker_exchanges.keys())
        self._running = True
        self._reconnect_count = 0
        self._first_tick_logged = False
        self._rest_fallback_active = False

        logger.info("ws_starting", tickers=self._subscribed_tickers)

        rest_fallback_task: asyncio.Task | None = None

        while self._running:
            try:
                # "invalid approval" 감지 시 approval key 갱신
                if self._approval_invalid:
                    logger.info("ws_refreshing_approval_key")
                    try:
                        await self._auth.refresh_approval_key()
                        self._approval_invalid = False
                        logger.info("ws_approval_key_refreshed")
                    except Exception as e:
                        logger.error("ws_approval_key_refresh_failed", error=str(e))

                # WS 연결 성공 → REST 폴백 중지
                if rest_fallback_task and not rest_fallback_task.done():
                    rest_fallback_task.cancel()
                    self._rest_fallback_active = False
                    logger.info("ws_rest_fallback_stopped", reason="ws_reconnected")

                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break
                logger.error("ws_connection_error", error=str(e))

            # 항상 reconnect 처리 (정상 종료 / 예외 모두)
            if not self._running:
                break

            # 3회 연속 실패 시 REST 폴백 시작
            if (
                self._rest_client
                and self._reconnect_count >= 3
                and not self._rest_fallback_active
            ):
                rest_fallback_task = asyncio.create_task(
                    self._rest_fallback_polling()
                )

            await self._handle_reconnect()

        # 종료 시 폴백 정리
        if rest_fallback_task and not rest_fallback_task.done():
            rest_fallback_task.cancel()

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
        ws_url = self._settings.kis_ws_url + "/tryitout"

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            self._ws = ws
            self._status = WebSocketStatus.CONNECTED
            self._last_message_time = time.time()
            # NOTE: _reconnect_count는 여기서 리셋하지 않음.
            # 실제 틱 데이터 수신 시(_parse_tick_data)에서만 리셋.
            # KIS "ALREADY IN USE appkey" 즉시 킥 시 백오프가 작동하도록.

            logger.info("ws_connected", url=ws_url, reconnect_count=self._reconnect_count)

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
                # done 태스크의 exception 회수 → "Task exception was never retrieved" 경고 방지
                for task in done:
                    try:
                        task.result()
                    except Exception:
                        pass  # 재연결 로직에서 처리
            except asyncio.CancelledError:
                listener.cancel()
                heartbeat.cancel()

    def _build_tr_key(self, ticker: str) -> str:
        exchange = self._ticker_exchange.get(ticker, "NASD")
        ws_exchange = _EXCHANGE_TO_WS.get(exchange, "NAS")
        return f"D{ws_exchange}{ticker}"

    async def _subscribe(self, ws: Any, ticker: str) -> None:
        tr_key = self._build_tr_key(ticker)
        msg = {
            "header": {
                "approval_key": self._auth.approval_key,
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "HDFSCNT0",
                    "tr_key": tr_key,
                }
            },
        }
        await ws.send(json.dumps(msg))
        logger.info("ws_subscribed", ticker=ticker, tr_key=tr_key)

    async def _unsubscribe(self, ws: Any, ticker: str) -> None:
        tr_key = self._build_tr_key(ticker)
        msg = {
            "header": {
                "approval_key": self._auth.approval_key,
                "custtype": "P",
                "tr_type": "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "HDFSCNT0",
                    "tr_key": tr_key,
                }
            },
        }
        await ws.send(json.dumps(msg))
        logger.debug("ws_unsubscribed", ticker=ticker, tr_key=tr_key)

    async def _listen(self, ws: Any) -> None:
        try:
            async for message in ws:
                self._last_message_time = time.time()

                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                if "PINGPONG" in message:
                    await ws.send(message)
                    continue

                if message.startswith("{"):
                    self._handle_json_response(message)
                    continue

                await self._parse_tick_data(message)

        except ConnectionClosed:
            logger.warning("ws_connection_closed")
            raise

    def _handle_json_response(self, message: str) -> None:
        try:
            data = json.loads(message)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")
            tr_key = header.get("tr_key", "")
            body = data.get("body", {})
            rt_cd = body.get("rt_cd", "")
            msg = body.get("msg1", "")
            # "invalid approval" 에러 감지 → 재연결 시 approval key 갱신
            if rt_cd == "1" and "invalid approval" in msg.lower():
                self._approval_invalid = True
                logger.warning(
                    "ws_approval_invalid_detected",
                    tr_key=tr_key,
                    msg=msg,
                )
            else:
                logger.info(
                    "ws_json_response",
                    tr_id=tr_id,
                    tr_key=tr_key,
                    rt_cd=rt_cd,
                    msg=msg,
                )
        except json.JSONDecodeError:
            logger.warning("ws_json_parse_error", message=message[:200])

    async def _parse_tick_data(self, message: str) -> None:
        """HDFSCNT0 필드 (KIS 공식 스펙):
        RSYM(0) SYMB(1) ZDIV(2) TYMD(3) XYMD(4) XHMS(5) KYMD(6) KHMS(7)
        OPEN(8) HIGH(9) LOW(10) LAST(11) SIGN(12) DIFF(13) RATE(14)
        PBID(15) PASK(16) VBID(17) VASK(18) EVOL(19) TVOL(20) TAMT(21)
        BIVL(22) ASVL(23) STRN(24) MTYP(25)

        주의: fields[0]은 RSYM(실시간종목코드, 예: "DNASAAPL")이고,
              fields[1]이 SYMB(종목코드, 예: "AAPL")이다.
        """
        try:
            parts = message.split("|")
            if len(parts) < 4:
                return

            tr_id = parts[1]
            data_str = parts[3]

            if tr_id != "HDFSCNT0":
                return

            fields = data_str.split("^")
            if len(fields) < 12:
                return

            # fields[0] = RSYM ("DNASAAPL"), fields[1] = SYMB ("AAPL")
            rsym = fields[0]
            ticker = fields[1]
            current_price = float(fields[11])

            # 안전장치: SYMB이 비어있으면 RSYM에서 추출
            if not ticker and rsym:
                # RSYM 형식: "D" + exchange(3) + ticker → 4번째 문자부터 추출
                ticker = rsym[4:] if len(rsym) > 4 else rsym

            # 실제 틱 수신 확인 → 재연결 카운터 리셋 (백오프 초기화)
            if self._reconnect_count > 0:
                logger.info("ws_reconnect_count_reset", was=self._reconnect_count)
                self._reconnect_count = 0

            if not self._first_tick_logged:
                self._first_tick_logged = True
                logger.info(
                    "ws_first_tick_received",
                    rsym=rsym,
                    ticker=ticker,
                    price=current_price,
                    field_count=len(fields),
                    raw_preview=message[:200],
                )

            await self._price_callback(ticker, current_price, time.time())

        except (ValueError, IndexError) as e:
            logger.warning("ws_tick_parse_error", error=str(e), message=message[:200])

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

    async def _rest_fallback_polling(self) -> None:
        """REST API 폴링 폴백 — WebSocket 장애 시 30초 간격 현재가 조회."""
        self._rest_fallback_active = True
        logger.warning(
            "ws_rest_fallback_started",
            interval=WS_REST_FALLBACK_INTERVAL,
            ticker_count=len(self._subscribed_tickers),
        )

        try:
            while self._running and not self.is_connected:
                for ticker in self._subscribed_tickers:
                    if self.is_connected:
                        break
                    try:
                        exchange = self._ticker_exchange.get(ticker, "NASD")
                        price_data = await self._rest_client.get_current_price(
                            ticker, exchange
                        )
                        current_price = float(price_data.get("last", 0) or price_data.get("stck_prpr", 0) or 0)
                        if current_price > 0:
                            await self._price_callback(
                                ticker, current_price, time.time()
                            )
                    except Exception:
                        logger.debug(
                            "rest_fallback_tick_failed",
                            ticker=ticker,
                            exc_info=True,
                        )
                await asyncio.sleep(WS_REST_FALLBACK_INTERVAL)
        except asyncio.CancelledError:
            pass
        finally:
            self._rest_fallback_active = False
            logger.info("ws_rest_fallback_ended")

    # ────────────────────────────────────────────────────────
    # 종목 관리
    # ────────────────────────────────────────────────────────

    async def update_subscriptions(self, new_ticker_exchanges: dict[str, str]) -> None:
        if not self._ws or not self.is_connected:
            self._ticker_exchange = new_ticker_exchanges
            self._subscribed_tickers = list(new_ticker_exchanges.keys())
            return

        current = set(self._subscribed_tickers)
        target = set(new_ticker_exchanges.keys())

        to_add = target - current
        to_remove = current - target

        for ticker in to_remove:
            await self._unsubscribe(self._ws, ticker)

        self._ticker_exchange.update(new_ticker_exchanges)

        for ticker in to_add:
            await self._subscribe(self._ws, ticker)

        self._subscribed_tickers = list(new_ticker_exchanges.keys())
        logger.info(
            "ws_subscriptions_updated",
            added=list(to_add),
            removed=list(to_remove),
            total=len(new_ticker_exchanges),
        )
