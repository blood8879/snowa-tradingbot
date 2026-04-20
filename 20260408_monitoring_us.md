# 2026-04-08 US 장 감시 로그

## 장 시간
- 미국 서머타임 적용: 22:30~05:00 KST (09:30~16:00 ET)

## 시장 상태
- **레짐**: YELLOW (SPY $675.10 > SMA200 $661.30, breadth 45.4%, ROC +1.19%)
- SMA 통과, breadth 55% 미달 → YELLOW
- 새 레짐 로직 적용됨 (200 SMA 단독 RED 폐지, breadth+ROC 모두 나쁠 때만 RED)

## CANSLIM 스크리닝
- 20:00 KST 실행 완료 (11:00~11:54 UTC, 약 55분)
- 유니버스: 6,580종목
- 가격 갱신: 6,542건
- Earnings Calendar: 19종목
- **Stale targets**: 6,527건 → 500건으로 cap (경고)
- 재무 갱신: 519종목, 4,722건 레코드
- CANSLIM 통과: 31종목
- Minervini 통과: 13종목
- **최종 watchlist**: 13종목

## Watchlist 변동 (4/8)
- **탈락**: JCI (Minervini 추세 템플릿 미통과), AMD (Minervini 미통과)
- **유지**: CVE, VIST, HG, AROC, BTSG, SBS, VRT, EZPW, AGX, KEX, EIX, GCT, WWD

## 매매 이벤트
### 신규 진입
- **WWD**: BUY 11주 @ $395.225 (S1 돌파, 주문가 $397.22 → 체결 $395.225)
  - 손절가: $367.48 (ATR=14.27, 2N 룰)
  - 포지션 크기: 계좌 대비 6.46%

### 피라미딩 주문
- **CVE**: BUY 453주 @ $24.76 (unit 2 피라미딩)
  - 현재가 ~$24.90, 지정가 미도달 → **미체결 유지**

## 포지션 현황 (22:45 KST 기준)
| 종목 | 주수 | 평균단가 | 손절가 | 미실현P&L |
|------|------|---------|--------|----------|
| CVE | 549 | $23.52 | $22.07 | +5.87% |
| AGX | 6 | $578.93 | $531.00 | +4.45% |
| AMD | 18 | $221.94 | $200.42 | +4.43% |
| EZPW | 225 | $27.35 | $25.65 | +3.37% |
| AZN | 41 | $204.39 | $194.81 | +1.10% |
| KEX | 147 | $139.36 | $132.16 | +0.46% |
| HG | 241 | $30.57 | $28.93 | -0.02% |
| WWD | 11 | $395.23 | $367.48 | -1.03% |

- 계좌 총 자산: $68,914
- 현금: $253 (거의 풀 투자)

## 알림 현황
### 청산 근접 (near-exit)
- **CVE**: exit_proximity 0.84% — **critical** (Donchian 10일 하단 $24.69 근접)

### 진입 근접 (near-entry)
- **EZPW**: S1+S2 **breakout** (Donchian 20일/55일 상단 돌파)
- **BTSG**: S1 **imminent** (proximity 0.16%)

## 버그 수정
### Bug #34: REST polling 초당 거래건수 초과
- **증상**: REST polling(15종목 × 1초 간격) + fill check + balance 조회 동시 실행 → KIS API rate limit 초과
- **영향**: `filled_query_failed` 반복 → 체결 확인 지연
- **수정**: `kis_websocket.py` REST polling 종목간 간격 1초→2초
- **결과**: 재시작 후 `filled_query_failed` 0건, `초당 거래건수` 에러 0건
- **파일**: `broker/kis_websocket.py` line 543

## 대시보드 API 확인
- [x] /api/status — 정상 (레짐, 포지션 수, 계좌 정보)
- [x] /api/positions — 정상 (8개 포지션, PnL, 손절가)
- [x] /api/watchlist — 정상 (13종목, 최신 스크리닝)
- [x] /api/watchlist/history — 정상 (추가/탈락 기록)
- [x] /api/alerts/near-exit — 정상 (CVE critical)
- [x] /api/alerts/near-entry — 정상 (EZPW breakout, BTSG imminent)
- [x] /api/diary — 정상 (매매 기록)

