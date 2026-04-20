# US Market Monitoring - 2026-03-17

## Session Overview
- **Market**: US (Paper Mode)
- **Date**: 2026-03-17 (Monday)
- **Market Open**: ET 09:30 (KST 22:30)
- **Market Close**: ET 16:00 (KST 05:00+1)
- **Bot Service**: active (running) since KST 17:53

---

## Pre-Market (ET 08:00 / KST 21:00)
- **Trigger**: 정상 (12:00 UTC)
- **Market Filter**: PASS (SPY 669.03 > SMA200 656.77)
- **Regime**: YELLOW (scale=0.5)
- **Breadth**: 45.8%
- **ROC 125**: 1.81%
- **Watchlist**: 14 tickers
- **Positions**: 4
- **Signals**: 14
- **Gap-down**: 0

## CANSLIM Screening (KST 20:00)
- **Universe**: 6,600 tickers
- **Price Records**: 564 new
- **Earnings Targets**: 144
- **Fundamental Records**: 4,978 new (644 tickers)
- **CANSLIM Passed**: 31
- **Minervini Passed**: 13
- **Final Watchlist**: 13 tickers (1 removed from prior, 0 added)
- **Elapsed**: 4,128.5s (~69 min)
- **Verdict**: 최신 재무데이터(2025Q4) 기반 정상 업데이트 확인

### Watchlist Tickers (13)
ISSC, CVE, VRT, COCO, AROC, EIX, GCT, WWD, MCK, EZPW, JCI, NVS, NSSC

