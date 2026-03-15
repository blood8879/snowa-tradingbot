# 한국 장 자동매매 확장 계획

## 개요

현재 미국 주식 전용인 Snowa Trading Bot을 **한국 주식(KOSPI/KOSDAQ)** 시장까지 확장하여, 하나의 봇에서 양 시장을 동시에 운영하고 대시보드에서 마켓별 on/off 제어가 가능하도록 한다.

### 핵심 결정 사항
- **운영 방식**: 단일 봇, 듀얼 마켓 (한국 09:00~15:30 KST, 미국 23:30~06:00 KST — 시간 비중첩)
- **전략**: 동일 Turtle Trading + CANSLIM
- **데이터**: KIS API (국내주식 엔드포인트)
- **계좌**: 동일 앱키, 단일 계좌
- **모드**: Paper(모의투자) 먼저 검증 후 Live 전환
- **구현**: 3단계 단계적 구현

---

## 현재 아키텍처 vs 변경 필요 사항

### 미국 전용 하드코딩 5대 영역

| 영역 | 현재 (US 전용) | 변경 후 (듀얼 마켓) |
|------|---------------|-------------------|
| **거래소 코드** | NASD/NYSE/AMEX | + KRX (KOSPI/KOSDAQ) |
| **장 시간** | 23:30~06:00 KST 고정 | 마켓별 스케줄러 |
| **KIS TR_ID** | 해외주식 (JTTT/HHDFS/VTTT) | + 국내주식 (TTTC/FHKST/VTTC) |
| **데이터 소스** | NASDAQ API + yfinance | + KIS 국내 시세 API |
| **벤치마크** | SPY 200SMA | + KOSPI200 (069500) 200SMA |

---

## Phase 1: 마켓 추상화 + KIS 국내 API (핵심 인프라)

> 목표: 코드베이스에 "마켓" 개념을 도입하고, KIS 국내주식 API를 통합

### 1.1 MarketConfig 추상화 레이어

**새 파일: `config/market_config.py`**

```python
@dataclass
class MarketConfig:
    market_id: str          # "US" | "KR"
    display_name: str       # "미국 주식" | "한국 주식"
    exchanges: list[str]    # ["NASD","NYSE","AMEX"] | ["KOSPI","KOSDAQ"]
    currency: str           # "USD" | "KRW"

    # 장 시간 (KST)
    pre_market_kst: str     # "22:00" | "08:00"
    market_open_kst: str    # "23:30" | "09:00"
    market_close_kst: str   # "06:00" | "15:30"
    post_market_kst: str    # "06:30" | "16:00"

    # 전략 파라미터
    benchmark_ticker: str   # "SPY" | "069500" (KODEX200)
    benchmark_exchange: str # "NASD" | "KOSPI"

    # KIS API 설정
    ws_tr_id: str           # "HDFSCNT0" | "H0STCNT0"
    rest_base_path: str     # "/uapi/overseas-stock/v1" | "/uapi/domestic-stock/v1"
    order_buy_tr: dict      # {"live": "JTTT1002U", "paper": "VTTT1002U"} | {"live": "TTTC0802U", "paper": "VTTC0802U"}
    order_sell_tr: dict     # {"live": "JTTT1006U", "paper": "VTTT1006U"} | {"live": "TTTC0801U", "paper": "VTTC0801U"}

    # 호가단위 (한국 전용)
    tick_size_table: list | None  # [(1000, 1), (5000, 5), (10000, 10), ...]
```

**변경 파일: `config/constants.py`**
- `MARKET_BENCHMARK = "SPY"` → `MarketConfig`로 이동
- 마켓별 독립 상수 관리

### 1.2 KIS REST 국내주식 API 통합

**변경 파일: `broker/kis_rest.py`**

국내주식 전용 메서드 추가 (기존 해외주식 메서드는 그대로 유지):

