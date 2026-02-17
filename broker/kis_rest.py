"""
Korea Investment Securities REST API Client.

해외주식 관련 REST API 호출을 담당하는 비동기 클라이언트.

기능:
- 현재가 조회
- 기간별 시세 (일봉 OHLCV)
- 주문 (매수/매도)
- 주문 정정/취소
- 미체결 조회
- 체결 내역 조회
- 잔고/보유종목 조회

참고:
- 해외주식은 지정가(LOO) 주문만 가능 (시장가/스톱 없음)
- TR_ID는 실전/모의투자에 따라 다름
- 모든 요청은 access_token 필요 (kis_auth.py에서 관리)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import aiohttp
import structlog

from broker.kis_auth import KISAuth
from config.settings import TradingMode, get_settings
from core.models import ExchangeCode, OHLCV

logger = structlog.get_logger(__name__)

# ============================================================
# TR_ID 매핑 (실전 / 모의투자)
# ============================================================

# 해외주식 현재가 상세
TR_PRICE_DETAIL = {"live": "HHDFS76200200", "paper": "HHDFS76200200"}

# 해외주식 기간별 시세 (일봉)
TR_DAILY_PRICE = {"live": "HHDFS76240000", "paper": "HHDFS76240000"}

# 해외주식 주문
TR_ORDER_BUY = {"live": "JTTT1002U", "paper": "VTTT1002U"}
TR_ORDER_SELL = {"live": "JTTT1006U", "paper": "VTTT1006U"}

# 해외주식 정정/취소
TR_ORDER_MODIFY = {"live": "JTTT1004U", "paper": "VTTT1004U"}

# 해외주식 미체결 내역
TR_UNFILLED = {"live": "TTTS3018R", "paper": "VTTS3018R"}

# 해외주식 잔고
TR_BALANCE = {"live": "TTTS3012R", "paper": "VTTS3012R"}

# 해외주식 체결 내역
TR_FILLED = {"live": "TTTS3035R", "paper": "VTTS3035R"}

# 해외주식 매수가능금액조회
TR_PSAMOUNT = {"live": "TTTS3007R", "paper": "VTTS3007R"}

# 거래소 코드 → 한투 API 거래소 코드
EXCHANGE_MAP: dict[str, str] = {
    "NASD": "NASD",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}

# 기본 리트라이 설정
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0


class KISRestClient:
    """
    한투 해외주식 REST API 비동기 클라이언트.

    사용법:
        client = KISRestClient(auth)
        price = await client.get_current_price("AAPL", "NASD")
        ohlcv_list = await client.get_daily_prices("AAPL", "NASD", days=300)
    """

    def __init__(self, auth: KISAuth) -> None:
        self._auth = auth
        self._settings = get_settings()
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션을 가져오거나 생성."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """HTTP 세션 종료."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_tr_id(self, tr_map: dict[str, str]) -> str:
        """현재 트레이딩 모드에 맞는 TR_ID 반환."""
        mode = "paper" if self._settings.is_paper else "live"
        return tr_map[mode]

    async def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        한투 API 공통 요청 메서드.

        자동 토큰 갱신 + 리트라이 + 에러 핸들링 포함.
        """
        await self._auth.ensure_token_valid()
        session = await self._ensure_session()

        url = f"{self._settings.kis_rest_base_url}{path}"
        headers = self._auth.get_auth_headers(tr_id)
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if method == "GET":
                    async with session.get(url, headers=headers, params=params) as resp:
                        data = await resp.json()
                else:
                    async with session.post(url, headers=headers, json=body) as resp:
                        data = await resp.json()

                # 한투 API 에러 체크
                rt_cd = data.get("rt_cd", "")
                if rt_cd != "0":
                    msg = data.get("msg1", "알 수 없는 오류")
                    msg_cd = data.get("msg_cd", "")
                    log_fn = logger.warning if attempt < MAX_RETRIES else logger.error
                    log_fn(
                        "kis_api_error",
                        path=path,
                        tr_id=tr_id,
                        rt_cd=rt_cd,
                        msg_cd=msg_cd,
                        msg=msg,
                        attempt=attempt,
                    )
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                        continue
                    raise KISAPIError(f"[{msg_cd}] {msg}", rt_cd=rt_cd, msg_cd=msg_cd)

                return data

            except aiohttp.ClientError as e:
                logger.error(
                    "kis_request_error",
                    path=path,
                    error=str(e),
                    attempt=attempt,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)
                    continue
                raise

        # 도달 불가능하지만 타입 안전을 위해
        raise RuntimeError("리트라이 횟수 초과")

    # ────────────────────────────────────────────────────────
    # 시세 조회
    # ────────────────────────────────────────────────────────

    async def get_current_price(self, ticker: str, exchange: str) -> dict[str, Any]:
        """
        해외주식 현재가 상세 조회.

        Args:
            ticker: 종목 코드 (예: "AAPL")
            exchange: 거래소 코드 (예: "NASD", "NYSE", "AMEX")

        Returns:
            현재가 정보 dict (stck_prpr: 현재가, stck_oprc: 시가, 등)
        """
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/price-detail",
            self._get_tr_id(TR_PRICE_DETAIL),
            params=params,
        )
        return data.get("output", {})

    async def get_daily_prices(
        self,
        ticker: str,
        exchange: str,
        period: str = "D",
        count: int = 100,
        end_date: str = "",
    ) -> list[OHLCV]:
        """
        해외주식 기간별 시세 (일봉 OHLCV) 조회.

        Args:
            ticker: 종목 코드
            exchange: 거래소 코드
            period: "D"=일봉, "W"=주봉, "M"=월봉
            count: 조회 건수 (최대 100)
            end_date: 조회 종료일 (YYYYMMDD, 공백이면 오늘)

        Returns:
            OHLCV 리스트 (최신 날짜부터)
        """
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
            "GUBN": "0",      # 0=일봉, 1=주봉, 2=월봉
            "BYMD": end_date,  # 공백이면 최신
            "MODP": "0",       # 0=수정주가 반영 안 함
        }
        if period == "W":
            params["GUBN"] = "1"
        elif period == "M":
            params["GUBN"] = "2"

        data = await self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/dailyprice",
            self._get_tr_id(TR_DAILY_PRICE),
            params=params,
        )

        output = data.get("output2", [])
        result: list[OHLCV] = []
        for item in output:
            # 빈 데이터 스킵
            if not item.get("xymd"):
                continue
            result.append(
                OHLCV(
                    date=self._format_date(item.get("xymd", "")),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("clos", 0)),
                    volume=int(float(item.get("tvol", 0))),
                )
            )
        return result

    async def get_daily_prices_bulk(
        self,
        ticker: str,
        exchange: str,
        days: int = 300,
    ) -> list[OHLCV]:
        """
        여러 번 호출해서 지정 일수만큼의 일봉 데이터를 수집.

        한투 API는 1회 최대 100건이므로 300일이면 3번 호출.
        """
        all_data: list[OHLCV] = []
        end_date = ""

        while len(all_data) < days:
            batch = await self.get_daily_prices(
                ticker, exchange, period="D", count=100, end_date=end_date
            )
            if not batch:
                break

            all_data.extend(batch)

            # 다음 배치: 현재 배치의 가장 오래된 날짜 전날
            oldest = batch[-1].date.replace("-", "")
            end_date = oldest

            # 중복 방지: 같은 날짜가 오면 중단
            if len(batch) < 2:
                break

            await asyncio.sleep(0.2)  # API 부하 방지

        # 날짜 순 정렬 (오래된 날짜 먼저)
        all_data.sort(key=lambda x: x.date)

        # 중복 제거
        seen: set[str] = set()
        unique: list[OHLCV] = []
        for bar in all_data:
            if bar.date not in seen:
                seen.add(bar.date)
                unique.append(bar)

        return unique[-days:] if len(unique) > days else unique

    # ────────────────────────────────────────────────────────
    # 주문
    # ────────────────────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        exchange: str,
        side: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        """
        해외주식 지정가 주문.

        Args:
            ticker: 종목 코드
            exchange: 거래소 코드
            side: "BUY" 또는 "SELL"
            quantity: 수량
            price: 지정가

        Returns:
            주문 응답 (ODNO: 주문번호 포함)
        """
        tr_map = TR_ORDER_BUY if side == "BUY" else TR_ORDER_SELL
        tr_id = self._get_tr_id(tr_map)

        # 주문 유형: 00=지정가
        body = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",  # 00=지정가
        }

        # hashkey 필요
        hashkey = await self._auth.get_hashkey(body)

        data = await self._request(
            "POST",
            "/uapi/overseas-stock/v1/trading/order",
            tr_id,
            body=body,
            extra_headers={"hashkey": hashkey},
        )

        output = data.get("output", {})
        order_no = output.get("ODNO", "")

        logger.info(
            "kis_order_placed",
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            order_no=order_no,
        )

        return output

    async def cancel_order(
        self,
        order_no: str,
        ticker: str,
        exchange: str,
        quantity: int,
    ) -> dict[str, Any]:
        """
        해외주식 주문 취소.

        Args:
            order_no: 원 주문 번호
            ticker: 종목 코드
            exchange: 거래소 코드
            quantity: 취소할 수량 (전량이면 원래 수량)
        """
        tr_id = self._get_tr_id(TR_ORDER_MODIFY)

        body = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": "0",
            "ORD_SVR_DVSN_CD": "0",
        }

        hashkey = await self._auth.get_hashkey(body)

        data = await self._request(
            "POST",
            "/uapi/overseas-stock/v1/trading/order-rvsecncl",
            tr_id,
            body=body,
            extra_headers={"hashkey": hashkey},
        )

        logger.info("kis_order_cancelled", order_no=order_no, ticker=ticker)
        return data.get("output", {})

    async def modify_order(
        self,
        order_no: str,
        ticker: str,
        exchange: str,
        quantity: int,
        new_price: float,
    ) -> dict[str, Any]:
        """
        해외주식 주문 정정 (가격 변경).

        Args:
            order_no: 원 주문 번호
            ticker: 종목 코드
            exchange: 거래소 코드
            quantity: 정정 수량
            new_price: 변경할 가격
        """
        tr_id = self._get_tr_id(TR_ORDER_MODIFY)

        body = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": "01",  # 01=정정
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{new_price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
        }

        hashkey = await self._auth.get_hashkey(body)

        data = await self._request(
            "POST",
            "/uapi/overseas-stock/v1/trading/order-rvsecncl",
            tr_id,
            body=body,
            extra_headers={"hashkey": hashkey},
        )

        logger.info(
            "kis_order_modified",
            order_no=order_no,
            ticker=ticker,
            new_price=new_price,
        )
        return data.get("output", {})

    # ────────────────────────────────────────────────────────
    # 조회
    # ────────────────────────────────────────────────────────

    async def get_unfilled_orders(self) -> list[dict[str, Any]]:
        """해외주식 미체결 주문 조회."""
        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": "NASD",  # 전체 조회 시에도 하나 지정 필요
            "SORT_SQN": "DS",        # 정렬순서: DS=최신순
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-stock/v1/trading/inquire-nccs",
            self._get_tr_id(TR_UNFILLED),
            params=params,
        )
        return data.get("output", [])

    async def get_filled_orders(
        self,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict[str, Any]]:
        """
        해외주식 체결 내역 조회.

        Args:
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
        """
        if not start_date:
            start_date = datetime.now().strftime("%Y%m%d")
        if not end_date:
            end_date = start_date

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "PDNO": "",               # 공백=전종목
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SLL_BUY_DVSN": "00",     # 00=전체
            "CCLD_NCCS_DVSN": "01",   # 01=체결만
            "OVRS_EXCG_CD": "NASD",
            "SORT_SQN": "DS",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-stock/v1/trading/inquire-ccnl",
            self._get_tr_id(TR_FILLED),
            params=params,
        )
        return data.get("output", [])

    async def get_balance(self) -> dict[str, Any]:
        """
        해외주식 잔고 조회.

        Returns:
            {
                "output1": {...},                      # 계좌 요약
                "output2": [{...}, {...}, ...],        # 보유 종목 리스트
            }
        """
        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-stock/v1/trading/inquire-balance",
            self._get_tr_id(TR_BALANCE),
            params=params,
        )
        # 한투 API 응답 형식 정규화:
        # - output1(요약): 보유 종목 있으면 dict, 없으면 빈 list
        # - output2(보유종목): 보유 있으면 list[dict], 없으면 단일 dict(합계행)
        raw_summary = data.get("output1", {})
        raw_positions = data.get("output2", [])

        # summary 정규화: list면 비어있다는 뜻 → 빈 dict
        if isinstance(raw_summary, list):
            summary = raw_summary[0] if raw_summary else {}
        else:
            summary = raw_summary

        # positions 정규화: dict면 보유 종목 없이 합계 행만 온 것 → 빈 list
        if isinstance(raw_positions, dict):
            positions: list[dict[str, Any]] = []
        elif isinstance(raw_positions, list):
            positions = raw_positions
        else:
            positions = []

        return {
            "summary": summary,
            "positions": positions,
        }

    async def get_purchasable_amount(
        self,
        ticker: str = "AAPL",
        exchange: str = "NASD",
        price: str = "100",
    ) -> dict[str, Any]:
        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "OVRS_ORD_UNPR": price,
            "ITEM_CD": ticker,
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-stock/v1/trading/inquire-psamount",
            self._get_tr_id(TR_PSAMOUNT),
            params=params,
        )
        return data.get("output", {})

    # ────────────────────────────────────────────────────────
    # 유틸리티
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _format_date(yyyymmdd: str) -> str:
        """YYYYMMDD → YYYY-MM-DD 변환."""
        if len(yyyymmdd) == 8:
            return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
        return yyyymmdd

    @staticmethod
    def detect_exchange(ticker: str) -> str:
        """
        종목 코드로 거래소 추정.

        실제 운영에서는 유니버스 DB에서 매핑하지만,
        폴백으로 사용할 수 있는 간단한 추정 로직.
        """
        # 일부 대형주 하드코딩 (나머지는 유니버스 DB에서 조회)
        nyse_known = {
            "BRK.A", "BRK.B", "JPM", "V", "JNJ", "WMT", "PG",
            "UNH", "HD", "BAC", "MA", "DIS", "KO", "PFE", "MRK",
        }
        if ticker in nyse_known:
            return "NYSE"
        # 기본값: NASDAQ (성장주 위주 전략이므로)
        return "NASD"


class KISAPIError(Exception):
    """한투 API 에러."""

    def __init__(self, message: str, rt_cd: str = "", msg_cd: str = "") -> None:
        super().__init__(message)
        self.rt_cd = rt_cd
        self.msg_cd = msg_cd
