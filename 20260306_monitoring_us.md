# 2026-03-06 미국 장 봇 감시 로그

## 감시 개요
- 감시 기간: 23:30 KST (3/6) ~ 06:30 KST (3/7) 완료
- 대상: Snowa Trading Bot (Paper 모의투자)
- 전략: CANSLIM x Turtle Trading Hybrid
- 보유 포지션 (장 시작): ISSC (1,414주)

## 장전 상태 (pre_market 13:00 UTC)
- Market filter: PASS (SPY 682.11 > SMA200 653.59)
- Watchlist: 16종목 + 1 position = signals 17개
- Gap-down 위험: 없음

## 장중 타임라인

### 14:30 UTC (23:30 KST) - 장 오픈
- [x] start_intraday 실행 확인
- [x] WebSocket 19종목 SUBSCRIBE SUCCESS
- [x] CVE 진입 신호 발동 → BUY 549주 @ $23.63 limit, 주문번호 0000041291
  - 실제 체결가: $23.52
  - 손절가: $22.07 (ATR 기반)

### 14:30~15:00 UTC - Bug#12 발견: fill check 체결 미감지

#### 현상
- CVE BUY 주문이 SUBMITTED 상태로 30분+ 체류
- fill_check_heartbeat: checks_done 60회, pending_orders=1 유지
- 에러 없음 - 단순히 매칭 실패

#### 원인 분석: **odno 제로패딩 불일치** (CRITICAL)
1. 주문 제출 API 응답: `order_no = "0000041291"` (선행 0 포함)
2. 체결 조회 API 응답: `odno = "41291"` (선행 0 제거)
3. `check_order_fills()`에서 `pending_orders["0000041291"]`로 저장
4. fill의 `odno = "41291"` → `"41291" not in pending_orders` → 매칭 실패

**이것이 어제 Bug#9(매도 체결 미감지 → 무한 재시도)의 근본 원인!**
- 어제는 EGW00201 rate limit이 원인이라 생각했으나, 실제로는 odno 불일치로 매칭 자체가 불가능
- rate limit은 3개 거래소 순회 시 발생한 부수 현상

#### 추가 버그: 자정 KST 날짜 불일치
- `get_filled_orders`의 기본 날짜 = `datetime.now().strftime("%Y%m%d")`
- 서버 시간 KST 기준 → 00:00 KST 이후 조회 날짜가 다음날로 변경
- 23:30 KST에 제출된 주문은 3/6 날짜 → 00:00 이후 3/7로 조회 → 영원히 매칭 불가

#### 수정 (Bug#12)
**파일**: `broker/order_executor.py`

1. **odno 정규화**: `lstrip("0")` 적용하여 양쪽 모두 선행 0 제거 후 매칭
   ```python
   # pending_orders 키 정규화
   normalized_key = order.broker_order_id.lstrip("0") or "0"
   pending_orders[normalized_key] = order

   # fill odno 정규화
   order_no = raw_odno.lstrip("0") or "0"
   ```

2. **날짜 범위 확장**: 주문 생성일 ~ 오늘(KST) 범위로 조회
   ```python
   order_dates = {created.strftime("%Y%m%d") for order in pending_orders}
   start_date = min(order_dates)
   end_date = max(today_str, max(order_dates))
   ```

#### 배포 & 검증 (15:06 UTC / 00:06 KST)
- 서버 배포 후 봇 재시작
- sync_positions: CVE broker_only로 감지 → OPEN 포지션 생성
- **첫 fill_check에서 즉시 CVE 체결 감지!**
  ```
  order_filled: CVE BUY 549주 @ $23.52
  fill_check_matched: count=1
  pending_orders: 0
  ```

### 15:07~15:23 UTC - Bug#13 발견: KR 종목 US WebSocket 혼합 구독 → 틱 수신 불가

#### 현상
- Bug#12 수정 후 봇 재시작 → 1개 틱 수신 후 WS 완전 침묵
- fill_check는 정상 실행(30초 간격) but WS에서 틱이 오지 않음
- 3회 연속 재시작 모두 동일 패턴: 1 tick → silence
- 봇 프로세스 alive (sleeping), crash 아님

#### 원인 분석: **KR 포지션이 US WebSocket에 혼합 구독** (CRITICAL)
1. `sync_positions`가 KR 포지션 3개(031980, 290550, 218410)를 생성
2. `pre_market(market="US")`에서 `get_open_positions()` → **시장 필터 없이** KR 포지션도 포함
3. `precomputed_signals`에 KR 종목 포함 → signals_count=20 (US 17 + KR 3)
4. `start_intraday`에서 모든 signals 종목을 US WS에 구독
5. KOSDAQ 종목(DKOSDAQ031980 등)이 US 실시간 WS에 구독됨
6. KIS WS 서버가 혼합 거래소 구독 시 **데이터 송출 중단** (1개 틱 후 침묵)

#### 비교
- 수정 전: `start_intraday`에서 `pos.market` 필터 없이 모든 포지션 추가
- KR 버전: `pos.market == "KR"` 필터 있음 (정상)

#### 수정 (Bug#13)
**파일**: `bot/trading_bot.py`, `bot/pre_market.py`

1. **trading_bot.py L616**: US start_intraday에서 `pos.market == "US"` 필터 추가
2. **pre_market.py L162**: US pre_market에서 `pos.market == market` 필터 추가
3. **pre_market.py L404**: gap_down_check에서 `pos.market != market` continue 추가