| 기능 | 메서드 | 국내 TR_ID | 엔드포인트 |
|------|--------|-----------|-----------|
| 현재가 | `get_current_price_kr()` | FHKST01010100 | `/uapi/domestic-stock/v1/quotations/inquire-price` |
| 일별시세 | `get_daily_prices_kr()` | FHKST01010400 | `/uapi/domestic-stock/v1/quotations/inquire-daily-price` |
| 매수 | `place_order_kr(side="BUY")` | TTTC0802U/VTTC0802U | `/uapi/domestic-stock/v1/trading/order-cash` |
| 매도 | `place_order_kr(side="SELL")` | TTTC0801U/VTTC0801U | `/uapi/domestic-stock/v1/trading/order-cash` |
| 잔고 | `get_balance_kr()` | TTTC8434R/VTTC8434R | `/uapi/domestic-stock/v1/trading/inquire-balance` |
| 체결내역 | `get_filled_orders_kr()` | TTTC8001R/VTTC8001R | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` |
| 미체결 | `get_unfilled_orders_kr()` | TTTC8001R/VTTC8001R | `/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl` |
| 매수가능 | `get_purchasable_amount_kr()` | TTTC8908R/VTTC8908R | `/uapi/domestic-stock/v1/trading/inquire-psbl-order` |

**핵심 차이점**:
- 국내주식은 exchange 파라미터 불필요 (6자리 종목코드만 사용)
- 국내주식은 야간/주간 TR_ID 구분 없음
- 국내주식은 **시장가 주문(01) 가능** (해외는 지정가만)
- 호가단위(tick size) 규칙 적용 필요

**라우터 패턴 도입**:
```python
class KISRestClient:
    def get_current_price(self, ticker: str, market: str = "US", exchange: str = ""):
        if market == "KR":
            return self._get_current_price_kr(ticker)
        return self._get_current_price_us(ticker, exchange)

    def place_order(self, ticker: str, side: str, qty: int, price: float, market: str = "US", ...):
        if market == "KR":
            return self._place_order_kr(ticker, side, qty, price)
        return self._place_order_us(ticker, side, qty, price, exchange)
```

### 1.3 KIS WebSocket 국내주식 구독

**변경 파일: `broker/kis_websocket.py`**

- 구독 TR_ID: `H0STCNT0` (국내 실시간 체결가)
- tr_key: 6자리 종목코드 (예: `005930`)
- 응답 파싱 포맷: 해외(`HDFSCNT0`)와 다른 필드 구조
- **제한**: 국내+해외 합계 최대 20종목 실시간 구독

**변경사항**:
```python
# 기존: 해외 전용
self._WS_EXCHANGE_MAP = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

# 추가: 국내는 exchange 매핑 불필요, tr_id만 다름
def subscribe(self, ticker, market="US", exchange="NASD"):
    if market == "KR":
        tr_id = "H0STCNT0"
        tr_key = ticker  # "005930"
    else:
        tr_id = "HDFSCNT0"
        tr_key = f"{ws_exchange}.{ticker}"
```

### 1.4 DB 스키마 변경

**변경 파일: `core/database.py`**

기존 테이블에 `market` 컬럼 추가:

```sql
-- watchlist: market 컬럼 추가
ALTER TABLE watchlist ADD COLUMN market TEXT DEFAULT 'US';

-- positions: market 컬럼 추가
ALTER TABLE positions ADD COLUMN market TEXT DEFAULT 'US';

-- orders: market 컬럼 추가
ALTER TABLE orders ADD COLUMN market TEXT DEFAULT 'US';

-- daily_log: market 컬럼 추가 (마켓별 일일 기록)
ALTER TABLE daily_log ADD COLUMN market TEXT DEFAULT 'US';
-- daily_log PK 변경: (date) → (date, market)

-- bot_state: 마켓별 상태 저장
-- key 네이밍: "kr_last_heartbeat", "us_ws_status" 등
```

### 1.5 마켓별 활성화/비활성화

**변경 파일: `bot/trading_bot.py`**

```python
# bot_state에 마켓별 활성화 상태 저장
# key: "market_enabled_US" = "true"
# key: "market_enabled_KR" = "true"

async def is_market_enabled(self, market: str) -> bool:
    val = await self.db.get_state(f"market_enabled_{market}")
    return val != "false"  # 기본값 true
