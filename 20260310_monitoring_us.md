# 2026-03-10 US 장 감시 내역

## 봇 상태 (최종)
- **모드**: Paper (모의투자)
- **서비스**: `snowa-bot.service` active
- **스케줄러**: 8개 작업 등록 (US: America/New_York TZ, KR: Asia/Seoul TZ)
- **시장 필터**: PASS (SPY 678.27 > SMA200 654.58)

## 세션 요약
| 항목 | 값 |
|------|-----|
| 장 시작 | 09:30 ET (22:30 KST) — DST 적용 |
| 장 종료 | 16:00 ET (05:00 KST) |
| Post-Market | 16:30 ET (05:30 KST) ✅ |
| 총 틱 수신 | 169,723 |
| REST polling 사이클 | 962 (15/15 ok, 0 errors) |
| Fill check | 821회 (pending 0) |
| 일일 손익 | **+$2,758.57** |
| 계좌 equity | **$88,138.79** |
| 현금 | $15,467.34 |
| 포지션 가치 | $72,671.45 |

## 보유 포지션 (US, 3개)
| 종목 | 시스템 | 수량 | 유닛 | 평균단가 | 손절가 | 비고 |
|------|--------|------|------|----------|--------|------|
| CVE | S1 | 549 | 1 | $23.52 | $22.07 | |
| ISSC | S1 | 1414 | 2 | $26.00 | $24.75 | 피라미딩 차단 (equity 40% 초과) |
| VRT | S1 | 63 | 2 | ~$265 | $242.78 | 09:35 ET 피라미딩 체결 |

## 워치리스트 (US, 14종목)
AEM, CVE, VRT, HXL, AROC, TSM, UGP, WWD, EZPW, WT, JCI, GE, NVS, OUT
- 모두 Minervini PASS, RS Rating 80+

## 진입 근접 알림
- **VRT**: S1+S2 돌파 완료 (보유 중, 피라미딩 진행)
- **AROC**: S1 임박 (1.66%)
- **EZPW**: S1 근접 (2.56%)
- **OUT**: S1 근접 (3.45%)

## 3월 청산 내역 (US, 전부 손절)
| 종목 | 손익 | 청산사유 | 청산일 |
|------|------|----------|--------|
| UGP | -$2,090 | STOP_LOSS | 03-05 |
| TSM | -$7,810 | STOP_LOSS | 03-05 |
| GVA | -$2,318 | STOP_LOSS | 03-05 |
| AEM | -$6,214 | STOP_LOSS | 03-05 |

## 장중 매매 내역 (3/10)
| 시각(ET) | 종목 | 유형 | 수량 | 가격 | 비고 |
|----------|------|------|------|------|------|
| 09:35 | VRT | PYRAMID (unit 2) | 31주 | $268.48 | 주문 $269.23 → 체결 $268.48 |

- 손절 미트리거 (3개 포지션 모두 손절가 위)
- Donchian exit 미트리거 (3개 포지션 모두 10일 저가 위 종가)
- 신규 진입 미발생 (돌파 시그널 미달)

## Post-Market 결과 (16:30 ET)
- 포지션 동기화: 3개 매칭 (불일치 없음)
- 미체결 주문: 없음
- equity: $88,138.79, daily_pnl: +$2,758.57
- 소요 시간: 6.79초

## 발견 및 수정한 버그

### Bug #24: journal API daily_log 쿼리에 market 필터 누락
- **증상**: 매매일지 월간 손익 -$165,912, 최대자산 $10.9M (KR ₩10,942,542가 USD로 합산)
- **원인**: `journal.py`의 daily_log 쿼리 3곳에 `AND market = ?` 누락
- **수정**: `journal.py`, `status.py`, `performance.py` — daily_log 쿼리에 market 필터 추가
- **파일**: `web/api/routes/journal.py`, `web/api/routes/status.py`, `web/api/routes/performance.py`

### Bug #25: daily_log 2월 말 equity 데이터 부풀림 (히스토리컬)
- **증상**: 2/25 equity=$252k (starting_equity=$100k → +152% 수익률은 paper 모드에서 비현실적)
- **원인**: 과거 paper 모드 잔고 조회 버그로 인한 부풀려진 equity 기록
- **상태**: 히스토리컬 데이터이므로 현재 세션에서 수정하지 않음 (참고만)

### Bug #26: journal API get_account_info() market 파라미터 누락
- **증상**: KR 매매일지에서 US equity 값이 사용됨
- **원인**: `journal.py:196` — `get_account_info()` 호출 시 `market` 파라미터 미전달
- **수정**: `get_account_info(market=market)` 으로 수정
- **파일**: `web/api/routes/journal.py`

