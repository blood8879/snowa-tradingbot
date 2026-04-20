# KR Market Monitoring - 2026-03-18

## Session Overview
- **Market**: KR (Paper Mode)
- **Date**: 2026-03-18 (Wednesday)
- **Market Open**: KST 09:00
- **Market Close**: KST 15:30
- **Bot Service**: active (running) since KST 05:05

---

## Pre-Session Status (KST 05:48)
- **Equity**: ₩11,420,750
- **Cash**: ₩74,960
- **Positions**: 5 (9 units)
- **Market Filter**: GREEN (PASS)
- **Regime**: GREEN (scale=1.0)
- **Benchmark**: KODEX200 84,635 > SMA200 54,913
- **Breadth**: 56.2%
- **Watchlist**: 18 tickers (last screened 3/17 KST 07:08)

## Open Positions

| Ticker | Name | Shares | Avg Entry | Stop | PnL |
|--------|------|--------|-----------|------|-----|
| 036170 | - | - | - | - | **+51.31%** |
| 290550 | - | - | - | - | **+25.41%** |
| 084110 | 휴온스글로벌 | - | - | - | +0.42% |
| 218410 | RFHIC | 11 | 80,900 | 72,630 | -3.35% |
| 237690 | 에스티팜 | - | 164,400 | - | -6.69% |

## Dashboard API Status (All KR endpoints)
| Endpoint | Status |
|----------|--------|
| /api/status?market=KR | OK |
| /api/positions?market=KR | OK |
| /api/journal?market=KR | OK |
| /api/diary?market=KR | OK |
| /api/trades?market=KR | OK |
| /api/alerts/near-entry?market=KR | OK |
| /api/alerts/near-exit?market=KR | OK |
| /api/pnl?market=KR | OK |
| /api/watchlist?market=KR | OK |
| /api/ibd/status?market=KR | OK (KOSDAQ150 누락 - IBD fix 배포됨, post_market KST 16:00 적용) |

## Schedule

| Time (KST) | Event | Status |
|-------------|-------|--------|
| 07:00 | kr_daily_screening (CANSLIM) | Pending |
| 08:00 | kr_pre_market | Pending |
| 09:00 | kr_market_open | Pending |
| 15:15-15:30 | Donchian 청산 윈도우 | Pending |
| 15:30 | 장 마감 | Pending |
| 16:00 | kr_post_market | Pending |

## Periodic Check Log

| Time (KST) | Check | Result |
|-------------|-------|--------|
| 05:48 | Pre-session | Bot active, 5 positions, GREEN regime |
| 05:48 | Dashboard | 10 endpoints OK, IBD KOSDAQ150 pending fix |
| 05:51 | Position details | 5 positions, 9 units, stops 6-10.2% 정상 |
| 05:52 | Paper orders | ENTRY/PYRAMID/STOP_LOSS 모두 과거 체결 이력 확인 |
| 05:52 | KR code review | REST-only, tick 조정, Donchian KST 15:15-15:30 확인 |

## KR Position Details

| Ticker | Name | Avg Entry | Stop (%) | Units | N | PnL |
|--------|------|-----------|----------|-------|---|-----|
| 036170 | 에이치엠넥스 | ₩3,581 | ₩3,290 (8.1%) | 2 | 241 | **+51.31%** |
| 290550 | 디케이티 | ₩14,355 | ₩13,500 (6.0%) | 3 | 913 | **+25.41%** |
| 084110 | 휴온스글로벌 | ₩72,000 | ₩65,790 (8.6%) | 2 | 4,092 | +0.42% |
| 218410 | RFHIC | ₩80,900 | ₩72,630 (10.2%) | 1 | 5,961 | -3.35% |
| 237690 | 에스티팜 | ₩164,500 | ₩147,960 (10.1%) | 1 | 9,533 | -6.69% |

## Past KR Paper Mode Orders (최근)

| Date | Ticker | Side | Type | Shares | Price | Status |
|------|--------|------|------|--------|-------|--------|
| 3/11 | 084110 | BUY | PYRAMID | 13 | 73,300 | FILLED |
| 3/11 | 218410 | BUY | ENTRY | 11 | 80,900 | FILLED |
| 3/11 | 084110 | BUY | ENTRY | 13 | 70,700 | FILLED |
| 3/11 | 031980 | SELL | STOP_LOSS | 23 | 105,000 | FILLED |
| 3/10 | 290550 | BUY | PYRAMID | 77 | 15,000 | FILLED |
| 3/9 | 218410 | SELL | STOP_LOSS | 36 | 63,400 | FILLED |

---

## Automated Monitoring (Background Checks)

| KST | Task | 목적 |
|-----|------|------|
| ~06:58 | b0dar81f6 | 스크리닝 직전 |
| ~07:05 | bp79rpz95 | KR CANSLIM 스크리닝 결과 |
| ~08:08 | bb2s44pyq | Pre-market 결과 |
| ~09:08 | bdbbytxy0 | Market open + intraday |
| ~15:23 | b7lme9la0 | Donchian 청산 윈도우 |
| ~16:10 | b4c94nmcb | Post-market + IBD fix (KOSDAQ150) |

## Issues

### IBD KOSDAQ150 (229200) 누락
- US와 동일 이슈 — IBD fix가 `bulk_load_from_pykrx(['069500','229200'], days=70)` 추가
- US에서 이미 검증 완료 (QQQ 정상 표시)
- KR post_market(KST 16:00)에서 자동 적용 예정

## Session Summary

### 사전 검증 완료 항목
1. ✅ 대시보드 KR 10개 엔드포인트 정상
2. ✅ 5개 포지션 상세 확인 (stop 6-10.2%, 합리적)
3. ✅ Paper 모드 ENTRY/PYRAMID/STOP_LOSS 과거 체결 확인
4. ✅ DART 재무데이터 최신 (2025Q3)
5. ✅ KR 특화 로직 코드 검증 (REST-only, tick 조정, Donchian KST 15:15-15:30)
6. ✅ 매매 로직 12개 규칙 US 감시에서 코드 검증 완료 (KR 동일 코드)
7. ✅ IBD fix 배포 + US에서 성공 검증

### 참고: US 감시 결과 (2026-03-17)
- 6.5시간 연속 가동, 에러 0, 65,000+ ticks
- Equity: $86,169 → $87,839 (+$1,670, +1.94%)
- IBD fix 성공 (SPY + QQQ 모두 정상)
- 상세: `20260317_monitoring_us.md` 참조

*Last updated: 2026-03-18 KST 06:10*
*백그라운드 체크 6개가 KST 07:05~16:10 자동 실행*