```

### Phase 1 영향 범위

| 파일 | 변경 유형 | 규모 |
|------|----------|------|
| `config/market_config.py` | **신규** | ~150줄 |
| `config/constants.py` | 수정 | ~30줄 |
| `broker/kis_rest.py` | 수정 (국내 메서드 추가) | ~300줄 |
| `broker/kis_websocket.py` | 수정 (국내 구독 지원) | ~100줄 |
| `broker/order_executor.py` | 수정 (마켓 파라미터 전달) | ~50줄 |
| `core/database.py` | 수정 (마이그레이션 추가) | ~50줄 |
| `bot/trading_bot.py` | 수정 (듀얼 스케줄러) | ~100줄 |
| `bot/intraday_monitor.py` | 수정 (마켓 파라미터) | ~50줄 |
| `bot/pre_market.py` | 수정 (마켓별 pre-market) | ~50줄 |
| `bot/post_market.py` | 수정 (마켓별 post-market) | ~50줄 |

**예상 작업량**: ~930줄 변경/추가

---

## Phase 2: 한국 주식 스크리닝 + 전략 적용

> 목표: KOSPI/KOSDAQ 종목 유니버스를 구축하고, CANSLIM + Turtle Trading 적용

### 2.1 한국 주식 유니버스

**새 파일: `data/universe_kr.py`**

한국 종목 리스트 소스 옵션:
1. **KIS API 종목마스터**: 일별 갱신되는 마스터 파일 다운로드
2. **KRX 정보데이터시스템**: `data.krx.co.kr` API (무료)
3. **pykrx 라이브러리**: `pip install pykrx` — KRX 공식 데이터

```python
class KRUniverseLoader:
    """KOSPI + KOSDAQ 종목 리스트 로더"""

    async def load_universe(self) -> dict[str, dict]:
        """
        Returns: {
            "005930": {"name": "삼성전자", "exchange": "KOSPI", "market_cap": 400_000_000},
            "035720": {"name": "카카오", "exchange": "KOSDAQ", "market_cap": 20_000_000},
            ...
        }
        """
        # 옵션 1: KRX API 사용
        # 옵션 2: pykrx 라이브러리
        # 필터: 관리종목/거래정지 제외, 보통주만
```

**필터링 기준** (미국과 동일 원칙):
- 시가총액 > 1,000억원
- 일평균 거래량 > 50,000주
- 관리종목/거래정지 제외
- 우선주/ETF/ETN/SPAC 제외

### 2.2 한국 주식 가격 데이터

**변경 파일: `data/price_cache.py`**

KIS API 일별시세 조회 (FHKST01010400) 사용:
```python
async def fetch_daily_prices_kr(self, ticker: str, days: int = 300):
    """KIS API로 국내주식 일별 OHLCV 가져오기"""
    # KIS 국내 일별시세: 최대 100건/요청 → 300일이면 3번 호출
    # 페이징: FID_INPUT_DATE_1, FID_INPUT_DATE_2 파라미터로 기간 지정
```

**대안 (더 효율적)**: `pykrx` 라이브러리로 벌크 다운로드
```python
from pykrx import stock
df = stock.get_market_ohlcv("20250101", "20260228", "005930")
```

### 2.3 한국 주식 재무 데이터

**변경 파일: `data/fundamental_data.py`**

CANSLIM에 필요한 재무 데이터:
- **분기 EPS 성장률**: KIS API 재무제표 조회 또는 DART API
- **연간 EPS CAGR**: 최근 5년 실적
- **기관 보유비율**: KIS API 투자자별 매매동향

**데이터 소스 옵션**:
1. **DART OpenAPI** (전자공시): EPS, 매출, 순이익 — 무료, 분기별
2. **KIS API 재무비율**: `/uapi/domestic-stock/v1/finance/financial-ratio`
3. **FnGuide/WiseFn**: 유료 API (가장 정확)

**권장**: DART OpenAPI (무료 + 공식 데이터)
```python
# DART API Key 필요 (https://opendart.fss.or.kr)
# 분기보고서: /api/fnlttSinglAcntAll.json
# 사업보고서: /api/fnlttSinglAcnt.json
```

### 2.4 한국 RS Rating 계산

**변경 파일: `screening/rs_rating.py`**

- 기존: 미국 유니버스 대비 상대강도
- 추가: **한국 유니버스 대비** 상대강도 (별도 계산)
- 계산 로직은 동일 (3/6/9/12개월 가중 수익률, 백분위)

```python
def calculate_rs_ratings(prices: dict, market: str = "US") -> dict:
    # market별로 별도 유니버스 기준 RS 계산
    # 한국 유니버스: KOSPI+KOSDAQ ~2,500종목
```

### 2.5 한국 마켓 필터

**변경 파일: `strategy/market_filter.py`**

- 미국: SPY > 200SMA
- 한국: KODEX200 (069500) > 200SMA 또는 KOSPI 지수 > 200SMA

```python
async def get_market_filter_status(market_data, market: str = "US"):
    if market == "KR":
        benchmark = "069500"  # KODEX200 ETF
    else:
        benchmark = "SPY"
    # 나머지 로직 동일
