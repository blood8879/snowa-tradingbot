# US Market Monitoring - 2026-03-12

## Session Summary
- **Market**: US (NYSE/NASDAQ/AMEX)
- **Market Filter**: PASS (SPY $666.06 > SMA200 $656.03)
- **Watchlist**: 16 ACTIVE
- **Positions**: 4 OPEN (6 units)
- **Daily P&L**: -$3,156.62
- **Account Equity**: $84,369.39
- **Cash**: $3,129.63

## Pre-Market (08:00 ET)
- pre_market 스케줄 정상 트리거
- 시장 필터: SPY close=$676.33 > SMA200=$655.49 -> PASS
- 워치리스트: 16종목 ACTIVE
- 포지션: 4 OPEN (6 units)
- 갭다운 체크: 0건

## Imminent/Breakout Alerts (장 오픈 전)
| 종목 | 시그널 | Alert Level | 비고 |
|------|--------|-------------|------|
| CVE | S1 | breakout | 기존 포지션, 피라미딩 대상 |
| UGP | S1 | imminent | |
| EZPW | S1 | close | 기존 포지션 |
| AROC | S1 | close | |
| ISSC | S1 | close | 기존 포지션 |

## Intraday (09:30 ~ 16:00 ET)
### Market Open
- `us_intraday_start` 정상 트리거 (09:30:00 ET)
- WebSocket 연결 성공 (`ws://ops.koreainvestment.com:31000/tryitout`)
- 16종목 WS 구독 완료 (DNYS/DNAS prefix)
- REST polling 시작 (10초 간격, 16종목)
- 첫 heartbeat: 170,844 ticks, 17 unique tickers

### Trading Events
- **신규 진입**: 0건 (현금 부족)
- **피라미딩**: 0건 — CVE/ISSC 피라미딩 시그널 반복 발생, 현금 부족으로 스킵
  - CVE: cash=$3,129.63 < required=$12,586~$12,639
  - ISSC: cash=$3,129.63 < required=$8,226~$8,253
- **손절**: 0건 (모든 포지션 손절가 이상 유지)
- **Donchian 청산**: 0건

### Session Statistics
- 총 틱 수신: 351,966
- REST polling cycles: 937
- Unique tickers: 18
- Errors: 0 (매매 관련)
- KIS API rate limit warnings: 210건 누적 (EGW00201, retry 정상 처리)

### Closing Prices (주요 종목)
| 종목 | 종가 | 전일대비 |
|------|------|----------|
| AEM | $217.78 | |
| AROC | $35.07 | |
| CVE | $23.65 | |
| EZPW | $26.68 | |
| GE | $306.01 | |
| ISSC | $27.93 | |
| VRT | $265.38 | |

## Post-Market (16:30 ET)
- `post_market_start` 정상 트리거 (16:30:00 ET / 20:30:00 UTC)
- `ws_rest_polling_ended` 정상 종료
- **포지션 동기화**: US matched=4, broker_only=0, db_only=0, 불일치=0건
- **미체결 주문**: 0건
- **Daily Log**: equity=$84,369.39, daily_pnl=-$3,156.62, positions=9(KR+US), market_filter=PASS
- 소요시간: 8.08초

## Dashboard Verification (Final)
| Endpoint | Status | Result |
|----------|--------|--------|
| GET /api/status?market=US | OK | equity=$84,369.39, 4 pos, 6 units, filter=PASS |
| GET /api/positions?market=US | OK | EZPW, VRT, CVE, ISSC (4 OPEN) |
| GET /api/journal?market=US | OK | pnl=-$15,630.61, 4 trades (all STOP_LOSS) |
| GET /api/diary?market=US | OK | 233 entries |
| GET /api/trades?market=US | OK | 7 total, 18 broker |
| GET /api/alerts/near-entry?market=US | OK | 16 alerts, 1 imminent (CVE) |
| GET /api/alerts/near-exit?market=US | OK | 4 positions, all safe |
| GET /api/pnl?market=US | OK | daily data 정상 |
| GET /api/watchlist?market=US | OK | 16 ACTIVE |

## Positions (End of Day)
| 종목 | System | Shares | Avg Entry | Stop | Units | Unrealized P&L |
|------|--------|--------|-----------|------|-------|----------------|
| EZPW | S1 | 465 | $26.27 | $25.18 | 1 | -1.18% |
| VRT | S1 | 63 | $265.17 | $242.78 | 2 | +0.08% |
| CVE | S1 | 549 | $23.52 | $22.07 | 1 | +0.34% |
| ISSC | S1 | 1,414 | $26.00 | $24.75 | 2 | +7.43% |

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
- 매매 이벤트 0건 (현금 부족으로 피라미딩 스킵만 발생)
- REST polling 937 cycles, 351,966 ticks, 에러 0건
- WebSocket 정상 동작 (16종목 구독, 18 unique tickers 수신)
- Post-market 동기화 완벽 (불일치 0건)
- 대시보드 US 탭 9개 엔드포인트 모두 정상 응답
- Daily P&L: -$3,156.62 (equity: $84,369.39)
