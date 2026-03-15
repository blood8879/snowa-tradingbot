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
import time
from datetime import datetime
from typing import Any

import aiohttp
import structlog

from broker.kis_auth import KISAuth
from config.settings import TradingMode, get_settings
from config.market_config import KR_TICK_SIZE_TABLE, adjust_price_to_tick
from core.models import ExchangeCode, OHLCV

logger = structlog.get_logger(__name__)

# ============================================================
# TR_ID 매핑 (실전 / 모의투자)
# ============================================================

# 해외주식 현재가 상세
TR_PRICE_DETAIL = {"live": "HHDFS76200200", "paper": "HHDFS76200200"}

# 해외주식 현재가 (기본) — paper 모드에서 price-detail이 빈 응답 → 이 엔드포인트 사용
TR_PRICE = {"live": "HHDFS76200200", "paper": "HHDFS76200200"}

# 해외주식 기간별 시세 (일봉)
TR_DAILY_PRICE = {"live": "HHDFS76240000", "paper": "HHDFS76240000"}

# 해외주식 주문 (미국: TTTT 계열 — 야간/통합)
# KIS 공식: 미국 매수 TTTT1002U [모의투자] VTTT1002U
#           미국 매도 TTTT1006U [모의투자] VTTT1001U (비대칭 매핑 주의!)
TR_ORDER_BUY = {"live": "TTTT1002U", "paper": "VTTT1002U"}
TR_ORDER_SELL = {"live": "TTTT1006U", "paper": "VTTT1001U"}

# 해외주식 주간주문 (미국: TTTS6036U/6037U — daytime order)
# 해외주식 주간주문 (daytime order) — 90000000 에러 시 fallback용
TR_DAYTIME_ORDER_BUY = {"live": "TTTS6036U", "paper": "VTTS6036U"}
TR_DAYTIME_ORDER_SELL = {"live": "TTTS6037U", "paper": "VTTS6037U"}

# 해외주식 정정/취소 (미국: TTTT 계열)
TR_ORDER_MODIFY = {"live": "TTTT1004U", "paper": "VTTT1004U"}

# 해외주식 미체결 내역 (주간/야간)
TR_UNFILLED_DAY = {"live": "TTTS3018R", "paper": "VTTS3018R"}
TR_UNFILLED_NIGHT = {"live": "JTTT3018R", "paper": "VTTT3018R"}

# 해외주식 잔고 (주간/야간)
TR_BALANCE_DAY = {"live": "TTTS3012R", "paper": "VTTS3012R"}
TR_BALANCE_NIGHT = {"live": "JTTT3012R", "paper": "VTTT3012R"}

# 해외주식 체결 내역 (주간/야간)
TR_FILLED_DAY = {"live": "TTTS3035R", "paper": "VTTS3035R"}
TR_FILLED_NIGHT = {"live": "JTTT3035R", "paper": "VTTT3035R"}

# 해외주식 매수가능금액조회 (주간/야간)
TR_PSAMOUNT_DAY = {"live": "TTTS3007R", "paper": "VTTS3007R"}
TR_PSAMOUNT_NIGHT = {"live": "JTTT3007R", "paper": "VTTT3007R"}

# 해외주식 주야간원장구분 조회
TR_DAYORNIGHT = {"live": "JTTT3010R", "paper": "VTTT3010R"}

# 주야간 캐시 TTL (초)
_DAYORNIGHT_CACHE_TTL = 300  # 5분

# 거래소 코드 → 한투 API 거래소 코드
EXCHANGE_MAP: dict[str, str] = {
    "NASD": "NASD",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}