```

### 2.6 한국 주식 특수 규칙

**호가단위 적용** (주문 가격 조정):
```python
TICK_SIZE_TABLE_KR = [
    (1_000, 1),      # ~1,000원: 1원 단위
    (5_000, 5),      # ~5,000원: 5원 단위
    (10_000, 10),    # ~10,000원: 10원 단위
    (50_000, 50),    # ~50,000원: 50원 단위
    (100_000, 100),  # ~100,000원: 100원 단위
    (500_000, 500),  # ~500,000원: 500원 단위
    (float('inf'), 1_000),  # 500,000원~: 1,000원 단위
]

def adjust_price_to_tick(price: float, table: list) -> float:
    """주문 가격을 호가단위에 맞춰 조정"""
```

**가격 제한** (상한가/하한가 ±30%):
- 손절가 계산 시 ±30% 제한 고려
- 주문가가 가격 제한 범위 내인지 검증

### Phase 2 영향 범위

| 파일 | 변경 유형 | 규모 |
|------|----------|------|
| `data/universe_kr.py` | **신규** | ~200줄 |
| `data/price_cache.py` | 수정 | ~100줄 |
| `data/fundamental_data.py` | 수정 | ~150줄 |
| `screening/canslim_screener.py` | 수정 (마켓 파라미터) | ~50줄 |
| `screening/rs_rating.py` | 수정 (마켓별 계산) | ~30줄 |
| `screening/minervini_template.py` | 수정 (마켓 파라미터) | ~20줄 |
| `strategy/market_filter.py` | 수정 | ~30줄 |
| `strategy/entry_signals.py` | 수정 (호가단위) | ~20줄 |
| `bot/daily_screening.py` | 수정 (한국 스크리닝 추가) | ~80줄 |
| `config/market_config.py` | 수정 (호가단위 테이블) | ~30줄 |

**예상 작업량**: ~710줄 변경/추가

---

## Phase 3: 대시보드 + 통합 테스트

> 목표: 대시보드에서 마켓별 제어 가능, 전체 통합 검증

### 3.1 대시보드 API 확장

**변경 파일: `web/api/main.py`**

```python
# 마켓별 필터링
@app.get("/api/watchlist")
async def get_watchlist(market: str = None):  # market=KR 또는 US
    ...

@app.get("/api/positions")
async def get_positions(market: str = None):
    ...

# 마켓별 활성화/비활성화 토글
@app.post("/api/market/{market_id}/toggle")
async def toggle_market(market_id: str, enabled: bool):
    await db.set_state(f"market_enabled_{market_id}", str(enabled).lower())
    return {"market": market_id, "enabled": enabled}

# 마켓별 상태 조회
@app.get("/api/market/status")
async def market_status():
    return {
        "US": {"enabled": ..., "is_open": ..., "positions": ..., "equity": ...},
        "KR": {"enabled": ..., "is_open": ..., "positions": ..., "equity": ...},
    }
```

### 3.2 프론트엔드 마켓 선택기

**변경 파일: `web/frontend/` (React)**

- 헤더에 마켓 토글 스위치 (US / KR / 전체)
- 포지션/워치리스트/주문내역에 마켓 필터
- 마켓별 수익률 차트
- 마켓별 on/off 스위치

### 3.3 통합 테스트

**테스트 시나리오**:

1. **단위 테스트**:
   - KIS 국내 REST API 호출 (mock)
   - 호가단위 계산 정확성
   - 마켓별 스케줄러 독립 동작

2. **통합 테스트 (Paper 모드)**:
   - 한국 장 시간에 봇 가동 → 스크리닝 → 시그널 → 주문
   - 미국 장 시간에도 정상 동작 (기존 기능 회귀 없음)
   - 양 마켓 동시 포지션 관리

3. **안정성 테스트**:
   - 24시간 연속 가동 (한국 장 → 미국 장 전환)
   - WS 연결 관리 (국내 20종목 제한 준수)
   - 마켓 토글 on/off 시 정상 전환

### Phase 3 영향 범위

| 파일 | 변경 유형 | 규모 |
|------|----------|------|
| `web/api/main.py` | 수정 | ~100줄 |
| `web/frontend/` (여러 파일) | 수정 | ~300줄 |
| `tests/` (여러 파일) | **신규** | ~400줄 |

**예상 작업량**: ~800줄 변경/추가

---

## 스케줄 타임라인 (단일 봇 듀얼 마켓)

```
KST 시간대별 봇 동작:

