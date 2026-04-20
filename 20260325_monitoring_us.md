# US Market Monitoring Log - 2026-03-25

## 장 전 헬스체크 (08:50~09:00 EDT)

### 봇 서비스 상태
- **snowa-bot.service**: active (running), 4일째 연속 가동 (since 2026-03-20)
- 최근 로그: ERROR/CRITICAL 없음 ✅

### 대시보드 API 검증
| API | 상태 | 비고 |
|-----|------|------|
| GET /api/positions?market=US | ✅ | 4 포지션, donchian_lower_10/20 포함 |
| GET /api/alerts/near-exit?market=US | ✅ | 4 alerts, current_stop_price 포함, 경고 2건 |
| GET /api/pnl?period=daily&market=US | ✅ | 24 data points |
| GET /api/watchlist?market=US | ✅ | 15 ACTIVE 종목 |
| GET /api/journal?market=US | ✅ | 2026-03: 4 trades |
| GET /api/trades?market=US | ✅ | 7 trades |

### CANSLIM 스크리닝 재무데이터 검증
- fundamentals 최신 업데이트: **2026-03-25 12:06:50 UTC** (오늘) ✅
- 스크리닝 결과: 6572종목 → CANSLIM 31통과 → Minervini 15통과 → watchlist 15종목
- watchlist_history 오늘 기록: 3건 (added 2, removed 1)
- NSSC eps_growth: 31.0% (period 매칭 수정 반영됨)
- 대부분 latest_financial_date: 2025-12-31 (최신 Q4 데이터)

### Pre-Market 실행 결과 (08:00 EDT = 12:00 UTC)
- pre_market_started → token OK → price update (15 tickers) → signals computed (14)
- **시장 필터: RED** (SPY 653.18 < SMA200 658.41)
- **신규 진입 차단** (전략 규칙 정상 적용)
- watchlist: 14, positions: 4, gap_down: 0

### 보유 포지션 (4개)
| 종목 | 시스템 | 평균진입가 | 손절가 | N(ATR) | 유닛수 | S1청산가 | S2청산가 |
|------|--------|-----------|--------|--------|--------|---------|---------|
| CVE | S1 | 23.52 | 22.07 | 0.726 | 1 | 22.51 | 21.35 |
| EZPW | S1 | 26.27 | 25.18 | 0.879 | 1 | 25.20 | 24.38 |
| ISSC | S1 | 26.00 | 24.75 | **0.0** | 2 | 26.30 | 24.22 |
| VRT | S1 | 265.17 | 242.78 | 12.394 | 2 | 251.15 | 234.72 |

### 청산 경고
- **ISSC**: 근접도 3.73% (경고)
- **EZPW**: 근접도 3.89% (경고)

### 발견된 이슈
1. **ISSC n_at_entry=0.0** — 포지션 레벨 ATR 미저장 (유닛별 손절은 10% fallback으로 정상)
2. **VRT Unit 1 손절 미상향** — Unit 2 추가 시 Unit 1 current_stop이 237.21→242.78로 올라가야 하나 유지됨 (포지션 레벨 손절은 242.78로 정상)

---

## 매매 로직 코드 검증 결과

| 항목 | 전략 규칙 | 코드 구현 | 결과 |
|------|----------|----------|------|
| 진입 | Donchian 20일 고가 돌파 | `max(highs[-20:])` 비교 | ✅ PASS |
| 포지션 사이징 | (계좌×1%) / min(2N, 가격×10%) | 동일 공식 | ✅ PASS |
| 피라미딩 | 1/2N 간격, 최대 4유닛 | PYRAMID_INTERVAL_N=0.5, MAX_UNITS=4 | ✅ PASS |
| 손절 | max(진입-2N, 진입×0.90) | STOP_LOSS_N=2, STOP_LOSS_MAX_PCT=0.10 | ✅ PASS |
| Donchian 청산 | S1=10일저가, S2=20일저가 | lower_10, lower_20 정확 | ✅ PASS |
| Paper TR_ID | 매수:VTTT1002U, 매도:VTTT1001U | 비대칭 매핑 정상 | ✅ PASS |
| 시장 필터 | SPY > 200MA → 진입 허용 | 3-tier regime (GREEN/YELLOW/RED) | ✅ PASS |

---

## 장중 감시 (09:30~16:00 EDT)

