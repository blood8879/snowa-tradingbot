# 2026-03-05 미국 장 봇 감시 로그

## 감시 개요
- 감시 기간: 22:00 ~ 04:30 KST (미국 장 23:30 개장)
- 대상: Snowa Trading Bot (Paper 모의투자)
- 전략: CANSLIM x Turtle Trading Hybrid
- 보유 포지션: AEM, GVA, ISSC, TSM, UGP (5종목)

## 오늘 수정된 버그 (장전 수정)
1. Bug#1: precomputed_signals 없는 포지션 손절 불가 → 수정 완료
2. Bug#2: 손절 쿨다운 중 Donchian exit 차단 → 수정 완료
3. Bug#3: SELL 주문 auto-expire 2h→30m 단축 → 수정 완료
4. Bug#4: exit_sell 재시도 없음 → 2회 재시도 추가
5. Bug#5: REST 폴백 간격 30s→10s 단축
6. sync_positions ATR 미적용 → ATR 기반 손절가 재계산 완료

## ATR 기반 손절가 (수정 후)
| Ticker | 평단가 | 손절가 | ATR(N) | 손절폭 |
|--------|--------|--------|--------|--------|
| AEM | 239.04 | 220.32 | 9.36 | 7.8% |
| GVA | 136.79 | 130.62 | 3.08 | 4.5% |
| ISSC | 24.99 | 22.49 | 1.52 | 10% cap |
| TSM | 386.79 | 361.49 | 12.65 | 6.5% |
| UGP | 5.41 | 5.13 | 0.14 | 5.1% |

## 감시 타임라인

### 22:00 - 장전 준비 체크
- [x] 봇 서비스 active (running)
- [x] pre_market 실행 확인 (22:00 KST, 이전 인스턴스에서 실행)
  - watchlist: 19종목, positions: 5, signals: 19개 계산 완료
  - Market filter: PASS (SPY 680.62 > SMA200 653.12)
  - Gap-down 위험: GVA (close 132.16, stop 130.62), TSM (close 356.94 < stop 361.49), UGP (close 4.91 < stop 5.13)
- [ ] WebSocket 연결 확인 (23:30 장 오픈 시)
- [ ] 시그널 계산 확인 (23:30 자동 재실행 예정)

### 22:08 - Bug#7 발견 & 수정: PriceCache 생성자 오류
- **문제**: sync_positions에서 `PriceCache(self._rest, self._db)` → PriceCache는 `db`만 받음
- **영향**: sync_positions 실패 → 브로커 전용 포지션 동기화 불가
- **수정**: `PriceCache(self._db)`로 변경, 서버 배포
- 재시작 후 `sync_positions_ok` (US matched=5) 확인 완료

### 22:08~22:27 - 토큰 rate limit 이슈
- 원인: `/tmp/fix_stops.py` 고아 프로세스(PID 139064)가 토큰 점유
- 조치: 프로세스 kill 후 봇 재시작
- 22:27 KST: 토큰 획득 성공, 봇 정상 가동

### 22:28 - 장전 상태 확인
- 봇 running (PID 139840 → 재시작 후 새 PID)
- sync_positions: US 5매칭, KR 0매칭 (정상)
- pre_market: 현재 인스턴스에서 미실행 (23:30 start_intraday 시 자동 복구 예정)
- **손절 대상**: TSM (356.94 < stop 361.49), UGP (4.91 < stop 5.13)

### 22:34 - Bug#8 발견: DST 하드코딩
- `bot/intraday_monitor.py:800` — `timezone(timedelta(hours=-5))` = EST 고정
- 3/8 DST 전환 후 Donchian exit 시간이 1시간 지연됨
- **수정**: `ZoneInfo("America/New_York")` (DST 자동 처리)
- 오늘은 DST 전이라 영향 없음

### 22:45~23:03 - 토큰 rate limit 무한 루프
- **원인**: uvicorn 웹 API(web.api.main)도 KISAuth 토큰 발급 → 봇과 경쟁
- 동시에 2개의 uvicorn + 1개의 봇이 동일 appkey로 토큰 요청 → 영구 rate limit
- **조치**: uvicorn 전부 kill → 봇 정지 → 3분 대기(rate limit 해제) → 봇 시작
- 23:03 KST: 토큰 획득 성공, sync_positions OK

---