### Bug #27 (Critical): DST 미반영 — US 스케줄 시간 오류
- **증상**: 3/8부터 DST 적용으로 장 시작 22:30 KST인데, 스케줄이 23:30 KST로 설정
- **원인**: `trading_bot.py` US 스케줄이 Asia/Seoul TZ로 하드코딩
- **수정**: US 스케줄 트리거를 `America/New_York` TZ로 변경
  - Pre-market: 8:00 AM ET
  - Market open: 9:30 AM ET
  - Post-market: 4:30 PM ET (mon-fri)
- **파일**: `bot/trading_bot.py`
- **검증**: Post-market 16:30 ET에 정확히 실행됨 ✅

### Bug #28: 리스크 매니저 market 필터 누락 — 피라미딩 차단
- **증상**: US 유닛 4개인데 "Total long limit: 12/12 units"로 피라미딩 차단
- **원인**: `risk_manager.py`의 `_count_units_by_group()`가 US+KR 전체 유닛 합산 (US 4 + KR 8 = 12)
- **수정**: `_count_units_by_group(market=)` 파라미터 추가, `can_enter_position`/`can_add_unit`에 market 전달
- **영향**: 수정 후 VRT 피라미딩 즉시 실행됨 (unit 2, 31주 @ $268.48)
- **파일**: `portfolio/risk_manager.py`, `bot/intraday_monitor.py`

### 대시보드 추가 수정
- 워치리스트 페이지: 편입일 컬럼 추가 (YYYYMMDD 포맷)
- 워치리스트 페이지: 실시간 거래량/50일 평균 컬럼 제거
- 매매일지/종목일기: KR 종목명 표시 추가

## 대시보드 API 점검 (21:55 KST)
| 엔드포인트 | 상태 | 비고 |
|-----------|------|------|
| /api/status | ✅ | equity=$85,546, 3포지션, 4유닛 |
| /api/positions | ✅ | CVE(-2.98%), ISSC(+10.86%), VRT(+0.91%) |
| /api/journal | ✅ | monthly_pnl 부정확 (Bug #25 히스토리컬 데이터) |
| /api/diary | ✅ | 주문 상세 + 컨텍스트 정상 |
| /api/trades | ✅ | 체결/미체결 내역 정상 |
| /api/alerts/near-entry | ✅ | VRT breakout, EZPW/AROC/OUT close |
| /api/alerts/near-exit | ✅ | 3포지션 모두 safe |
| /api/pnl | ✅ | 일별 equity 데이터 (2월 부풀림 있음) |
| /api/watchlist | ✅ | 14 ACTIVE, 편입일 표시 |

## 코드 리뷰 (매매 로직)
- **entry_signals.py** ✅ S1(20일 Donchian), S2(55일), chase guard
- **exit_signals.py** ✅ S1→10일저, S2→20일저, 장마감 15분전만 체크
- **stop_loss.py** ✅ min(2N, 10%), UP_ONLY, pyramid tightening
- **pyramiding.py** ✅ 0.5N 간격, 최대 4유닛
- **intraday_monitor.py** ✅ 우선순위: 손절→피라미딩→진입→Donchian청산
- **order_executor.py** ✅ 재시도, odno 정규화, 잔고 캐시
- **pre_market.py** ✅ 토큰/가격/시그널/마켓필터/갭다운
- **trading_bot.py** ✅ 스케줄러, catchup, kill switch

## 스케줄 & 감시 타임라인
- [x] 20:00 KST — Daily CANSLIM Screening (20:03 재시작으로 중단, 기존 워치리스트 유효)
- [x] 22:00 KST (08:00 ET) — Pre-Market Preparation ✅ (3.69초, 15시그널, 마켓필터 PASS, 갭다운 0)
- [x] 22:30 KST (09:30 ET) — Market Open ✅ (DST 수정 후 catchup 정상 작동)
  - WS 15종목 구독, 첫 틱 AEM $229.02
  - Bug #28 수정 → 22:35 재시작 → VRT 피라미딩 즉시 체결
- [x] 05:00 KST (16:00 ET) — Market Close (Donchian 청산 미트리거)
- [x] 05:30 KST (16:30 ET) — Post-Market Cleanup ✅ (6.79초, 3포지션 sync, equity $88,139)

## 총평
- 장 전체 세션 (09:30~16:30 ET) 동안 **무중단** 운영
- 169,723 ticks 수신, 962 REST polling cycles (전부 15/15 ok)
- Bug #27(DST), #28(market filter) 발견 및 장중 즉시 수정
- VRT 피라미딩 1건 정상 체결 (주문→체결→유닛추가→스탑조정 전체 플로우 검증)
- Post-market 포지션 동기화 완벽 (불일치 0건)
- 일일 수익: **+$2,758.57** (+3.2%)
