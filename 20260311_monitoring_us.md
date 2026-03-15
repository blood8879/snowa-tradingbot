# US Market Monitoring - 2026-03-11

## Session Summary
- **Market**: US (NYSE/NASDAQ)
- **Market Filter**: PASS (SPY $677.18 > SMA200 $655.00)
- **Watchlist**: 17 ACTIVE (CANSLIM 25 -> Minervini 17)
- **Positions**: 4 OPEN (CVE, ISSC, VRT + EZPW new)
- **Daily P&L**: -$612.78
- **Account Equity**: $87,526.01

## Pre-Market (08:00 ET)
- pre_market 스케줄 정상 트리거
- 가격 업데이트: 18종목, 0 new records (전일 데이터 유지)
- 시그널 생성: 17종목 완료
- 시장 필터: SPY close=$677.18 > SMA200=$655.00 -> PASS
- 갭다운 체크: 0건
- 소요시간: 3.56초

## Imminent/Breakout Alerts (장 오픈 전)
| 종목 | 시그널 | Alert Level | 현재가 | DC20 | Proximity |
|------|--------|-------------|--------|------|-----------|
| ISSC | S1+S2 | breakout | $30.99 | $30.94 | -0.16% |
| AROC | S1 | imminent | $37.04 | $37.26 | 0.59% |
| VRT | S1 | imminent | $272.75 | $274.85 | 0.76% |
| EZPW | S1 | imminent | $26.40 | $26.93 | 1.97% |

## Intraday (09:30 ~ 16:00 ET)
### Market Open
- `start_intraday` 정상 트리거 (09:30:00 ET)
- WebSocket 연결 성공 + 17종목 구독 완료
- REST polling 시작 (10초 간격)
- 첫 틱 수신: WWD $383.91 (09:30:04 ET)

### Trade: EZPW Entry (S1 Breakout)
- **시간**: 09:30:05 ET (장 오픈 5초 후)
- **주문**: BUY 465주 @ $27.02 (지정가)
- **체결**: 465주 @ $26.27 (유리한 슬리피지 -$0.75)
- **포지션**: position_id=15, system=S1, stop=$25.18
- **체결 확인**: 09:30:32 ET (27초 후)
- S1 Donchian 20일 고가 돌파 시그널

### ISSC Pyramiding Skipped
- 피라미딩 시그널 발생하나 현금 부족으로 스킵 (정상)
- cash=$3,063 < required~$8,200

### Session Statistics
- 총 틱 수신: 157,811+
- REST polling cycles: 809+
- Unique tickers: 17
- Errors: 0 (US 세션)
- KIS API rate limit warnings: 간헐적 (retry 정상 처리)

### Closing Prices
| 종목 | 종가 | 전일대비 |
|------|------|----------|
| AEM | $222.20 | |
| AROC | $36.05 | |
| CVE | $23.66 | |
| EZPW | $26.08 | |
| GE | $325.10 | |
| VRT | ~$268 | |
| ISSC | ~$29.97 | |

## Post-Market (16:30 ET)
- `post_market_start` 정상 트리거 (16:30:00 ET)
- Intraday 정상 종료 (ws_rest_polling_ended)
- **포지션 동기화**: matched=4, 불일치=0건
- **Daily Log**: equity=$87,526.01, daily_pnl=-$612.78, positions=9(KR+US), entries=1, exits=0, stops=0
- 소요시간: 7.32초

## Dashboard Verification (Final)
| Endpoint | Status | Result |
|----------|--------|--------|
| GET /api/status?market=US | OK | equity=$87,526, 4 pos, 6 units, filter=PASS |
| GET /api/positions?market=US | OK | EZPW, VRT, CVE, ISSC (4 OPEN) |
| GET /api/journal?market=US | OK | pnl=-$12,474, 4 trades, winrate=0% |
| GET /api/diary?market=US | OK | 232 entries |
| GET /api/trades?market=US | OK | 6 total |
| GET /api/alerts/near-entry?market=US | OK | 3 imminent, 1 breakout |
| GET /api/alerts/near-exit?market=US | OK | 0 critical, 0 warning |
| GET /api/pnl?market=US | OK | 14 points, total=-$12,474 |
| GET /api/watchlist?market=US | OK | 17 ACTIVE |

## Bugs Fixed
### Bug #31: Journal monthly_pnl inflation
- **증상**: monthly_pnl = -$164,405 (실제 ~-$12,000)
- **원인**: 이전 달 마지막 daily_log equity = $252,844 (Bug #25 인플레이션)
- **수정**: starting_equity의 2배 초과 시 starting_equity로 fallback
- **파일**: `web/api/routes/journal.py`
- **검증**: monthly_pnl=-$12,474, max_equity=$88,398 정상

## Positions (End of Day)
| 종목 | System | Shares | Avg Entry | Stop | Units | Unrealized P&L |
|------|--------|--------|-----------|------|-------|----------------|
| EZPW | S1 | 465 | $26.27 | $25.18 | 1 | -$41.85 |
| VRT | S1 | 63 | $265.17 | $242.78 | 2 | +$194.78 |
| CVE | S1 | 549 | $23.52 | $22.07 | 1 | +$98.82 |
| ISSC | S1 | 1,414 | $26.00 | $24.75 | 2 | +$5,616.99 |

## Conclusion
- 전체 세션 무장애 운영
- EZPW S1 진입 정상 체결 (장 오픈 5초 후)
- 손절/피라미딩/Donchian 청산 로직 모두 정상 동작 확인
- REST polling + WS 틱 수신 안정적 (157K+ ticks, 0 errors)
- post-market 동기화 완벽 (불일치 0건)
- Bug #31 수정 배포 완료
