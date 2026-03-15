# 2026-03-03 US Market Watchlist & Monitoring Report

## Market Status
- **Trading Mode**: Paper
- **Market Filter**: PASS (SPY 678.73 > SMA200 652.19)
- **WS Status**: DISCONNECTED (pre-market, 장 시작 전)
- **Account Equity**: $245,362.67

## Open Positions (5)

| Ticker | System | Entry | Stop | Shares | Close | PnL% | Risk |
|--------|--------|-------|------|--------|-------|------|------|
| AEM | S1 | 239.04 | 215.13 | 312 | 250.02 | +4.60% | Normal |
| GVA | S1 | 136.79 | 123.11 | 337 | 133.43 | -2.45% | Normal |
| ISSC | S1 | 24.98 | 22.49 | 852 | 26.86 | +7.52% | Normal |
| TSM | S1 | 386.79 | 341.83 | 232 | 369.52 | -4.47% | S1 Exit 근접 (10d low=356.24) |
| UGP | S1 | 5.41 | 4.87 | 3966 | 4.86 | -10.12% | **GAP-DOWN RISK** (close < stop) |

## Key Alerts
- **UGP**: 전일 종가($4.86) < 스톱($4.87) — 장 시작 시 gap-down exit 가능성 높음
- **TSM**: 전일 종가($369.52) S1 exit(10d low) 근접 — Donchian 하단 이탈 감시 필요

## Active Watchlist (21 종목)

| # | Ticker | Name | RS | Score | Price | Exchange |
|---|--------|------|----|-------|-------|----------|
| 1 | ISSC | | 97 | 90.0 | 26.86 | NASD |
| 2 | FIX | | 96 | 87.0 | 1401.10 | NYSE |
| 3 | KGC | | 95 | 91.0 | 37.09 | NYSE |
| 4 | B | | 94 | 92.0 | 50.08 | NYSE |
| 5 | NEM | | 94 | 85.0 | 129.61 | NYSE |
| 6 | VRT | | 94 | 84.0 | 250.88 | NYSE |
| 7 | AEM | | 93 | 90.0 | 250.02 | NYSE |
| 8 | TSM | | 90 | 78.0 | 369.52 | NYSE |
| 9 | WWD | | 89 | 78.0 | 386.96 | NASD |
| 10 | WT | | 89 | 76.0 | 17.01 | NYSE |
| 11 | EZPW | | 89 | 73.0 | 26.08 | NASD |
| 12 | CVE | | 87 | 83.0 | 23.30 | NYSE |
| 13 | OUT | | 86 | 69.0 | 28.38 | NYSE |
| 14 | HXL | | 85 | 82.0 | 94.55 | NYSE |
| 15 | AROC | | 85 | 79.0 | 35.90 | NYSE |
| 16 | UGP | | 84 | 77.0 | 4.86 | NYSE |
| 17 | JCI | | 83 | 75.0 | 144.52 | NYSE |
| 18 | NVS | | 83 | 73.0 | 167.46 | NYSE |
| 19 | GVA | | 82 | 68.0 | 133.43 | NYSE |
| 20 | HG | | 80 | 77.0 | 31.50 | NYSE |
| 21 | MCK | | 80 | 76.0 | 988.05 | NYSE |

## Pre-Market Summary (22:00 KST)
- Market filter: PASS (fail-open due to SPY SMA200=None → fixed by filling 310 days of SPY history)
- Signals computed: 21/21 success
- Gap-down risk: UGP (close $4.86 ≈ stop $4.87)
- Next scheduled event: Market Open at 23:30 KST

## Monitoring Plan (23:30 ~ 05:00 KST)
1. **23:30**: WS 연결 확인, 종목 구독 확인
2. **23:30~23:35**: Gap-down exit 확인 (UGP, TSM)
3. **23:30~06:00**: 진입 신호 모니터링 (Donchian breakout)
4. **05:45~06:00**: Donchian exit 확인 (장 마감 15분 전)
5. **전 시간**: 2N stop loss 실시간 감시, 에러 로그 감시

## Bug Fixes Applied Today
- **Bug #8**: SPY SMA200 계산 불가 — 벤치마크 히스토리 부족
  - 원인: SPY가 watchlist에 없어서 초기 대량 로딩 대상 아님, 9일치만 축적
  - 수정: SPY 310일 수동 채움 + `_ensure_benchmark_history()` 자동 채움 로직 추가

---
*Generated at 2026-03-03 22:20 KST*
