# KR Market Monitoring - 2026-03-13

## Session Summary
- **Market**: KR (KOSPI/KOSDAQ)
- **Market Filter**: PASS (KOSPI ETF ₩81,540 > SMA200 ₩54,421)
- **Watchlist**: 26 ACTIVE (CANSLIM 36 -> Minervini 26)
- **Positions**: 5 OPEN (9 units)
- **Daily P&L**: +₩296,480
- **Account Equity**: ₩11,799,940
- **Cash**: ₩74,960

## Pre-Market (08:00 KST)
- `kr_pre_market_start` 정상 트리거 (23:00 UTC / 08:00 KST)
- 가격 업데이트: 27종목, 0 new records
- 시그널 생성: 26종목 완료
- 시장 필터: KOSPI ETF(069500) close=₩83,200 > SMA200=₩54,188 -> PASS
- 갭다운 체크: 0건
- 소요시간: 0.58초
- 스크리닝: 3,668 → CANSLIM 36 → Minervini 26

## Imminent/Breakout Alerts (장 오픈 전)
| 종목 | 시그널 | Alert Level | 비고 |
|------|--------|-------------|------|
| 218410 RFHIC | S1 | breakout/imminent | 기존 포지션, 피라미딩 대상 |

## Intraday (09:00 ~ 15:30 KST)
### Market Open
- `kr_intraday_start` 정상 트리거 (09:00:00 KST)
- REST polling 시작 (10초 간격, 26종목)
- 첫 heartbeat: 32,471 ticks, 25 unique tickers (09:00 KST)

### Trading Events
- **신규 진입**: 0건 (현금 부족)
- **피라미딩**: 0건 — RFHIC(218410) 피라미딩 스킵 (cash=₩74,585 < required=₩937,684)
- **손절**: 0건 (모든 포지션 손절가 이상 유지)
- **Donchian 청산**: 0건

### Session Statistics
- 총 틱 수신: 49,462
- REST polling cycles: ~830
- Unique tickers: 28
- Errors: 0 (매매 관련)
- KIS API rate limit warnings: 6건 (EGW00201, retry 정상 처리)

### Closing Prices (주요 종목)
| 종목 | 종가 | 전일대비 |
|------|------|----------|
| 000500 가온미디어 | ₩98,600 | +1.6% |
| 000660 SK하이닉스 | ₩910,000 | -2.2% |
| 010120 LS일렉트릭 | ₩747,000 | +0.9% |
| 036170 에이치엠넥스 | ₩5,480 | +19.4% |
| 084110 휴온스글로벌 | ₩75,300 | +4.4% |
| 218410 RFHIC | ₩84,800 | -2.1% |
| 237690 에스티팜 | ₩160,700 | +2.4% |
| 290550 디케이티 | ₩18,540 | -4.3% |

## Post-Market (16:00 KST)
- `kr_post_market_start` 정상 트리거 (16:00:00 KST / 07:00 UTC)
- `ws_rest_polling_ended` 정상 종료
- **포지션 동기화**: KR matched=4, broker_only=0, db_only=0, 불일치=0건
- **미체결 주문**: 0건
- **Daily Log**: equity=₩11,799,940, daily_pnl=+₩296,480, positions=9(KR+US), market_filter=PASS
- 소요시간: 2.55초

## Dashboard Verification (Final)
| Endpoint | Status | Result |
|----------|--------|--------|
| GET /api/status?market=KR | OK | equity=₩11,799,940, 5 pos, 9 units, filter=PASS |
| GET /api/positions?market=KR | OK | RFHIC, 휴온스글로벌, 에스티팜, 에이치엠넥스, 디케이티 (5 OPEN) |
| GET /api/journal?market=KR | OK | 정상 응답 |
| GET /api/diary?market=KR | OK | 43 entries |
| GET /api/trades?market=KR | OK | 19 total |
| GET /api/alerts/near-entry?market=KR | OK | 26 alerts, 1 breakout, 1 imminent |
| GET /api/alerts/near-exit?market=KR | OK | 5 positions, all safe (0 critical, 0 warning) |
| GET /api/pnl?market=KR | OK | daily data 정상 |
| GET /api/watchlist?market=KR | OK | 26 ACTIVE |

## Positions (End of Day)
| 종목 | System | Shares | Avg Entry | Stop | Units | Unrealized P&L |
|------|--------|--------|-----------|------|-------|----------------|
| 218410 RFHIC | S1 | 11 | ₩80,900 | ₩72,630 | 1 | +5.21% |
| 084110 휴온스글로벌 | S1 | 26 | ₩72,000 | ₩65,790 | 2 | +5.03% |
| 237690 에스티팜 | S1 | 7 | ₩164,400 | ₩147,960 | 1 | -2.25% |
| 036170 에이치엠넥스 | S1 | 649 | ₩3,575 | ₩3,290 | 2 | +53.27% |
| 290550 디케이티 | S1 | 224 | ₩14,353 | ₩13,500 | 3 | +29.17% |

## Bugs Fixed
- 없음 (전체 세션 무장애 운영)

## Conclusion
- 전체 세션 무장애 운영 (09:00~16:00 KST)
- 매매 이벤트 0건 (현금 부족으로 피라미딩 스킵만 발생)
- REST polling ~830 cycles, 49,462 ticks, 에러 0건
- KIS API rate limit 6건 (모두 retry 성공)
- Post-market 동기화 완벽 (불일치 0건)
- 대시보드 KR 탭 9개 엔드포인트 모두 정상 응답
- Daily P&L: +₩296,480 (equity: ₩11,799,940)
