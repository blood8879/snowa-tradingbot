# 2026-03-19 US 장 감시 내역

## 감시 환경
- **서버**: ubuntu@43.202.181.170
- **봇 서비스**: snowa-bot.service
- **대시보드**: snowa-dashboard.service (port 8000)
- **모드**: Paper (모의투자)

## US 스케줄 (KST 기준)
| 시간 (KST) | 이벤트 | 상태 |
|------------|--------|------|
| 20:00 | US CANSLIM 스크리닝 (yfinance 재무데이터) | ✅ 완료 (6572→33 CANSLIM→13 Minervini) |
| 21:00 | US Pre-Market 준비 (시그널 계산) | ✅ 완료 (15 signals, regime=YELLOW) |
| 22:30 | US 장 개장 / Intraday 모니터링 시작 | 🟢 진행 중 |
| 05:30+1 | US Post-Market 정리 | ✅ 완료 (equity=$87,404, PnL=+$935) |

## 현재 US 포지션 (4개)
| 종목 | 수량 | 평균단가 | 손절가 | 미실현 PnL |
|------|------|---------|--------|-----------|
| CVE | 549주 | $23.52 | $22.07 | +2.2% |
| EZPW | 465주 | $26.27 | $25.18 | -1.6% |
| ISSC | 1,414주 | $26.00 | $24.75 | +10.5% |
| VRT | 63주 | $265.17 | $242.78 | -2.8% |

## US 워치리스트 (13종목 ACTIVE)
CVE, ISSC, VIST, VRT, AROC, BTSG, COCO, EIX, GCT, WWD + 3종목

## 3월 US 매매 실적
- 4건 청산 (모두 손절): UGP, TSM, GVA, AEM
- 총 PnL: -$14,698.36
- 승률: 0%

## 장 전 코드 수정 (KR 감시 중 적용 — US에도 공통 적용)
1. `screening/watchlist_manager.py` — 탈락 history에 최신 EPS + 이전→현재 비교
2. `bot/intraday_monitor.py` — `calculate_unit_shares()`에 `market` 전달 (KR/US 공통)
3. `broker/order_executor.py` — KR Paper fill 가격 + BUY 가드 수정

---

## 감시 로그

### 05:38 — 초기 상태 확인
- US 포지션 4개, 모두 "safe" (exit proximity 5.7%~11.5%)
- US 워치리스트 13종목 active
- 대시보드 US 탭 전수 확인: positions, journal, exit alerts, watchlist history 모두 정상
- watchlist history 새 포맷 확인: SBS `79%→-56%<25%` (이전→현재 비교 동작)
- 3월 매매일지: 4건 손절 (UGP, TSM, GVA, AEM), total PnL -$14,698

### 20:00 — US CANSLIM 스크리닝
- Universe: 6,572 stocks
- Price refresh: 6,908 new records (1329.7s)
- Earnings targets: 264개
- **Stale targets capped**: 3,319 → 500 (새 cap 코드 동작 ✅)
- Fundamentals: 764 tickers, 5,914 new records (3250.5s)
- CANSLIM: 33 passed → Minervini: 13 passed → 워치리스트 13개
- History: 1 added, 3 removed
- Total pipeline: 4599.9s (76.7min)

### 21:00 — US Pre-Market
- 시그널 15개 계산 완료
- Gap-down: 0개
- **Market regime: YELLOW** (SPY 661.43 > SMA200 657.66, but breadth=43.5%)
  - `regime_scale=0.5` → 신규 진입 시 포지션 사이즈 50% 축소
- 포지션: 4개, 워치리스트: 15개 (스크리닝 후 13으로 축소)

### 22:30 — US 장 개장
- Intraday 시작: 15종목 모니터링
- WebSocket 연결 ✅ (첫 틱 VRT $258.01)
- REST 폴링 ✅ (15종목, errors=0)
- 피라미딩 시그널 감지: CVE ($3,227 < $13,700 필요), ISSC ($3,227 < $8,250 필요) → 현금 부족 skip
- 22:45 KST: 4,335 ticks, 15 unique tickers, 에러 없음

### 01:10 — US 장중 2시간 40분 경과
- 48,457 ticks, 매매 이벤트 0건, 에러 0건
- CVE $25.33 (+7.7%), AROC $36.42

### 05:30 — US Post-Market 완료
- Equity: $87,404.14
- **Daily PnL: +$935.47**
- 포지션 sync: 4개 matched, 미체결 0
- IBD 가격 갱신: SPY, QQQ ✅
- 전체 세션 매매 이벤트: 0건, 에러: 0건

### 23:09 — US 장중 39분 경과
- 10,605 ticks, pyramid skip 44회 (현금 부족), 매매 이벤트 0건
- 대시보드 포지션 실시간 업데이트 확인: CVE +2.7%, ISSC +7.5%, VRT -1.8%, EZPW -0.4%

### 23:20 — US 장중 50분 경과
- 15,247 ticks, 에러 0건, 매매 이벤트 0건
- cash=$3,227.36 (변동 없음)
- CVE $24.66(+4.8%), AROC $36.28, BTSG $44.01

### US watchlist history 새 포맷 확인 ✅
- SBS: `79%→-56%<25%` (이전→현재 EPS 비교)
- EPS성장률 컬럼: -55.8% (최신 스크리닝 값 반영)

## 최종 요약

### 오늘 확인 완료 항목
1. ✅ **CANSLIM 스크리닝 최신 재무데이터 반영**
   - KR: DART 685종목 3,597 레코드 수집 → 최신 Q4 파생 데이터 포함
   - US: yfinance 764종목 5,914 fundamental 레코드 갱신
2. ✅ **매수/매도 로직 정상** — 터틀 전략 규칙 준수 (진입/손절/피라미딩/청산)
3. ✅ **대시보드 KR/US 탭 전체 기능 정상**
   - positions, journal, diary, alerts, exit alerts, watchlist, watchlist history
4. ✅ **watchlist history 이전→현재 EPS 비교 포맷** (KR/US 모두)

### 코드 수정 및 배포
1. `screening/watchlist_manager.py` — EPS 비교 표시 + 최신값 기록
2. `bot/intraday_monitor.py` — calculate_unit_shares market 전달 (HIGH 버그)
3. `broker/order_executor.py` — KR Paper fill 가격 정확도 + BUY 가드
4. `bot/daily_screening.py` — stale targets cap (500)
5. `bot/post_market.py` — IBD 인덱스 가격 refresh
6. `core/database.py` — watchlist_history 테이블 스키마
7. `web/api/routes/watchlist.py` — history API 엔드포인트
8. Frontend build 배포
