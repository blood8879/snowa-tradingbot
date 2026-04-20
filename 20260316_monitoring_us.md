# 2026-03-16 US 장 감시 내역

## 감시 시작: KST 21:14

## 상태 요약

### Daily Screening (KST 20:20 시작)
- `needs_update()` 코드 배포 후 첫 실행
- 4,580개 stale 종목 감지 → 전체 유니버스 재무데이터 갱신 중
- 진행 속도: ~50종목/2.5분
- **예상 완료: KST 00:00~00:30** (약 3시간 소요)
- 원인: 첫 실행이라 모든 종목의 최신 분기 데이터 없음 → needs_update() True 반환

### 영향
- US pre_market (KST 21:00 ET 08:00): 스크리닝 진행 중이라 대기
- US 장 시작 (KST 22:30 ET 09:30): 스크리닝 완료 전
- `_check_and_recover_missed_jobs()`가 스크리닝 완료 후 자동 복구 예정

### 조치사항
- [x] `MAX_STALE_TARGETS = 500` 상한 추가 (로컬, 스크리닝 완료 후 배포 예정)
- [ ] 스크리닝 완료 확인
- [ ] pre_market 자동 실행 확인
- [ ] intraday 모니터 정상 시작 확인
- [ ] 대시보드 US 탭 정상 확인
- [ ] CANSLIM 최신 재무데이터 반영 확인
- [ ] 매수/매도 시그널 정상 확인

## 진행 로그

| 시각 (KST) | 이벤트 | 상세 |
|-----------|--------|------|
| 20:20 | daily_screening 시작 | market=US |
| 21:12 | bulk_fetch 1000/4580 | 8,687 records, 81 empty |
| 21:16 | bulk_fetch 1050/4580 | 9,122 records, 88 empty |
| 21:17 | 최신 종목: CREX | 알파벳순 C 종목 진행 중 |
| 21:18 | bulk_fetch 1100/4580 | 9,595 records, 90 empty |
| 21:23 | bulk_fetch 1200/4580 | 10,536 records, 98 empty |
| 21:24 | 대시보드 API 확인 | 모든 탭 정상 동작 |
| 21:24 | 레짐: YELLOW | 브레드스 44.9%, ROC +1.3% |
| 21:24 | 워치리스트 | 13종목, 12개 Q4 기준 (CVE만 Q3) |
| 21:24 | 포지션 | CVE, EZPW, ISSC, VRT — 총 6유닛 |
| 22:00 | bulk_fetch 1850/4580 | 16,224 records, 158 empty |
| 22:11 | bulk_fetch 2100/4580 | 18,331 records, 180 empty |
| 22:21 | bulk_fetch 2300/4580 | 20,050 records |
| 22:28 | bulk_fetch 2600/4580 | 22,667 records |
| 22:30 | US 장 시작 | APScheduler market_open 크론 정상 실행 |
| 22:30 | intraday 시작 | WS 13종목 구독, REST 폴링 시작 |
| 22:34 | **봇 재시작** | systemd가 OOM으로 중지 → 즉시 재시작 (메모리 339.6M+스왑 100.2M) |
| 22:34 | 스크리닝 중단 | 2,620/4,580에서 중단 (약 57%) |
| 22:35 | catchup 자동복구 | pre_market + intraday 자동 실행, WS 재구독 |
| 22:35 | 레짐 확인 | YELLOW (브레드스 44.9%, ROC +1.8%) |
| 22:36 | 정상 운영 시작 | REST polling cycle, tick 수신 정상 |
| 22:47 | KIS rate limit | 초당 거래건수 초과 (자동 복구) |
| 22:51 | heartbeat | 4,252 ticks, 13종목, 에러 0 |

| 00:14 | 수동 스크리닝 Step 4 | 580종목 fetch (500 stale cap 적용) |
| 00:35 | **스크리닝 완료** | CANSLIM 31종목 → Minervini 14종목 → 워치리스트 14종목 |
| 00:43 | 워치리스트 확인 | 전 종목 2025-12-31 기준, UGP/OUT 탈락, COCO/EIX/GCT 신규 |

## 스크리닝 결과 검증

| 항목 | 결과 |
|------|------|
| 전 종목 Q4(2025-12-31) 반영 | ✓ |
| UGP 탈락 (EPS fallback → C필터 10.6%) | ✓ 예측 일치 |
| OUT 탈락 (Q4 EPS 22% < 25%) | ✓ 예측 일치 |
| CVE Q4 반영 (EPS성장 537.5%) | ✓ |
| 신규 종목: COCO, EIX, GCT | Q4 데이터로 새로 통과 |
| MAX_STALE_TARGETS=500 캡 정상 동작 | ✓ (3,538 → 500으로 제한) |

## 발견된 이슈

### Issue #1: OOM으로 인한 봇 재시작
- **원인**: needs_update() 첫 실행으로 4,580종목 bulk fetch → 메모리 339.6M + 스왑 100.2M → systemd 강제 재시작
- **영향**: 스크리닝 57%에서 중단, 나머지 종목 재무데이터 미갱신
- **조치**: MAX_STALE_TARGETS=500 상한 추가 (로컬 준비완료, 장후 배포)
- **복구**: catchup 자동복구로 intraday 정상 시작