### 23:30 - 장 오픈
- [x] start_intraday 실행 확인
- [x] precomputed_signals 자동 복구 확인 ("precomputed_signals 비어있음 → pre_market 실행")
  - 19종목 signals, Market filter PASS (SPY 682.11 > SMA200 653.59)
- [x] WebSocket 연결 & 틱 수신 확인 (19종목 SUBSCRIBE SUCCESS)
- [x] TSM 손절 발동 (23:30:06) — 가격 $354.90 < 손절 $361.49
  - SELL 232주 @ $353.13, 주문번호 0000034832
- [x] UGP 손절 발동 (23:30:09) — 가격 $4.90 < 손절 $5.13
  - SELL 3,965주 @ $4.88, 주문번호 0000034865
- [x] GVA 손절 발동 (23:39:33) — 가격 $130.56 < 손절 $130.62
  - SELL 337주 @ $129.91, 주문번호 0000035356

### 23:35 - 장중 상태
- tick_count: 2,397 | unique_tickers: 19 | pending_orders: 3
- 현금: $0 → 신규 진입/피라미딩 모두 현금 부족으로 skip (정상)
  - WT, AROC 진입 시도 → insufficient_cash
  - ISSC 피라미딩 시도 → insufficient_cash
- 남은 보유 포지션: AEM, ISSC (GVA, TSM, UGP 손절 주문 제출)

### 23:45~23:57 - Bug#9 발견: 매도 주문 체결 미감지 → 무한 재시도 루프

#### 현상
- TSM, UGP 매도 주문(23:30 제출)이 15분 후 `stale_order_expired_broker_confirmed`로 만료
- 이후 손절 재발동 → `40240000: 모의투자 잔고내역이 없습니다` 에러로 3회 재시도 실패
- 120초 쿨다운 후 다시 손절 트리거 → 같은 에러 → **무한 루프**
- GVA도 같은 패턴 (pending_orders: 1로 남아있다가 결국 expire)

#### 원인 분석
1. **체결 감지 실패**: `get_filled_orders` API가 3개 거래소를 순회하며 `EGW00201` (초당 거래건수 초과) rate limit에 걸림
2. **주문은 실제 체결됨**: KIS 브로커에서 TSM/UGP/GVA 매도 정상 체결 → 잔고 삭제
3. **로컬 포지션 미정리**: fill check 실패로 로컬 DB에 포지션 잔존
4. **재시도 에러**: `40240000` = "잔고 없음" = 이미 팔린 종목을 또 매도 시도

#### 수정 (Bug#9)
- **order_executor.py**: `40240000` 에러 감지 시 즉시 재시도 중단, `NO_BROKER_BALANCE` 플래그
- **intraday_monitor.py**: `NO_BROKER_BALANCE` 시 로컬 포지션 강제 청산 (`STOP_LOSS_BROKER_CONFIRMED`)
- **execute_exit_sell에도 동일 보호** 적용
- 배포 후 봇 재시작 (23:57 KST)

#### 재시작 후 상태
- `sync_positions_reconciled`: US matched=2 (AEM, ISSC), db_only=[TSM, UGP, GVA] → 자동 정리
- **무한 루프 완전 해소**, pending_orders=0, 에러 없음
- 남은 포지션: AEM, ISSC (2종목)
- 현금: $0 → 진입/피라미딩 불가 (정상)

---

### 00:00~ - 장중 모니터링 (재시작 후)
- 틱 정상 수신 (19종목 구독)
- AEM, ISSC 포지션 유지 중 (손절 미발동)

### 01:24 KST (16:23 UTC) - AEM 손절 발동
- AEM 가격 $220.22 < 손절가 $220.32 → 손절 트리거
- SELL 312주 @ $219.12, 주문번호 0000038203
- 1회 시도 성공

### 01:24 KST (16:24 UTC) - ISSC 피라미딩 (Unit 2)
- AEM 매도로 현금 확보 ($58,935.71)
- ISSC BUY 562주 @ $27.58, 주문번호 0000038211
- 신규 손절가: $24.75

### 01:28~01:39 KST - Bug#10: get_filled_orders API hang → 봇 이벤트 루프 차단

#### 현상
- fill_check_heartbeat (16:28:36 UTC) 이후 로그 출력 완전 중단
- tick_count 증가 안 함, 틱 수신 불가, 손절 체크 불가
- 봇 프로세스는 sleeping 상태 (crash 아님)
- 재시작해도 pending_orders=2 상태에서 동일하게 hang