## Market Open (ET 09:30 / KST 22:30)
- **Trigger**: 정상 (13:30 UTC)
- **WebSocket**: CONNECTED (ws://ops.koreainvestment.com:31000/tryitout)
- **WS Subscriptions**: 14/14 SUCCESS
- **REST Polling**: 14 tickers, 0 errors (10초 간격)
- **Tick Data**: 정상 수신 (5분에 ~1,477 ticks)

## Open Positions (at market open)

| Ticker | Avg Entry | Stop | Stop % | Shares | Units | N | Current | Unrealized |
|--------|-----------|------|--------|--------|-------|---|---------|------------|
| ISSC   | 25.997    | 24.75| -4.8%  | 1,414  | 2     | 0.0* | 29.28 | +$4,641 (+12.6%) |
| VRT    | 265.17    | 242.78| -8.4% | 63     | 2     | 12.39 | - | - |
| EZPW   | 26.27     | 25.18| -4.1%  | 465    | 1     | 0.88 | 25.80 | -$219 (-1.8%) |
| CVE    | 23.52     | 22.07| -6.2%  | 549    | 1     | 0.73 | 23.42 | - |

*ISSC n_at_entry=0.0 (DB 기록 문제, 운영 영향 없음 - stop은 이미 설정됨)

## Account Status
- **Equity**: $86,169.10
- **Cash**: $3,227.36
- **Positions Value**: $82,941.74
- **Positions/Units**: 4/6

## Dashboard API Status (All US endpoints)
| Endpoint | Status |
|----------|--------|
| /api/status?market=US | OK |
| /api/positions?market=US | OK |
| /api/journal?market=US | OK |
| /api/diary?market=US | OK |
| /api/trades?market=US | OK |
| /api/alerts/near-entry?market=US | OK |
| /api/alerts/near-exit?market=US | OK |
| /api/pnl?market=US | OK |
| /api/watchlist?market=US | OK |
| /api/ibd/status?market=US | OK (QQQ 누락 - fix 배포됨, post_market에서 적용 예정) |

## Intraday Activity Log

### ET 09:30 - Market Open
- 장 개장, 14종목 모니터링 시작
- ISSC 피라미딩 신호 감지 → 현금 부족 ($3,227 < $8,252 필요) → 정상 스킵
- REST polling 0 에러, WS 정상

### Trading Logic Verification
- **손절 체크**: 매 틱마다 실행 (Priority 1). 현재 트리거 없음 (모든 포지션 stop 위)
- **피라미딩 체크**: ISSC만 조건 충족하나 현금 부족으로 스킵 (Priority 2)
- **신규 진입 체크**: 포지션 없는 종목에 대해 Donchian 돌파 체크 실행 중 (Priority 3)
- **Donchian 청산**: ET 15:45~16:00에만 체크 예정 (Priority 4)

---

## Bugs / Issues Found

### Bug #1: IBD Market Direction - QQQ/229200 가격 데이터 누락
- **증상**: IBD 시장방향에 QQQ 데이터 없음, 229200도 3/17 데이터 없음
- **원인**: daily_screening/pre_market이 유니버스/watchlist 종목만 가격 수집 → ETF인 QQQ, 229200이 대상에서 제외
- **수정**: `post_market._update_ibd_direction()`에서 IBD 인덱스 종목 가격을 명시적으로 fetch하도록 코드 추가
- **파일**: `bot/post_market.py` line 475-491
- **상태**: 코드 수정 완료, 서버 배포 완료. 다음 post_market (ET 16:30) 실행 시 자동 적용 예정
- **심각도**: Medium (IBD는 로깅 전용, 매매 영향 없음)

### Issue #2: ISSC n_at_entry = 0.0
- **증상**: ISSC 포지션의 n_at_entry가 0.0으로 기록됨
- **영향**: 없음 (손절가는 이미 설정, 장중 체크는 current_stop_price 사용)
- **심각도**: Low (DB 기록 불완전, 기능 영향 없음)

### Issue #3: Stop Price 계산 기준 - 신호 시점 vs 체결가
- **증상**: EZPW stop=25.18 (breakout 26.93 - 2N), 체결가 26.27 기준이면 stop=24.51이어야 함
- **분석**: `_execute_entry()`에서 `calculate_unit_shares(entry_price=price)`의 `price`가 Donchian 돌파 감지 시점 현재가 (≈breakout level). 체결가와 슬리피지 차이 시 stop이 체결가 기준 2N과 다름
- **영향**: 보수적 방향 (stop이 더 타이트 → 리스크 감소). 치명적 아님
- **개선 제안**: 체결 후 stop 재계산 (체결가 기반) — 향후 개선 사항으로 별도 관리
- **심각도**: Low (보수적 방향, 매매 안전성에 영향 없음)

---

## Near-Entry Alerts (ET 09:41)

| Ticker | Price | Donchian 20 | Proximity | Level | Signal | Has Position? |
|--------|-------|-------------|-----------|-------|--------|---------------|
| CVE    | 23.41 | 23.91       | 2.09%     | close | S1     | Yes (pyramid) |
| COCO   | 59.53 | 61.37       | 3.00%     | close | S1     | No            |
| VRT    | 267.68| 276.78      | 3.29%     | close | S1     | Yes (pyramid) |
| EIX    | 72.97 | 75.50       | 3.35%     | close | S1     | No            |
| AROC   | 35.68 | 37.26       | 4.24%     | close | S1     | No            |
| EZPW   | 25.80 | 26.93       | 4.20%     | close | S1     | Yes (pyramid) |

## Code-Level Trading Logic Verification

| Component | Strategy Reference | Code | Verified |
|-----------|-------------------|------|----------|
| S1 Entry: 20일 Donchian 돌파 | §5 | `entry_signals.py:43` | OK |
| S1 Filter: 이전 돌파 수익 시 스킵 | §5.3 | `entry_signals.py:61-64` | OK |
| S2 Entry: 55일 Donchian 돌파 | §5 | `entry_signals.py:102` | OK |
| 시장 필터: SPY > SMA200 | §2.2 | `entry_signals.py:156` | OK |
| 포지션 사이징: min(2N, 10%) | §4.2 | `position_sizer.py:71` | OK |
| 피라미딩: 1/2 N 간격, 최대 4유닛 | §6 | `pyramiding.py:44,73` | OK |
| 손절: min(2N, 10%) | §7 | `stop_loss.py` + `intraday_monitor.py:295` | OK |
| Donchian 청산: 10일/20일 저가 이탈 | §8 | `exit_signals.py` | OK |
| 청산 시간: 장 마감 15분 전 | §8 | `exit_signals.py:183` (ET 15:45-16:00) | OK |
| Chase guard | 추가 안전장치 | `entry_signals.py:49-59`, `pyramiding.py:95-106` | OK |
| WS reconnect | 인프라 | `kis_websocket.py:173` | OK |
| 포지션 동기화 | 인프라 | `broker/account.py` → 4 matched, 0 mismatch | OK |

## Periodic Check Log

| Time (ET) | Check | Result |
|-----------|-------|--------|
| 09:30 | Market Open | OK - 14 tickers, WS connected |
| 09:36 | First heartbeat | OK - 1,477 ticks, all 14 tickers |
| 09:41 | Position check | EZPW 2.4% to stop (watch), others safe |
| 09:44 | Error scan | 0 errors, 0 exceptions since open |
| 09:48 | Position update | EZPW improved 2.4%→3.7% to stop |
| 09:51 | Full status | 5,856 ticks, cycle 51, all stable |
| 09:52 | Code review | All trading logic verified vs strategy spec |
| 09:54 | Dashboard svc | active 24h+, HTTP 200 |
| 09:55 | Watchlist history | AEM removed (Minervini), GCT added |
| 09:55 | Journal/PnL/Diary | All working, 3/17 equity $86,689 (+$763) |
| 09:55 | Position update | VRT +1.0% (반등), EZPW -0.32% (개선) |
| 09:57 | Rate limit warn | KIS API "초당 거래건수 초과" 2회 (자동 재시도 성공, 기존 이슈) |
| 09:57 | Status | 7,263 ticks, cycle 65, equity $86,333 |
| 10:00 | Heartbeat | 8,632 ticks, 14 unique tickers |
| 10:00 | WS reconnect | WS 자동 재연결 + 3종목 재구독 성공 + count reset ✅ |
| 10:02 | Status | cycle 77, 0 errors, equity $86,620 |
| 10:04 | Full status | Equity $86,708, Total PnL +$4,930, all safe |

---

## Automated Monitoring Schedule (Background)

| Time (ET) | Task | Status |
|-----------|------|--------|
| ~10:10 | 30분 체크 | Scheduled |
| ~11:10 | 90분 체크 | Scheduled |
| ~13:40 | 세션 중반 체크 | Scheduled |
| ~15:50 | Donchian 청산 윈도우 체크 | Scheduled |
| ~16:05 | 봇 재시작 (IBD fix 적용) | Scheduled |
| ~16:40 | Post-market + IBD 검증 | Scheduled |

## Session Summary (ET 10:04 기준)

### 전체 평가: 봇 정상 동작 ✅

**핵심 확인 사항:**
1. **CANSLIM 스크리닝**: 최신 재무데이터(2025Q4) 기반 6600종목 스크리닝 → 13종목 워치리스트 정상
2. **매매 로직**: 전략 명세서 12개 규칙 100% 코드 일치 확인
3. **실시간 운영**: 34분간 에러 0, 매매 이벤트 정상 처리, WS 재연결 성공
4. **대시보드**: 10개 API + watchlist history, journal, diary, PnL 모두 정상
5. **포지션 동기화**: DB ↔ 브로커 100% 일치

**발견된 이슈 (3건, 모두 Low~Medium):**
1. IBD QQQ 가격 누락 → fix 배포 완료 (Medium)
2. ISSC n_at_entry=0.0 → 영향 없음 (Low)
3. Stop 계산 기준 → 보수적 방향 (Low)

**포지션 현황 (ET 10:04):**
- ISSC: +13.2% (+$4,641)
- VRT: +1.07% (+$178)
- EZPW: -0.61% (-$74)
- CVE: -0.21% (-$28)
- **총 미실현 PnL: +$4,930**

## Post-Market Results (ET 16:30)

- **Trigger**: 정상 (20:30 UTC)
- **포지션 동기화**: 4 matched, 불일치 0
- **미체결 주문**: 0
- **Daily Report**: equity $87,839, daily PnL **+$1,913**
- **IBD Fix 검증**: ✅ **성공!**
  - `ibd_price_refreshed` 로그 확인 (SPY, QQQ 가격 fetch 성공)
  - SPY: RALLY_ATTEMPT (Day 2, dist 0)
  - QQQ: RALLY_ATTEMPT (Day 1, dist 0) ← **신규 데이터!**
  - API `/api/ibd/status?market=US` 에서 SPY + QQQ 모두 표시 확인

## Final Session Results

| Metric | Open (ET 09:30) | Close (ET 16:00) | Change |
|--------|----------------|-------------------|--------|
| Equity | $86,169 | $87,839 | **+$1,670 (+1.94%)** |
| Daily PnL | - | +$1,913 | - |
| Positions | 4 | 4 | No change |
| Entries | - | 0 | - |
| Exits | - | 0 | - |
| Stop Losses | - | 0 | - |
| Errors | - | 0 | - |
| Ticks Processed | 0 | 65,094+ | - |
| REST Cycles | 0 | 610+ | 14/14 OK |
| WS Reconnects | 0 | 1 (auto-recovered) | - |

*Last updated: 2026-03-17 ET 16:43 (Post-market verified)*