## Bug #35: 미체결 주문 예약금 equity 누락
- **증상**: 손익분석 페이지에서 오늘 -$11,478 손실 표시 (실제 손실 없음)
- **원인**: `get_purchasable_amount()`가 반환하는 cash는 미체결 주문 예약금이 차감된 값. equity = cash + positions_value에서 미체결 주문 금액이 빠짐
- **CVE 예**: 453주 × $24.76 = $11,216 예약 → cash에서 차감되었으나 position에 미포함 → equity $11,216 허위 감소
- **수정**: `account.py` `_get_account_info_us()`에서 SUBMITTED BUY 주문의 `SUM(requested_shares * requested_price)`를 equity에 추가
- **결과**: equity $68,914 → $80,370 (전일 $80,597과 일치)
- **파일**: `broker/account.py`

## 주의사항
- **VIST**: Q4 2025 재무데이터 누락 → FY2025 연간보고서 미공시 (아르헨티나 기업, 4월 중 발표 예정). 정상.
- **현금 부족**: $253 → 피라미딩/신규 진입 불가 (BTSG, SBS, VRT 등 entry_skipped)
- CVE 피라미딩 주문 미체결 유지 중 (지정가 $24.76 < 현재가 ~$24.90)

## 23:10 KST 업데이트
- Rate limiting 수정 후 filled_query_failed 0건 유지
- 포지션 안정적: 손절 근접 종목 없음 (최소 거리 5%)
- Equity 수정 완료: $80,370 (정상)
- REST polling cycle 모두 errors=0

## 00:30 KST 업데이트
- CVE 피라미딩 주문(#306): 2시간 경과 → 자동 만료 (지정가 $24.76 미도달)
- 8 포지션 유지, 청산/손절 없음
- fill check 167회 성공
- Equity: $80,174 → $80,284 → $80,192 (안정)
- KEX 손절 거리 4.5% (NEAR 레벨)

## Bug #36: 미체결 주문 만료 시 broker 취소 미전송
- **증상**: 주문 만료 시 DB에서 FAILED로 변경하지만 KIS broker에 취소 요청 미전송 → broker 측 예약금 미환불
- **수정**: `order_executor.py` 만료 로직에 `cancel_order()` 호출 추가, 상태를 FAILED→CANCELLED로 변경
- **파일**: `broker/order_executor.py`

## 장중 모니터링 요약 (22:30 ~ 01:56 KST)
- fill check: 총 81+ 회 연속 성공 (재시작 후 filled_query_failed 0건)
- REST polling: 93+ 사이클 errors=0
- 포지션 변동: 없음 (8개 포지션 유지, 청산/손절 0건)
- CVE 피라미딩 #306: 2시간 후 자동 만료 (15:30 UTC)
- Equity 추이: $80,370 → $80,364 → $80,284 → $80,192 → $69,076~$69,187 (pending 제거 후)

## 수정된 버그 총 3건
| # | 내용 | 파일 |
|---|------|------|
| 34 | REST polling 초당 거래건수 초과 (1초→2초) | broker/kis_websocket.py |
| 35 | 미체결 주문 예약금 equity 누락 | broker/account.py |
| 36 | 미체결 주문 만료 시 broker 취소 미전송 | broker/order_executor.py |

## 장 마감 — post_market 결과 (05:30 KST)
- **equity**: $69,419
- **daily_pnl**: -$11,178 (허위 — CVE 미체결 주문 예약금 미환불로 인한 차이)
- **sync**: 8 포지션 매칭 성공, 불일치 0건
- **IBD Market Direction**: SPY/QQQ 모두 CONFIRMED_UPTREND
- **cancelled orders**: 0
- 장 전체 동안 청산/손절 **0건**, fill check **481회** 연속 성공

## 추가 확인 필요
- post_market의 daily_log equity 기록이 pending order 예약금을 반영하지 않아 daily_pnl이 부정확
- Bug #35 수정은 대시보드 API에만 적용됨 → post_market 경로도 동일하게 수정 필요

## 감시 완료
