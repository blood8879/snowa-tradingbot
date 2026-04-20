# US Market Monitoring Log — 2026-03-24

## 시장 상태
- **IBD Status**: RALLY_ATTEMPT (SPY, QQQ)
- **Market Filter**: RED (SPY 655.38 < SMA200 658.09) → **신규 진입 차단**
- **Regime Scale**: 0.0
- **Trading Mode**: Paper

## 봇 상태 (pre-market 완료 12:00:09 UTC)
- Health: running, error 0건
- Live equity: $87,729.93, Cash: $3,227.36
- Starting equity: $100,000
- Watchlist: 10 ACTIVE US 종목 (pre-market 시점, 스크리닝 후 14종목으로 업데이트)
- Open positions: 4 US

## CANSLIM 스크리닝 파이프라인
- **시작**: 11:00 UTC (20:00 KST)
- **Fundamentals bulk fetch**: 613 tickers
  - 50 → 11:23, 100 → 11:24, 150 → 11:28, 200 → 11:32
  - 250 → 11:36, 300 → 11:40, 350 → 11:44, 400 → 11:48
  - 450 → 11:51, 500 → 11:53, 550 → 11:59
  - Total new records: 4,325, Empty: 94 (30 retried)
  - 600 → 12:03
- **Bulk fetch 완료**: 12:04 UTC, retry 완료 후 스크리닝 시작
- **CANSLIM 스크리닝 완료**: 12:14:05 UTC (20초)
  - Universe: 6,572 → CANSLIM passed: 32 → Minervini passed: 14
- **Watchlist 업데이트**: 14 ACTIVE (어제 10 → +4 신규)
  - 신규: COCO(78), GCT(78), LAUR(76), NSSC(67)
  - 기존유지: CVE(90), ISSC(88), VIST(84), VRT(82), AROC(81), BTSG(79), EIX(78), JCI(76), EZPW(73), SBS(61)
- **파이프라인 총 소요**: 4,453초 (~74분)

## Pre-Market (12:00:00 UTC)
- 소요시간: 9.18초
- Price update: 11 tickers, 0 new records
- Signals computed: 10종목
- Gap-down risk: 0종목
- Market filter: SPY < 200 SMA → false (RED)

## US 포지션 현황 (장전)
| Ticker | Shares | Entry | Stop | Current | PnL% | 비고 |
|--------|--------|-------|------|---------|------|------|
| ISSC | 1,414 | $25.997 | $24.75 | $30.10 | +15.78% | 양호 |
| CVE | 549 | $23.52 | $22.07 | $24.89 | +5.82% | 양호 |
| EZPW | 465 | $26.27 | $25.18 | $25.92 | -1.33% | 주의 |
| VRT | 63 | $265.17 | $242.78 | $257.52 | -2.88% | **10일저가 0.93% 근접** |

## Near-Entry Alerts (장전)
| Ticker | Price | 20일고가 | Proximity | Alert |
|--------|-------|---------|-----------|-------|
| AROC | $36.80 | $37.26 | 1.23% | imminent |
| CVE | $24.91 | $25.39 | 1.89% | imminent |

> 단, market_filter=RED이므로 신규 진입 차단

## Near-Exit Alerts (장전)
| Ticker | Price | 10일저가 | Stop | Proximity | Level |
|--------|-------|---------|------|-----------|-------|
| VRT | $257.52 | $255.13 | $242.78 | 0.93% | **CRITICAL** |
| EZPW | $25.92 | $25.20 | $25.18 | 2.78% | warning |

## 매매 로직 검증
- 진입 (Donchian 20일) ✓
- 청산 (10일 저가, 마감15분전) ✓
- 손절 min(2N,10%) ✓
- 피라미딩 1/2N, max 4유닛 ✓
- 포지션 사이징 (1%리스크)/min(2N,10%) ✓
- Paper TR_ID VTTT1002U/VTTT1001U ✓

## 대시보드 API 검증
- positions ✓ | watchlist ✓ | near-entry ✓ | near-exit ✓
- pnl ✓ | journal ✓ | bot-health ✓ | ibd/status ✓

## 장중 감시 로그
(장 오픈 후 업데이트)