06:30  ── 미국 장 Post-Market (sync, cleanup)
07:00  ── 유휴
08:00  ── 한국 장 Pre-Market (스크리닝, 시그널 계산)
09:00  ── 한국 장 Market Open (WS 구독, 장중 모니터링)
15:30  ── 한국 장 Market Close
16:00  ── 한국 장 Post-Market (sync, cleanup)
17:00  ── 유휴
20:00  ── 미국 장 Daily Screening (CANSLIM)
22:00  ── 미국 장 Pre-Market (시그널 계산)
23:30  ── 미국 장 Market Open (WS 구독, 장중 모니터링)
06:00  ── 미국 장 Market Close
```

> 한국 장(09:00~15:30)과 미국 장(23:30~06:00)은 시간이 겹치지 않으므로 WS 구독 전환이 자연스럽게 가능.

---

## 리스크 및 주의사항

### 기술적 리스크

1. **WS 동시 구독 20종목 제한**
   - 국내+해외 합계 20종목
   - 현재 미국 22종목 구독 중 → 제한 초과 가능
   - **대응**: 마켓 전환 시 이전 마켓 구독 해제 후 신규 구독. 시간이 겹치지 않으므로 가능.

2. **API Rate Limit**
   - Paper: 5req/sec (미국과 동일)
   - Live: 20req/sec (미국 해외주식도 동일)
   - **대응**: 기존 딜레이 로직 재활용

3. **통화 분리 (KRW vs USD)**
   - 포지션 사이징: 원화 기준 계산 필요
   - 통합 수익률: 환율 적용 필요
   - **대응**: 마켓별 독립 equity 관리, 대시보드에서만 합산 표시

4. **한국 주식 재무 데이터 품질**
   - KIS API 재무 데이터가 CANSLIM에 충분한지 검증 필요
   - DART API 보조 활용 가능
   - **대응**: Phase 2에서 데이터 품질 검증 후 결정

### 운영 리스크

5. **Paper 모드 한계**
   - KIS 모의투자 국내주식도 API 제한 있을 수 있음
   - **대응**: Phase 1에서 API 호출 테스트 후 확인

6. **동일 앱키 WS 충돌**
   - 국내/해외 WS를 동일 앱키로 동시에 열 수 있는지 확인 필요
   - **대응**: 단일 WS 연결에서 국내/해외 동시 구독 가능 (확인 필요)

---

## 의존성 및 새 패키지

| 패키지 | 용도 | 필수 여부 |
|--------|------|----------|
| `pykrx` | 한국 주식 가격 벌크 다운로드 | 선택 (KIS API로도 가능) |
| `dart-fss` 또는 직접 호출 | DART 재무 데이터 | CANSLIM에 필요 시 |

---

## 총 예상 작업량

| Phase | 신규 파일 | 변경 파일 | 예상 코드량 |
|-------|----------|----------|------------|
| Phase 1: 인프라 | 1 | 9 | ~930줄 |
| Phase 2: 스크리닝 | 1 | 8 | ~710줄 |
| Phase 3: 대시보드 | 0 | 3+ | ~800줄 |
| **합계** | **2** | **~20** | **~2,440줄** |

---

## 구현 순서 (Phase 1 세부)

Phase 1을 더 세분화하면:

```
1.1 config/market_config.py 생성 (MarketConfig 클래스)
    ↓
1.2 core/database.py 마이그레이션 (market 컬럼 추가)
    ↓
1.3 broker/kis_rest.py 국내 API 메서드 추가
    ↓ (1.3과 병렬 가능)
1.4 broker/kis_websocket.py 국내 구독 지원
    ↓
1.5 broker/order_executor.py 마켓 파라미터 전달
    ↓
1.6 bot/trading_bot.py 듀얼 스케줄러
    ↓ (1.6과 병렬 가능)
1.7 bot/pre_market.py, intraday_monitor.py, post_market.py 마켓 지원
    ↓
1.8 기본 동작 테스트 (Paper 모드, 한국 장 시간)
```

---

## 성공 기준

- [ ] 한국 장 시간(09:00~15:30)에 봇이 자동으로 국내주식 모니터링 시작
- [ ] KOSPI/KOSDAQ 종목 CANSLIM 스크리닝 정상 동작
- [ ] 국내주식 Turtle Trading 시그널 생성 및 주문 실행 (Paper)
- [ ] 미국 장 기존 기능 회귀 없음 (기존 5개 포지션 정상 관리)
- [ ] 대시보드에서 KR/US 마켓 토글 가능
- [ ] 24시간 연속 가동 시 한국→미국 장 전환 안정적