#### 배포 & 검증 (15:23 UTC / 00:23 KST)
- dashboard(uvicorn) 서비스 중지 (토큰 경쟁 방지)
- 봇 재시작 → **US 17종목만 구독 (KR 종목 제거)**
- tick_count: 2,216 (5분 후), unique_tickers: 17 → **정상 수신!**
- fill_check: checks_done=11, pending_orders=0 → 정상

### 15:28 UTC (00:28 KST) - 안정 확인
- tick_count: 2,216 | unique_tickers: 17 | signals: 17
- fill_check: checks_done=11, pending_orders=0
- 가격: AEM=$223.02, CVE=$23.44, GVA=$124.62, ISSC 감시중

### 15:28~21:00 UTC - 장중 안정 운영
- 봇 완벽 안정 작동 (에러 0, 매매 신호 미발동)
- WS 매시간 정상 reconnect (16:00, 17:00, 18:00, 19:00, 20:00, 21:00 UTC)
- 주요 가격 추이 (5분 heartbeat 기준):

| 시간 (UTC) | tick_count | CVE | AEM | GVA | checks_done |
|------------|-----------|------|------|------|-------------|
| 15:28 | 2,216 | $23.44 | $223.02 | $124.62 | 11 |
| 15:38 | 6,460 | $23.57 | $223.95 | $125.27 | 31 |
| 16:03 | 16,822 | $23.58 | $222.15 | $125.04 | 81 |
| 16:33 | 27,976 | $23.55 | $222.03 | $125.12 | 141 |
| 17:03 | 38,457 | $23.53 | $221.51 | $124.42 | 201 |
| 17:53 | 56,311 | $23.20 | $221.31 | $123.75 | 301 |
| 18:33 | 70,322 | $23.15 | $222.58 | $123.24 | 381 |
| 19:13 | 84,336 | $23.24 | $222.86 | $123.30 | 461 |
| 19:53 | 99,547 | $23.17 | $221.81 | $123.17 | 541 |
| 20:23 | 112,690 | $22.995 | $221.06 | $123.41 | 601 |
| 20:53 | 130,231 | $22.78 | $220.70 | $123.35 | 661 |

### 21:00 UTC (06:00 KST) - 장 마감
- 최종 tick_count: 137,365
- CVE 종가: $22.70 (진입가 $23.52 대비 -3.5%, 손절 $22.07 미도달)
- 손절/Donchian exit 미발동

### 21:30 UTC (06:30 KST) - post_market 완료
- intraday_stopped → post_market 정상 실행 (7.08초)
- sync: matched=2 (ISSC, CVE), broker_only=0, db_only=0
- 미체결 주문: 0
- **총 자산: $79,777.78** (시작 $100,000 대비 -20.2%)
- **일일 P&L: -$3,475.65**
- 포지션: 5개 (US 2 + KR 3)
- EGW00201 rate limit 경고 2건 (재시도 후 정상 처리)

### 최종 보유 포지션 상태
| Ticker | 시장 | 수량 | 평단가 | 손절가 | 종가 | 일일 수익 | 상태 |
|--------|------|------|--------|--------|------|-----------|------|
| ISSC | US | 1,414 | $25.997 | $24.75 | - | - | 유지 |
| CVE | US | 549 | $23.52 | $22.07 | $22.70 | -$450.18 | 신규 진입, 하락 |
| 031980 | KR | - | - | ₩102,724 | - | - | KR 세션 관리 |
| 290550 | KR | - | - | ₩12,386 | - | - | KR 세션 관리 |
| 218410 | KR | - | - | ₩63,842 | - | - | KR 세션 관리 |

---

## 발견 & 수정된 버그

| # | 심각도 | 설명 | 파일 |
|---|--------|------|------|
| 12a | CRITICAL | odno 제로패딩 불일치 → fill check 매칭 불가 | order_executor.py |
| 12b | MEDIUM | 자정 KST 날짜 불일치 → 조회 범위 오류 | order_executor.py |
| 13 | CRITICAL | KR 포지션이 US WS에 혼합 구독 → 틱 수신 중단 | trading_bot.py, pre_market.py |

## 수정 파일 목록
1. `broker/order_executor.py` — Bug #12a, #12b
2. `bot/trading_bot.py` — Bug #13
3. `bot/pre_market.py` — Bug #13

---

## 감시 총평

### 안정성
- Bug #12, #13 수정 후 (15:23 UTC~) **5시간 37분 연속 무장애 운영**
- WebSocket: 137,365 ticks 수신, 17종목 전량 수신, 매시간 정상 reconnect
- fill_check: 691회 체크, 0건 오류
- post_market: 정상 완료, sync 불일치 0건

### 매매 로직 검증
- **진입**: CVE S1 진입 정상 발동 (Donchian 20일 고가 돌파), 주문/체결 모두 정상
- **손절**: CVE가 종가 $22.70까지 하락했으나 손절선 $22.07 미도달 → 올바르게 미발동
- **피라미딩**: 조건 미충족으로 미발동 (정상)
- **Donchian exit**: 조건 미충족으로 미발동 (정상)
- **시장 필터**: PASS (SPY > SMA200) → 진입 허용 (정상)

### 핵심 교훈
1. **Bug #12 (odno 제로패딩)**: KIS API의 주문번호 포맷이 제출/조회 간 불일치 — 어제 Bug #9의 진짜 근본 원인
2. **Bug #13 (시장 간 혼합 구독)**: KR/US 포지션을 동시에 관리할 때 시장 필터가 필수
3. 두 버그 모두 KR+US 듀얼 마켓 운영 이후 발생한 통합 이슈
