# 2026-03-19 KR 장 감시 내역

## 감시 환경
- **서버**: ubuntu@43.202.181.170
- **봇 서비스**: snowa-bot.service (05:26 KST 재시작)
- **대시보드**: snowa-dashboard.service (port 8000)
- **모드**: Paper (모의투자)
- **시장 필터**: GREEN (market_filter=true, 2026-03-18 기준)

## KR 스케줄
| 시간 (KST) | 이벤트 | 상태 |
|------------|--------|------|
| 07:00 | KR CANSLIM 스크리닝 | ✅ 완료 (3672→15 CANSLIM→12 Minervini) |
| 08:00 | Pre-Market 준비 (시그널 계산) | ✅ 완료 (14 signals, 0 gap-down) |
| 09:00 | 장 개장 / Intraday 모니터링 시작 | ✅ 정상 운영 (13,490 ticks) |
| 15:30 | 장 종료 | ✅ 정상 종료 |
| 16:00 | Post-Market 정리 | ✅ equity=11,310,106원, PnL=-124,834원 |

## 현재 KR 포지션 (5개)
| 종목 | 수량 | 평균단가 | 손절가 | 미실현 PnL |
|------|------|---------|--------|-----------|
| 036170 에이치엔넥스 | 649주 | 3,581원 | 3,290원 | +42.1% |
| 084110 휴온스글로벌 | 26주 | 72,000원 | 65,790원 | +0.8% |
| 218410 RFHIC | 11주 | 80,900원 | 72,630원 | -2.9% |
| 237690 에스티팜 | 7주 | 164,500원 | 147,960원 | -5.2% |
| 290550 디케이티 | 224주 | 14,355원 | 13,500원 | +31.6% |

## KR 워치리스트 (16종목 ACTIVE)
005440, 218410, 368770, 278470, 015750, 085620, 001440, 031980, 298040, 071050, 267250, 010120, 290550, 019180, 084110, 237690

## 장 전 코드 배포
- [x] `screening/watchlist_manager.py` — 탈락 history에 최신 EPS 값 + 이전→현재 비교 표시 수정

---

## 감시 로그

### 05:22 — 초기 상태 확인
- 봇 서비스 정상 가동 (24시간 전 시작, US 장 종료 후 대기 중)
- 어제 KR 스크리닝 (07:37 KST): 3,672종목 → CANSLIM 23개 → Minervini 16개 → 워치리스트 16개
- DART 데이터 수집 정상: 685종목, 3,587 레코드
- KR 포지션 5개, 모두 OPEN
- 계좌: equity=11,434,940원, cash=74,960원

### 05:26 — 봇 재시작
- watchlist_manager.py 코드 배포 후 재시작
- 스케줄러 정상 등록: KR Daily CANSLIM Screening, Pre-Market, Intraday, Post-Market

### 05:30 — 대시보드 KR 탭 전수 확인
- `/api/watchlist?market=KR` ✅ — 16종목, EPS/RS/종합점수 정상
- `/api/positions?market=KR` ✅ — 5개 포지션, 현재가/미실현PnL 정상
- `/api/alerts/near-entry?market=KR` ✅ — 진입알림 (278470 에이피알 breakout 감지)
- `/api/alerts/near-exit?market=KR` ✅ — 청산알림 5개 모두 "safe"
- `/api/journal?market=KR&month=2026-03` ✅ — 2건 (RFHIC, PSK홀딩스 손절)
- `/api/diary?market=KR` ✅ — 주문 상세 + 전략 컨텍스트 정상
- `latest_financial_date`: "2025-09-28" (DART Q3 2025 데이터 기준) — DART 최신 공시 반영 확인됨

### 05:30 — 발견 사항
1. **대시보드 yfinance 경고**: KR 종목을 `/api/prices/realtime`에서 yfinance로 조회 시 "possibly delisted" 에러 → 각 API가 자체 latest_price 제공하므로 실질적 문제 없음 (로그 노이즈)

### 05:34 — 코드 리뷰 기반 버그 수정 & 재배포
**코드 리뷰 결과**: HIGH 2개, MEDIUM 4개, LOW 2개 발견

**수정 완료 (HIGH):**
1. **`calculate_unit_shares()`에 `market=self._market` 미전달** — KR 포지션의 손절가 tick 조정 안 됨, 포지션 과대 사이징 위험
   - 파일: `bot/intraday_monitor.py` (line 492, 664)
   - 수정: pyramid/entry 양쪽에 `market=self._market` 추가

2. **KR Paper fill 가격 왜곡** — `requested_price`(buffer 포함)를 체결가로 사용 → P&L 1.2%↑ 왜곡
   - 파일: `broker/order_executor.py` (line 504-512)
   - 수정: 브로커 잔고의 `pchs_avg_pric`(매입평균가) 사용, BUY 체결 시 `broker_qty > db_shares` 가드 추가

**배포**: `intraday_monitor.py`, `order_executor.py` → 봇 재시작 05:34 KST

### 07:00 — KR CANSLIM 스크리닝
- DART prefetch: 685종목 → 3,597 레코드 수집 ✅
- CANSLIM: 3,672 screened → 15 passed
- Minervini: 12 passed → 워치리스트 12개 저장
- **4종목 탈락** (새 EPS 비교 포맷 정상 동작):
  - 290550 디케이티: `27%→-65%<25%`
  - 085620 미래에셋생명: `2661%→-96%<25%`
  - 368770 파이버프로: `489%→-57%<25%`
  - 001440 대한전선: `60%→-12%<25%`
- EPS성장률 컬럼도 최신값(-65%, -96% 등)으로 업데이트됨

### 08:00 — KR Pre-Market
- 시그널 14개 계산 완료
- Gap-down: 0개
- Market filter: true (상승 시장)

### 09:00~15:30 — KR 장중 모니터링
- REST 폴링 정상 (14종목, 13,490+ 틱)
- 매수/매도 실행: 없음 (시그널 미발생)
- 현금: 364,041원 (유지)
- 에러: 없음

### 16:00 — KR Post-Market
- Equity: 11,310,106원 (전일 대비 -124,834원)
- 포지션 sync: matched=4 (DB-브로커 일치)
- 미체결 주문: 0개
- Daily PnL: -124,834원