### 09:30 장 개장
- WS 연결 성공, 13개 종목 SUBSCRIBE SUCCESS
- 첫 틱 수신: AROC $37.548 (09:30:05)
- REST polling 시작: 14 tickers, 0 errors
- 잔고: $3,227.36

### 09:30~09:47 (개장 후 17분)
- REST polling: cycle 41, 전부 0 errors ✅
- WS ticks: 294,428개, 15 unique tickers ✅
- 피라미딩 시도: CVE($13K필요), VRT($8.4K필요), EZPW($13.4K필요) → 잔고 부족 정상 스킵
- 손절/청산 트리거: 없음 (모든 포지션 안전 범위)
- 에러: 없음

### 10:00~15:44 (장중 안정 구간)
- REST polling: cycle 22~958, **전부 0 errors** ✅
- WS ticks: 294K → 391K (누적 ~391,280개)
- 피라미딩 시도: CVE, VRT, EZPW → 잔고 부족($3,227)으로 모두 정상 스킵
- 손절 트리거: 없음
- 신규 진입: 없음 (시장 필터 RED, 전략 규칙 정상)
- ERROR/CRITICAL: **없음**

### 15:45 Donchian 청산 윈도우 — ISSC S1 청산 실행! 🔴
```
15:45:03 EDT - donchian_exit_triggered
  ISSC price $26.09 <= 10-day low $26.30 → S1 exit 트리거

15:45:03 EDT - SELL 주문 제출
  TR_ID: VTTT1001U (Paper 매도 정확) ✅
  수량: 1414주 (전량), 가격: $26.02
  SLL_TYPE: "00" ✅
  order_no: 0000034566

15:45:33 EDT - 체결 완료
  filled_price: $26.069
  realized_pnl: +$101.99
  reason: SYSTEM1_EXIT
  position_closed ✅
```
- S1 포지션 → 10일 저가 이탈 시 전량 청산 ✅
- Donchian 청산 윈도우(15:45 EDT) 정확히 실행 ✅

---

## 장 마감 및 Post-Market (16:00~16:30 EDT)

### 16:30 Post-Market 실행
- intraday_monitor_stopped ✅
- ws_stopped ✅
- sync: 3 matched (US 포지션 CVE, EZPW, VRT), broker_only: 0, db_only: 0 ✅
- unfilled orders: 0 ✅
- **equity: $83,145.81** / daily_pnl: **-$1,951.10**
- market_filter: false (RED 유지)
- IBD 시장 방향: **RALLY_ATTEMPT** (SPY/QQQ 모두 Correction → Rally Attempt 전환)
- post_market_completed (18.59초) ✅

### KIS API 경고 (비치명적)
- `초당 거래건수를 초과하였습니다` (VTTS3018R, VTTS3007R) — rate limit 경고, 정상 재시도 처리

---

## 종합 결과

### 오늘 장 요약
| 항목 | 값 |
|------|------|
| 장중 에러 | **0건** |
| 손절 트리거 | 0건 |
| Donchian 청산 | **1건** (ISSC S1 청산, +$101.99) |
| 신규 진입 | 0건 (시장 필터 RED) |
| 피라미딩 | 0건 (잔고 부족) |
| 최종 equity | $83,145.81 |
| daily PNL | -$1,951.10 |
| REST cycles | 958+, 0 errors |
| WS ticks | ~400,000+ |
| 포지션 | 3개 (CVE, EZPW, VRT) |

### 매매 로직 검증
- 7개 항목 전부 **PASS** (진입/사이징/피라미딩/손절/Donchian청산/TR_ID/시장필터)
- ISSC Donchian S1 청산이 실제로 정확하게 실행됨

### CANSLIM 스크리닝
- 오늘 재무데이터 갱신 완료 (fundamentals updated_at: 2026-03-25)
- 6572종목 → 31 CANSLIM → 15 Minervini → watchlist 15종목
- 최신 Q4(2025-12-31) 데이터 기반

### 대시보드 기능
- 포지션/청산알림/손익분석/종목일기/매매내역/워치리스트 — 전부 정상

### 발견된 데이터 이슈 (비치명적)
1. ISSC n_at_entry=0.0 — 포지션 레벨 ATR 미저장 (유닛별 손절은 10% fallback으로 정상)
2. VRT Unit 1 current_stop 미상향 — 피라미딩 시 유닛별 손절 동기화 미흡 (포지션 레벨은 정상)