#### 원인 분석
1. `aiohttp.ClientSession()` 생성 시 **timeout 미설정** → API 무한 대기 가능
2. `_fill_check_loop`에서 `check_order_fills()` 호출 시 timeout 미적용
3. `get_filled_orders`가 3개 거래소 순차 호출 → 하나라도 hang되면 전체 차단
4. asyncio 이벤트 루프가 fill_check에서 블록 → WS 틱 수신/처리도 중단

#### 수정 (Bug#10)
- **kis_rest.py**: `aiohttp.ClientSession(timeout=ClientTimeout(total=30, connect=10))`
- **trading_bot.py**: `asyncio.wait_for(check_order_fills(), timeout=60)` (US/KR 양쪽)
- **DB 수동 조치**: stale 주문 2개 (AEM SELL #249, ISSC BUY #250) → FILLED로 마킹
- 배포 후 봇 재시작 (01:39 KST)

#### 재시작 후 상태 (01:45 KST)
- tick_count: 2,149 (19종목 정상 수신)
- checks_done: 11 (fill_check 30초마다 정상 동작, hang 없음)
- pending_orders: 0
- 보유 포지션: ISSC (1종목, unit 2 피라미딩 완료)
- AEM: sync_positions에서 db_only로 감지 → 자동 CLOSED

### 01:45 - ISSC 손절가 수동 수정
- sync_positions가 피라미딩 유닛 생성 시 기존 손절가($22.49)를 복사
- 피라미딩 시 설정된 new_stop=$24.75가 반영 안 됨
- DB 수동 수정: positions + units 모두 current_stop_price → $24.75

### 01:45~ - 장중 모니터링 (Bug#10 수정 후)
- 봇 정상 가동 중
- ISSC 1,414주 보유 (Unit1: 852주@$24.99, Unit2: 562주@$27.53), 손절가 $24.75
- tick 정상 수신 (5분당 ~2,100 틱, 19종목)
- fill_check 30초마다 정상, pending_orders=0, 에러/timeout 없음

### 04:29 KST (19:29 UTC) - 감시 마감
- 봇 안정 가동 중 (Bug#10 수정 이후 약 3시간 무장애)
- tick_count: 76,612 | unique_tickers: 19 | checks_done: 331
- pending_orders: 0, 에러/timeout/stop_loss 없음
- ISSC 포지션 유지 중 (손절 미트리거, 가격 > $24.75)
- Donchian exit 체크(15:45~16:00 ET)는 감시 범위 이후 (20:45 UTC)

---

## 오늘 요약

### 보유 포지션 변동
| 시작 | 종료 | 이벤트 |
|------|------|--------|
| AEM 312주 | CLOSED | 손절 ($220.22 < $220.32) @ 01:24 KST |
| GVA 337주 | CLOSED | 손절 ($130.56 < $130.62) @ 23:39 KST |
| TSM 232주 | CLOSED | 손절 ($354.90 < $361.49) @ 23:30 KST |
| UGP 3,965주 | CLOSED | 손절 ($4.90 < $5.13) @ 23:30 KST |
| ISSC 852주 | 1,414주 | 피라미딩 Unit2 +562주 @ $27.58 @ 01:24 KST |

### 발견 & 수정된 버그 (10개)
| # | 심각도 | 설명 | 파일 |
|---|--------|------|------|
| 1 | CRITICAL | precomputed_signals 누락 → 손절 불가 | intraday_monitor.py |
| 2 | MEDIUM | 쿨다운 중 Donchian exit 차단 | intraday_monitor.py |
| 3 | MEDIUM | SELL 주문 auto-expire 2h → 30m | order_executor.py |
| 4 | LOW | exit_sell 재시도 없음 | order_executor.py |
| 5 | LOW | REST 폴백 30s → 10s | constants.py |
| 6 | MEDIUM | sync_positions ATR 미적용 | account.py |
| 7 | LOW | PriceCache 생성자 인수 오류 | account.py |
| 8 | LOW | DST 하드코딩 | intraday_monitor.py |
| 9 | CRITICAL | 매도 체결 미감지 → 무한 재시도 루프 | order_executor.py, intraday_monitor.py |
| 10 | CRITICAL | get_filled_orders hang → 이벤트 루프 차단 | kis_rest.py, trading_bot.py |

### 최종 상태 (04:30 KST 기준)
- 보유: ISSC 1,414주 (손절가 $24.75)
- 현금: $0 (AEM 매도 대금으로 ISSC 피라미딩)
- 봇: 정상 가동 중

---
