# US Market Monitoring - 2026-03-13

## Session Summary
- **Market**: US (NYSE/NASDAQ/AMEX)
- **Market Filter**: PASS (SPY $662.29 > SMA200 $656.41)
- **Watchlist**: 13 ACTIVE
- **Positions**: 4 OPEN (6 units)
- **Daily P&L**: -$884.30
- **Account Equity**: $83,485.09
- **Cash**: $3,227.36

## Pre-Market (08:00 ET)
- pre_market 스케줄 정상 트리거
- 시장 필터: SPY close=$666.06 > SMA200=$655.95 -> PASS
- 스크리닝: 6,600 → CANSLIM 26 → Minervini 13
- 워치리스트: 13종목 ACTIVE
- 포지션: 4 OPEN (6 units)
- 갭다운 체크: 0건

## Imminent/Breakout Alerts (장 오픈 전)
| 종목 | 시그널 | Alert Level | 비고 |
|------|--------|-------------|------|
| ISSC | S1 | breakout | 기존 포지션, 피라미딩 대상 |

## Intraday (09:30 ~ 16:00 ET)
### Market Open
- `us_intraday_start` 정상 트리거 (09:30:00 ET)
- WebSocket 연결 성공
- 13종목 WS 구독 완료
- REST polling 시작 (10초 간격, 13종목)

### Trading Events
- **신규 진입**: 0건 (현금 부족)
- **피라미딩**: 0건
- **손절**: 0건 (모든 포지션 손절가 이상 유지)
- **Donchian 청산**: 0건

### Session Statistics
- 총 틱 수신: 459,683
- REST polling cycles: ~905
- Unique tickers: 19
- Errors: 0 (매매 관련)
- KIS API rate limit warnings: 4건 (초당 거래건수 초과, retry 정상 처리)

### Closing Prices (주요 종목)
| 종목 | 종가 | 전일대비 |
|------|------|----------|
| AEM | $207.13 | -4.9% |
| AROC | $34.61 | -1.3% |
| CVE | $23.20 | -1.9% |
| EZPW | $25.87 | -3.0% |
| GE | $306.78 | +0.3% |
| ISSC | $27.71 | -0.8% |
| VRT | $258.88 | -2.4% |

## Post-Market (16:30 ET)
- `post_market_start` 정상 트리거 (16:30:00 ET / 20:30:00 UTC)
- `ws_rest_polling_ended` 정상 종료
- **포지션 동기화**: US matched=4, broker_only=0, db_only=0, 불일치=0건
- **미체결 주문**: 0건
- **Daily Log**: equity=$83,485.09, daily_pnl=-$884.30, positions=9(KR+US), market_filter=PASS
- 소요시간: 6.96초

## Dashboard Verification (Final)
| Endpoint | Status | Result |
|----------|--------|--------|
| GET /api/status?market=US | OK | equity=$83,485.09, 4 pos, 6 units, filter=PASS |
| GET /api/positions?market=US | OK | EZPW, VRT, CVE, ISSC (4 OPEN) |
| GET /api/journal?market=US | OK | pnl=-$16,514.91, 4 trades (all STOP_LOSS) |
| GET /api/diary?market=US | OK | 50 entries |
| GET /api/trades?market=US | OK | 7 total, 18 broker |
| GET /api/alerts/near-entry?market=US | OK | 13 alerts |
| GET /api/alerts/near-exit?market=US | OK | 4 positions, 0 critical, 1 warning (CVE) |
| GET /api/pnl?market=US | OK | daily data 정상 |
| GET /api/watchlist?market=US | OK | 13 ACTIVE |

## Positions (End of Day)
| 종목 | System | Shares | Avg Entry | Stop | Units | Unrealized P&L |
|------|--------|--------|-----------|------|-------|----------------|
| EZPW | S1 | 465 | $26.27 | $25.18 | 1 | -1.52% |
| VRT | S1 | 63 | $265.17 | $242.78 | 2 | -2.37% |
| CVE | S1 | 549 | $23.52 | $22.07 | 1 | -1.36% |
| ISSC | S1 | 1,414 | $26.00 | $24.75 | 2 | +6.59% |

## Journal Summary (2026-03)
| 종목 | 청산사유 | 실현 P&L | 진입가 | 청산가 |
|------|----------|----------|--------|--------|
| UGP | STOP_LOSS | -$2,089.56 | $5.41 | $4.88 |
| TSM | STOP_LOSS | -$7,809.82 | $386.79 | $353.13 |
| GVA | STOP_LOSS | -$2,317.55 | $136.79 | $129.91 |
| AEM | STOP_LOSS | -$6,214.42 | $239.04 | $219.12 |

## Bugs Fixed
- 없음 (전체 세션 무장애 운영)

## Conclusion
- 전체 세션 무장애 운영 (09:30~16:30 ET)
- 매매 이벤트 0건 (현금 부족)
- REST polling ~905 cycles, 459,683 ticks, 매매 에러 0건
- WebSocket 정상 동작 (13종목 구독, 19 unique tickers 수신)
- KIS API rate limit 4건 (모두 retry 성공)
- Post-market 동기화 완벽 (불일치 0건)
- 대시보드 US 탭 9개 엔드포인트 모두 정상 응답
- Daily P&L: -$884.30 (equity: $83,485.09)