# 거래소 코드 → REST /quotations/price 엔드포인트용 단축 코드
# price-detail은 NASD/NYSE/AMEX, price(기본)는 NAS/NYS/AMS 사용
EXCHANGE_SHORT_MAP: dict[str, str] = {
    "NASD": "NAS",
    "NYSE": "NYS",
    "AMEX": "AMS",
    "NAS": "NAS",
    "NYS": "NYS",
    "AMS": "AMS",
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
        self._dayornight_cache: str | None = None
        self._dayornight_cache_ts: float = 0.0

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션을 가져오거나 생성."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30, connect=10)
            )
        return self._session

    async def close(self) -> None:
        """HTTP 세션 종료."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_tr_id(self, tr_map: dict[str, str]) -> str:
        """현재 트레이딩 모드에 맞는 TR_ID 반환."""
        mode = "paper" if self._settings.is_paper else "live"
        return tr_map[mode]

    def _estimate_day_or_night_by_time(self) -> str:
        """시간 기반 주야간 판단 (API 폴백용).

        US 정규장: ET 09:30–16:00 → KIS 야간(night)
        그 외 시간 → KIS 주간(day)
        """
        from zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
        hour, minute = now_et.hour, now_et.minute
        # US 정규장 09:30 ~ 16:00 = 야간
        if (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16:
            return "night"
        return "day"

    async def _check_day_or_night(self) -> str:
        """주야간원장구분 조회 (5분 캐시).

        KIS API ``/uapi/overseas-stock/v1/trading/dayornight`` 호출.
        ``output.PSBL_YN`` — 'Y'=야간(미국장 오픈), 'N'=주간(미국장 마감).

        모의투자는 주야간 API가 없으므로 시간 기반 판단으로 폴백.
        API 실패 시에도 시간 기반으로 판단 (야간 하드코딩 제거).

        Returns:
            ``"night"`` 또는 ``"day"``
        """
        now = time.monotonic()
        if (
            self._dayornight_cache is not None
            and (now - self._dayornight_cache_ts) < _DAYORNIGHT_CACHE_TTL
        ):
            return self._dayornight_cache

        # 모의투자: dayornight API 자체가 없으므로 시간 기반 판단
        if self._settings.is_paper:
            result = self._estimate_day_or_night_by_time()
            self._dayornight_cache = result
            self._dayornight_cache_ts = now
            logger.debug("dayornight_paper_time_based", result=result)
            return result

        try:
            await self._auth.ensure_token_valid()
            session = await self._ensure_session()

            tr_id = self._get_tr_id(TR_DAYORNIGHT)
            url = f"{self._settings.kis_rest_base_url}/uapi/overseas-stock/v1/trading/dayornight"
            headers = self._auth.get_auth_headers(tr_id)
            params = {
                "CANO": self._settings.account_number,
                "ACNT_PRDT_CD": self._settings.account_product_code,
            }

            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()

            rt_cd = data.get("rt_cd", "")
            if rt_cd != "0":
                logger.warning(
                    "dayornight_api_error",
                    rt_cd=rt_cd,
                    msg=data.get("msg1", ""),
                )
                result = self._estimate_day_or_night_by_time()
                self._dayornight_cache = result
                self._dayornight_cache_ts = now
                return result

            psbl_yn = data.get("output", {}).get("PSBL_YN", "Y")
            result = "night" if psbl_yn == "Y" else "day"

            self._dayornight_cache = result
            self._dayornight_cache_ts = now

            logger.debug("dayornight_checked", result=result, psbl_yn=psbl_yn)
            return result

        except Exception as e:
            logger.warning("dayornight_api_failed", error=str(e))
            result = self._estimate_day_or_night_by_time()
            self._dayornight_cache = result
            self._dayornight_cache_ts = now
            return result

    async def _get_overseas_tr_id(
        self,
        day_map: dict[str, str],
        night_map: dict[str, str],
    ) -> str:
        """주야간 세션에 따라 올바른 해외주식 조회 TR_ID 반환.

        모의투자(paper)는 야간 전용 TR_ID가 없으므로 항상 주간 TR 사용.
        """
        if self._settings.is_paper:
            return self._get_tr_id(day_map)
        session_type = await self._check_day_or_night()
        tr_map = night_map if session_type == "night" else day_map
        return self._get_tr_id(tr_map)

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
                        full_response=data if "order" in path else None,
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
    # 한국 국내주식 API (private methods)
    # ────────────────────────────────────────────────────────

    async def _kr_get_current_price(self, ticker: str, exchange: str) -> dict[str, Any]:
        """한국 국내주식 현재가 조회."""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        }
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",  # 실전/모의 동일
            params=params,
        )
        return data.get("output", {})

    async def _kr_get_daily_prices(
        self,
        ticker: str,
        exchange: str,
        period: str = "D",
        count: int = 100,
        end_date: str = "",
    ) -> list[OHLCV]:
        """한국 국내주식 일/주/월봉 조회."""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "0",
        }
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST01010400",  # 실전/모의 동일
            params=params,
        )

        output = data.get("output", [])
        result: list[OHLCV] = []
        for item in output:
            date_str = item.get("stck_bsop_date", "")
            if not date_str:
                continue
            result.append(
                OHLCV(
                    date=self._format_date(date_str),
                    open=float(item.get("stck_oprc", 0)),
                    high=float(item.get("stck_hgpr", 0)),
                    low=float(item.get("stck_lwpr", 0)),
                    close=float(item.get("stck_clpr", 0)),
                    volume=int(float(item.get("acml_vol", 0))),
                )
            )
        return result

    async def _kr_place_order(
        self,
        ticker: str,
        exchange: str,
        side: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        """한국 국내주식 주문 (현금매수/매도)."""
        # TR_ID 선택
        if side == "BUY":
            tr_map = {"live": "TTTC0802U", "paper": "VTTC0802U"}
        else:  # SELL
            tr_map = {"live": "TTTC0801U", "paper": "VTTC0801U"}

        tr_id = self._get_tr_id(tr_map)

        # 가격을 틱 단위로 조정
        adjusted_price = int(adjust_price_to_tick(price, KR_TICK_SIZE_TABLE))

        body = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "PDNO": ticker,
            "ORD_DVSN": "00",  # 00=지정가
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(adjusted_price),
        }

        hashkey = await self._auth.get_hashkey(body)

        data = await self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            tr_id,
            body=body,
            extra_headers={"hashkey": hashkey},
        )

        output = data.get("output", {})
        order_no = output.get("ODNO", "")

        logger.info(
            "kis_kr_order_placed",
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=adjusted_price,
            order_no=order_no,
        )

        return output

    async def _kr_get_balance(self) -> dict[str, Any]:
        """한국 국내주식 잔고 조회."""
        tr_map = {"live": "TTTC8434R", "paper": "VTTC8434R"}
        tr_id = self._get_tr_id(tr_map)

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id,
            params=params,
        )

        positions = data.get("output1", [])
        summary_list = data.get("output2", [])
        summary = summary_list[0] if summary_list else {}

        return {
            "summary": summary,
            "positions": positions if isinstance(positions, list) else [],
        }

    async def _kr_get_filled_orders(
        self,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict[str, Any]]:
        """한국 국내주식 체결 내역 조회."""
        if not start_date:
            start_date = datetime.now().strftime("%Y%m%d")
        if not end_date:
            end_date = start_date

        tr_map = {"live": "TTTC8001R", "paper": "VTTC8001R"}
        tr_id = self._get_tr_id(tr_map)

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id,
            params=params,
        )

        return data.get("output1", [])

    async def _kr_get_unfilled_orders(self) -> list[dict[str, Any]]:
        """한국 국내주식 미체결 조회."""
        # Paper 모의투자에서 VTTC8036R 미지원 (90000000 에러)
        if self._settings.is_paper:
            return []
        tr_map = {"live": "TTTC8036R", "paper": "VTTC8036R"}
        tr_id = self._get_tr_id(tr_map)

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0",
            "INQR_DVSN_2": "0",
        }

        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl",
            tr_id,
            params=params,
        )

        return data.get("output", [])

    async def _kr_get_purchasable_amount(
        self,
        ticker: str,
        exchange: str,
        price: float,
    ) -> dict[str, Any]:
        """한국 국내주식 매수가능금액 조회."""
        tr_map = {"live": "TTTC8908R", "paper": "VTTC8908R"}
        tr_id = self._get_tr_id(tr_map)

        adjusted_price = int(adjust_price_to_tick(price, KR_TICK_SIZE_TABLE))

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "PDNO": ticker,
            "ORD_UNPR": str(adjusted_price),
            "ORD_DVSN": "00",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "N",
        }

        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            tr_id,
            params=params,
        )

        return data.get("output", {})

    # ────────────────────────────────────────────────────────
    # 시세 조회
    # ────────────────────────────────────────────────────────

    async def get_current_price(self, ticker: str, exchange: str, *, market: str = "US") -> dict[str, Any]:
        """
        현재가 상세 조회.

        Args:
            ticker: 종목 코드 (예: "AAPL" 또는 "005930")
            exchange: 거래소 코드 (예: "NASD", "NYSE", "AMEX")
            market: 시장 구분 ("US" 또는 "KR")

        Returns:
            현재가 정보 dict (stck_prpr: 현재가, stck_oprc: 시가, 등)
        """
        if market == "KR":
            return await self._kr_get_current_price(ticker, exchange)

        # Bug #20 fix: paper 모드에서 price-detail은 빈 응답 반환
        # → /quotations/price (기본) 엔드포인트 사용 + 단축 거래소 코드(NYS/NAS/AMS)
        short_excd = EXCHANGE_SHORT_MAP.get(exchange, exchange)
        params = {
            "AUTH": "",
            "EXCD": short_excd,
            "SYMB": ticker,
        }
        data = await self._request(
            "GET",
            "/uapi/overseas-price/v1/quotations/price",
            self._get_tr_id(TR_PRICE),
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
        *,
        market: str = "US",
    ) -> list[OHLCV]:
        """
        기간별 시세 (일봉 OHLCV) 조회.

        Args:
            ticker: 종목 코드
            exchange: 거래소 코드
            period: "D"=일봉, "W"=주봉, "M"=월봉
            count: 조회 건수 (최대 100)
            end_date: 조회 종료일 (YYYYMMDD, 공백이면 오늘)
            market: 시장 구분 ("US" 또는 "KR")

        Returns:
            OHLCV 리스트 (최신 날짜부터)
        """
        if market == "KR":
            return await self._kr_get_daily_prices(ticker, exchange, period, count, end_date)

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
            "GUBN": "0",  # 0=일봉, 1=주봉, 2=월봉
            "BYMD": end_date,  # 공백이면 최신
            "MODP": "0",  # 0=수정주가 반영 안 함
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
        *,
        market: str = "US",
    ) -> list[OHLCV]:
        """
        여러 번 호출해서 지정 일수만큼의 일봉 데이터를 수집.

        한투 API는 1회 최대 100건이므로 300일이면 3번 호출.
        """
        all_data: list[OHLCV] = []
        end_date = ""

        while len(all_data) < days:
            batch = await self.get_daily_prices(
                ticker, exchange, period="D", count=100, end_date=end_date, market=market
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
        *,
        market: str = "US",
    ) -> dict[str, Any]:
        """
        지정가 주문.

        Args:
            ticker: 종목 코드
            exchange: 거래소 코드
            side: "BUY" 또는 "SELL"
            quantity: 수량
            price: 지정가
            market: 시장 구분 ("US" 또는 "KR")

        Returns:
            주문 응답 (ODNO: 주문번호 포함)
        """
        if market == "KR":
            return await self._kr_place_order(ticker, exchange, side, quantity, price)

        tr_map = TR_ORDER_BUY if side == "BUY" else TR_ORDER_SELL
        tr_id = self._get_tr_id(tr_map)

        # 주문 유형: 00=지정가
        # KIS 공식: 매도 시 SLL_TYPE="00" 필수, 매수 시 SLL_TYPE="" (빈값)
        body = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "SLL_TYPE": "00" if side == "SELL" else "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",  # 00=지정가
        }

        # DEBUG: 주문 요청 바디 로깅
        logger.warning(
            "kis_order_debug_body",
            tr_id=tr_id,
            side=side,
            ticker=ticker,
            body=body,
        )

        try:
            data = await self._request(
                "POST",
                "/uapi/overseas-stock/v1/trading/order",
                tr_id,
                body=body,
            )
        except KISAPIError as e:
            # 모의투자 해외주식에서 90000000 에러 시 주간주문 엔드포인트로 fallback
            if e.msg_cd == "90000000" and self._settings.is_paper:
                daytime_tr_map = TR_DAYTIME_ORDER_BUY if side == "BUY" else TR_DAYTIME_ORDER_SELL
                daytime_tr_id = self._get_tr_id(daytime_tr_map)
                logger.info(
                    "kis_order_fallback_daytime",
                    original_tr_id=tr_id,
                    daytime_tr_id=daytime_tr_id,
                    ticker=ticker,
                    side=side,
                )
                try:
                    data = await self._request(
                        "POST",
                        "/uapi/overseas-stock/v1/trading/daytime-order",
                        daytime_tr_id,
                        body=body,
                    )
                except KISAPIError as e2:
                    raise
            else:
                raise

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

    async def get_unfilled_orders(self, *, market: str = "US") -> list[dict[str, Any]]:
        """미체결 주문 조회."""
        if market == "KR":
            return await self._kr_get_unfilled_orders()

        all_orders: list[dict[str, Any]] = []
        seen_odno: set[str] = set()
        tr_id = await self._get_overseas_tr_id(TR_UNFILLED_DAY, TR_UNFILLED_NIGHT)

        for exchange in ("NASD", "NYSE", "AMEX"):
            try:
                params = {
                    "CANO": self._settings.account_number,
                    "ACNT_PRDT_CD": self._settings.account_product_code,
                    "OVRS_EXCG_CD": exchange,
                    "SORT_SQN": "DS",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }
                data = await self._request(
                    "GET",
                    "/uapi/overseas-stock/v1/trading/inquire-nccs",
                    tr_id,
                    params=params,
                )
                for order in data.get("output", []):
                    odno = order.get("odno", "")
                    if odno and odno not in seen_odno:
                        seen_odno.add(odno)
                        all_orders.append(order)
            except Exception:
                logger.warning("unfilled_query_failed", exchange=exchange, exc_info=True)

        return all_orders

    async def get_filled_orders(
        self,
        start_date: str = "",
        end_date: str = "",
        *,
        market: str = "US",
    ) -> list[dict[str, Any]]:
        """
        체결 내역 조회.

        Args:
            start_date: 조회 시작일 (YYYYMMDD)
            end_date: 조회 종료일 (YYYYMMDD)
            market: 시장 구분 ("US" 또는 "KR")
        """
        if market == "KR":
            return await self._kr_get_filled_orders(start_date, end_date)

        if not start_date:
            start_date = datetime.now().strftime("%Y%m%d")
        if not end_date:
            end_date = start_date

        all_fills: list[dict[str, Any]] = []
        seen_odno: set[str] = set()
        tr_id = await self._get_overseas_tr_id(TR_FILLED_DAY, TR_FILLED_NIGHT)

        for i, exchange in enumerate(("NASD", "NYSE", "AMEX")):
            if i > 0:
                await asyncio.sleep(1)  # KIS 초당 거래건수 제한 방지
            try:
                params = {
                    "CANO": self._settings.account_number,
                    "ACNT_PRDT_CD": self._settings.account_product_code,
                    "PDNO": "",
                    "ORD_STRT_DT": start_date,
                    "ORD_END_DT": end_date,
                    "SLL_BUY_DVSN": "00",
                    "CCLD_NCCS_DVSN": "01",
                    "OVRS_EXCG_CD": exchange,
                    "SORT_SQN": "DS",
                    "ORD_DT": "",
                    "ORD_GNO_BRNO": "",
                    "ODNO": "",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }
                data = await self._request(
                    "GET",
                    "/uapi/overseas-stock/v1/trading/inquire-ccnl",
                    tr_id,
                    params=params,
                )
                for fill in data.get("output", []):
                    odno = fill.get("odno", "")
                    if odno and odno not in seen_odno:
                        seen_odno.add(odno)
                        all_fills.append(fill)
            except Exception:
                logger.warning("filled_query_failed", exchange=exchange, exc_info=True)

        return all_fills

    async def get_balance(self, *, market: str = "US") -> dict[str, Any]:
        """
        잔고 조회.

        Args:
            market: 시장 구분 ("US" 또는 "KR")

        Returns:
            {
                "summary": {...},                      # 계좌 요약
                "positions": [{...}, {...}, ...],      # 보유 종목 리스트
            }
        """
        if market == "KR":
            return await self._kr_get_balance()

        tr_id = await self._get_overseas_tr_id(TR_BALANCE_DAY, TR_BALANCE_NIGHT)
        all_positions: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}

        for i, exchange in enumerate(("NASD", "NYSE", "AMEX")):
            if i > 0:
                await asyncio.sleep(1)  # KIS 초당 거래건수 제한 방지
            try:
                params = {
                    "CANO": self._settings.account_number,
                    "ACNT_PRDT_CD": self._settings.account_product_code,
                    "OVRS_EXCG_CD": exchange,
                    "TR_CRCY_CD": "USD",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }
                data = await self._request(
                    "GET",
                    "/uapi/overseas-stock/v1/trading/inquire-balance",
                    tr_id,
                    params=params,
                )
                # KIS API 응답 형식:
                # - output1: 보유 종목 리스트 (list[dict]) 또는 빈 경우 빈 list/dict
                # - output2: 계좌 요약 (dict 또는 list)
                raw_positions = data.get("output1", [])
                raw_summary = data.get("output2", {})

                # summary 정규화
                if isinstance(raw_summary, list):
                    exch_summary = raw_summary[0] if raw_summary else {}
                else:
                    exch_summary = raw_summary
                if exch_summary:
                    summary = exch_summary

                # positions 정규화: list면 보유종목, dict면 단일항목 또는 빈값
                if isinstance(raw_positions, list):
                    all_positions.extend(raw_positions)
                elif isinstance(raw_positions, dict) and raw_positions.get("ovrs_pdno"):
                    all_positions.append(raw_positions)
            except Exception as exc:
                logger.warning(
                    "get_balance_exchange_failed",
                    exchange=exchange,
                    error=str(exc),
                )

        # 중복 제거: 모의투자에서 여러 거래소 쿼리 시 같은 종목이 반복될 수 있음
        seen_tickers: set[str] = set()
        unique_positions: list[dict[str, Any]] = []
        for pos in all_positions:
            ticker = pos.get("ovrs_pdno", "")
            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                unique_positions.append(pos)

        return {
            "summary": summary,
            "positions": unique_positions,
        }

    async def get_purchasable_amount(
        self,
        ticker: str = "AAPL",
        exchange: str = "NASD",
        price: str = "100",
        *,
        market: str = "US",
    ) -> dict[str, Any]:
        """
        매수가능금액 조회.

        Args:
            ticker: 종목 코드
            exchange: 거래소 코드
            price: 가격 (문자열)
            market: 시장 구분 ("US" 또는 "KR")
        """
        if market == "KR":
            return await self._kr_get_purchasable_amount(ticker, exchange, float(price))

        params = {
            "CANO": self._settings.account_number,
            "ACNT_PRDT_CD": self._settings.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "OVRS_ORD_UNPR": price,
            "ITEM_CD": ticker,
        }
        tr_id = await self._get_overseas_tr_id(TR_PSAMOUNT_DAY, TR_PSAMOUNT_NIGHT)
        data = await self._request(
            "GET",
            "/uapi/overseas-stock/v1/trading/inquire-psamount",
            tr_id,
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
            "BRK.A",
            "BRK.B",
            "JPM",
            "V",
            "JNJ",
            "WMT",
            "PG",
            "UNH",
            "HD",
            "BAC",
            "MA",
            "DIS",
            "KO",
            "PFE",
            "MRK",
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
