# KR Market Monitoring - 2026-03-12

## Session Summary
- **Market**: KR (KOSPI/KOSDAQ)
- **Market Filter**: PASS (KOSPI ETF ₩83,200 > SMA200 ₩54,188)
- **Watchlist**: 25 ACTIVE (CANSLIM 35 -> Minervini 25)
- **Positions**: 5 OPEN (9 units)
- **Daily P&L**: +₩295,120
- **Account Equity**: ₩11,503,460

## Pre-Market (08:00 KST)
- pre_market 스케줄 정상 트리거
- 가격 업데이트: 26종목, 0 new records (전일 데이터 유지)
- 시그널 생성: 25종목 완료
- 시장 필터: KOSPI ETF(069500) close=₩83,825 > SMA200=₩53,946 -> PASS
- 갭다운 체크: 0건
- 소요시간: 0.56초

## Imminent/Breakout Alerts (장 오픈 전)
| 종목 | 시그널 | Alert Level | 비고 |
|------|--------|-------------|------|
| 218410 RFHIC | S1 | breakout | 기존 포지션, 피라미딩 대상 |
| 290550 디케이티 | S1 | breakout | 기존 포지션, 피라미딩 대상 |
| 084110 휴온스글로벌 | S1 | imminent (0.85%) | 기존 포지션 |
| 036170 에이치엠넥스 | S1 | imminent (1.11%) | 기존 포지션 |

## Intraday (09:00 ~ 15:30 KST)
### Market Open
- `kr_intraday_start` 정상 트리거 (09:00:00 KST)
- REST polling 시작 (10초 간격, 25종목)
- 첫 heartbeat: 15,661 ticks, 20 unique tickers (09:00:00 KST)
- Cycle 1: ok=25, errors=0

### Trading Events
- **신규 진입**: 0건 (현금 부족)
- **피라미딩**: 0건 — RFHIC 피라미딩 시그널 반복 발생, 현금 부족으로 스킵 (cash=₩72,882, required=₩880K~₩961K)
- **손절**: 0건 (모든 포지션 손절가 이상 유지)
- **Donchian 청산**: 0건

### Session Statistics
- 총 틱 수신: 32,375
- REST polling cycles: 672
- Unique tickers: 25
- Errors: 0 (매매 관련)
- KIS API rate limit warnings: 15건 (EGW00201 "초당 거래건수 초과", retry 정상 처리)

### Closing Prices (주요 종목)
| 종목 | 종가 | 전일대비 |
|------|------|----------|
| 000500 가온미디어 | ₩97,000 | |
| 000660 SK하이닉스 | ₩930,000 | |
| 010120 LS일렉트릭 | ₩740,000 | |
| 012450 한화에어로스페이스 | ₩1,465,000 | |
| 036170 에이치엠넥스 | ₩4,590 | |
| 084110 휴온스글로벌 | ₩72,100 | |
| 218410 RFHIC | ₩86,600 | |
| 237690 에스티팜 | ₩157,000 | |
| 290550 디케이티 | ₩19,370 | |

## Post-Market (16:00 KST)
- `kr_post_market_start` 정상 트리거 (16:00:00 KST)
- Intraday 정상 종료 (`ws_rest_polling_ended`)
- **포지션 동기화**: KR matched=4, broker_only=0, db_only=0, 불일치=0건
- **미체결 주문**: 0건
- **Daily Log**: equity=₩11,503,460, daily_pnl=+₩295,120, positions=9(KR+US), market_filter=PASS
- 소요시간: 2.75초

## Dashboard Verification (Final)
| Endpoint | Status | Result |
|----------|--------|--------|
| GET /api/status?market=KR | OK | equity=₩11,503,460, 5 pos, 9 units, filter=PASS |
| GET /api/positions?market=KR | OK | RFHIC, 휴온스글로벌, 에스티팜, 에이치엠넥스, 디케이티 (5 OPEN) |
| GET /api/journal?market=KR | OK | pnl=₩1,503,460, 2 trades |
| GET /api/diary?market=KR | OK | 43 entries |
| GET /api/trades?market=KR | OK | 19 total |
| GET /api/alerts/near-entry?market=KR | OK | 25 alerts, 1 breakout (에이치엠넥스) |
| GET /api/alerts/near-exit?market=KR | OK | 5 positions, all safe |
| GET /api/pnl?market=KR | OK | daily data 정상 |
| GET /api/watchlist?market=KR | OK | 25 ACTIVE |

## Positions (End of Day)
| 종목 | System | Shares | Avg Entry | Stop | Units | Unrealized P&L |
|------|--------|--------|-----------|------|-------|----------------|
| 218410 RFHIC | S1 | 11 | ₩80,900 | ₩72,630 | 1 | +4.34% |
| 084110 휴온스글로벌 | S1 | 26 | ₩72,000 | ₩65,790 | 2 | +4.61% |
| 237690 에스티팜 | S1 | 7 | ₩164,400 | ₩147,960 | 1 | -4.26% |
| 036170 에이치엠넥스 | S1 | 649 | ₩3,575 | ₩3,290 | 2 | +45.44% |
| 290550 디케이티 | S1 | 224 | ₩14,353 | ₩13,500 | 3 | +26.80% |

## Bugs Fixed
- 없음 (전체 세션 무장애 운영)

## Conclusion
- 전체 세션 무장애 운영 (09:00~16:00 KST)
- 매매 이벤트 0건 (현금 부족으로 피라미딩 스킵만 발생)
- REST polling 672 cycles, 32,375 ticks, 에러 0건
- KIS API rate limit 15건 (모두 retry 성공)
- Post-market 동기화 완벽 (불일치 0건)
- 대시보드 KR 탭 9개 엔드포인트 모두 정상 응답
- Daily P&L: +₩295,120 (equity: ₩11,503,460)
