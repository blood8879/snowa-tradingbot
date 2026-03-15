"""시장별 설정 (미국/한국 주식)

각 시장(미국, 한국)의 거래소, 시간대, TR_ID, 틱 단위 등을 정의합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# 한국 주식 틱 단위 테이블 (가격 구간별)
KR_TICK_SIZE_TABLE = [
    (1_000, 1),
    (5_000, 5),
    (10_000, 10),
    (50_000, 50),
    (100_000, 100),
    (500_000, 500),
    (float('inf'), 1_000),
]


@dataclass
class MarketConfig:
    """시장별 설정 데이터클래스

    Attributes:
        market_id: 시장 ID ("US" 또는 "KR")
        display_name: 표시용 이름
        exchanges: 거래소 목록
        currency: 통화 코드
        pre_market_hour, pre_market_minute: 장전 시간 (KST)
        market_open_hour, market_open_minute: 개장 시간 (KST)
        market_close_hour, market_close_minute: 폐장 시간 (KST)
        post_market_hour, post_market_minute: 장후 시간 (KST)
        screening_hour, screening_minute: 스크리닝 시간 (KST)
        benchmark_ticker: 벤치마크 종목 (SPY, KODEX200 등)
        benchmark_exchange: 벤치마크 거래소
        ws_tr_id: WebSocket TR_ID
        rest_base_path: REST API 기본 경로
        order_buy_tr: 매수 주문 TR_ID (live/paper)
        order_sell_tr: 매도 주문 TR_ID (live/paper)
        balance_tr: 잔고 조회 TR_ID (live/paper)
        filled_orders_tr: 체결 조회 TR_ID (live/paper)
        unfilled_orders_tr: 미체결 조회 TR_ID (live/paper)
        purchasable_amount_tr: 매수 가능 금액 조회 TR_ID (live/paper)
        current_price_tr: 현재가 조회 TR_ID (live/paper)
        daily_price_tr: 일봉 조회 TR_ID (live/paper)
        tick_size_table: 틱 단위 테이블 (한국만 사용, 미국은 None)
        donchian_exit_minutes_before_close: 돈치안 청산 시간 (폐장 전 분)
        day_of_week_schedule: 거래일 스케줄
        supports_market_order: 시장가 주문 지원 여부
    """
    market_id: str
    display_name: str
    exchanges: list[str]
    currency: str

    # 시간 설정 (KST 기준)
    pre_market_hour: int
    pre_market_minute: int
    market_open_hour: int
    market_open_minute: int
    market_close_hour: int
    market_close_minute: int
    post_market_hour: int
    post_market_minute: int
    screening_hour: int
    screening_minute: int

    # 벤치마크 설정
    benchmark_ticker: str
    benchmark_exchange: str

    # API 설정
    ws_tr_id: str
    rest_base_path: str

    # TR_ID 설정 (각각 live/paper 구분)
    order_buy_tr: dict[str, str]
    order_sell_tr: dict[str, str]
    balance_tr: dict[str, str]
    filled_orders_tr: dict[str, str]
    unfilled_orders_tr: dict[str, str]
    purchasable_amount_tr: dict[str, str]
    current_price_tr: dict[str, str]
    daily_price_tr: dict[str, str]

    # 틱 단위 테이블 (한국만 사용)
    tick_size_table: list[tuple[float, float]] | None = None

    # 거래 설정
    donchian_exit_minutes_before_close: int = 15
    day_of_week_schedule: str = "mon-fri"
    supports_market_order: bool = False


# 미국 주식 설정
US_MARKET = MarketConfig(
    market_id="US",
    display_name="미국 주식",
    exchanges=["NASD", "NYSE", "AMEX"],
    currency="USD",

    # 시간 설정 (KST 기준)
    pre_market_hour=22,
    pre_market_minute=0,
    market_open_hour=23,
    market_open_minute=30,
    market_close_hour=6,
    market_close_minute=0,
    post_market_hour=6,
    post_market_minute=30,
    screening_hour=20,
    screening_minute=0,

    # 벤치마크
    benchmark_ticker="SPY",
    benchmark_exchange="NASD",

    # API 설정
    ws_tr_id="HDFSCNT0",
    rest_base_path="/uapi/overseas-stock/v1",

    # TR_ID 설정
    order_buy_tr={"live": "JTTT1002U", "paper": "VTTT1002U"},
    order_sell_tr={"live": "JTTT1006U", "paper": "VTTT1001U"},
    balance_tr={"live": "TTTS3012R", "paper": "VTTS3012R"},
    filled_orders_tr={"live": "TTTS3035R", "paper": "VTTS3035R"},
    unfilled_orders_tr={"live": "TTTS3018R", "paper": "VTTS3018R"},
    purchasable_amount_tr={"live": "TTTS3007R", "paper": "VTTS3007R"},
    current_price_tr={"live": "HHDFS76200200", "paper": "HHDFS76200200"},
    daily_price_tr={"live": "HHDFS76240000", "paper": "HHDFS76240000"},

    # 거래 설정
    tick_size_table=None,
    donchian_exit_minutes_before_close=15,
    day_of_week_schedule="mon-fri",
    supports_market_order=False,
)


# 한국 주식 설정
KR_MARKET = MarketConfig(
    market_id="KR",
    display_name="한국 주식",
    exchanges=["KOSPI", "KOSDAQ"],
    currency="KRW",

    # 시간 설정 (KST 기준)
    pre_market_hour=8,
    pre_market_minute=0,
    market_open_hour=9,
    market_open_minute=0,
    market_close_hour=15,
    market_close_minute=30,
    post_market_hour=16,
    post_market_minute=0,
    screening_hour=7,
    screening_minute=0,

    # 벤치마크
    benchmark_ticker="069500",
    benchmark_exchange="KOSPI",

    # API 설정
    ws_tr_id="H0STCNT0",
    rest_base_path="/uapi/domestic-stock/v1",

    # TR_ID 설정
    order_buy_tr={"live": "TTTC0802U", "paper": "VTTC0802U"},
    order_sell_tr={"live": "TTTC0801U", "paper": "VTTC0801U"},
    balance_tr={"live": "TTTC8434R", "paper": "VTTC8434R"},
    filled_orders_tr={"live": "TTTC8001R", "paper": "VTTC8001R"},
    unfilled_orders_tr={"live": "TTTC8001R", "paper": "VTTC8001R"},
    purchasable_amount_tr={"live": "TTTC8908R", "paper": "VTTC8908R"},
    current_price_tr={"live": "FHKST01010100", "paper": "FHKST01010100"},
    daily_price_tr={"live": "FHKST01010400", "paper": "FHKST01010400"},

    # 거래 설정
    tick_size_table=KR_TICK_SIZE_TABLE,
    donchian_exit_minutes_before_close=15,
    day_of_week_schedule="mon-fri",
    supports_market_order=True,
)


def get_market_config(market_id: str) -> MarketConfig:
    """시장 ID로 설정 조회

    Args:
        market_id: 시장 ID ("US" 또는 "KR")

    Returns:
        해당 시장의 MarketConfig

    Raises:
        ValueError: 지원하지 않는 시장 ID인 경우
    """
    if market_id == "US":
        return US_MARKET
    elif market_id == "KR":
        return KR_MARKET
    else:
        raise ValueError(f"지원하지 않는 시장 ID: {market_id}")


def adjust_price_to_tick(price: float, tick_table: list[tuple[float, float]]) -> float:
    """한국 주식 틱 단위에 맞게 가격 조정 (내림)

    Args:
        price: 원본 가격
        tick_table: 틱 단위 테이블 [(가격 상한, 틱 크기), ...]

    Returns:
        틱 단위로 내림한 가격
    """
    if tick_table is None:
        return price

    for upper_bound, tick_size in tick_table:
        if price < upper_bound:
            return (price // tick_size) * tick_size

    # 마지막 구간
    _, tick_size = tick_table[-1]
    return (price // tick_size) * tick_size


def get_all_markets() -> list[MarketConfig]:
    """전체 시장 설정 목록 반환

    Returns:
        [US_MARKET, KR_MARKET]
    """
    return [US_MARKET, KR_MARKET]
