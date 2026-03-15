# 2026-03-03 한국장 트레이딩 봇 감시 리포트

## 감시 개요
- **감시 기간**: 2026-03-03 KST 07:00 ~ KST 16:05
- **봇 모드**: Paper (모의투자)
- **봇 상태**: systemd 서비스로 운영 (US 장 이후 연속 운영)
- **결과**: Bug 3건 수정 (Bug #4 HIGH, #5 MEDIUM, #6 LOW), 봇 안정 운영 확인

---

## 1. 장 시작 전 상태

### KR 스케줄
| 이벤트 | 시각 (KST) | 실제 실행 | 상태 |
|--------|-----------|----------|------|
| kr_daily_screening | 07:00 | 07:00:00 | 완료 (08:51, 6662초 소요) |
| kr_pre_market | 08:00 | 08:00:00 | 완료 (2초 소요) |
| kr_market_open | 09:00 | 09:00:00 | 실패 → Bug #4 수정 후 09:09 catchup |
| kr_post_market | 16:00 | 16:00:00 | 완료 (5.54초 소요, Bug #6 발견) |

### KR Pre-Market 결과 (KST 08:00)
- 마켓 필터: **True** (통과)
- 보유 포지션: **5개**
- 시그널 계산: **32개** 완료
- 관심종목: **27개**

### 참고: pykrx 로그 노이즈
- KR daily_screening 중 pykrx 라이브러리가 KRX API에서 일부 종목의 fundamental 데이터를 가져올 때 에러 발생
- `JSONDecodeError` (KRX 빈 응답) 및 `NoneType` (ISIN 조회 실패) — pykrx 라이브러리 내부 문제
- 코드에 `except Exception` 핸들링 있어 스크리닝은 계속 진행됨 (봇 크래시 아님)
- pykrx의 `logging.info(args, kwargs)` 호출이 structlog와 충돌하여 저널 로그가 매우 noisy함

---

## 2. 발견된 버그 및 수정사항

### Bug #4: `Position` 모델에 `market` 필드 누락 (HIGH) — 장 오픈 실패
- **증상**: KR market_open (09:00) 시 `'Position' object has no attribute 'market'` → `kr_intraday_start_failed`
- **원인**: DB `positions` 테이블에는 `market` 컬럼이 있지만 (ALTER TABLE로 추가), `Position` 데이터클래스와 `_row_to_position()` 매퍼에 누락
- **영향**: KR 장 오픈 시 intraday 모니터링이 시작되지 않음 → KR 장중 매매 불가
- **수정**:
  - `core/models.py`: `Position` 데이터클래스에 `market: str = "US"` 필드 추가
  - `portfolio/position_manager.py`: `_row_to_position()`에 `market=row[15]` 매핑 추가 (DB 컬럼 인덱스 15)
- **배포**: 09:09 KST 서버 반영, 봇 재시작
- **확인**:
  ```
  catchup_kr_mid_session_restart_detected
  kr_pre_market_complete: market_filter=True, signals=32, watchlist=27
  kr_intraday_started: tickers_count=32
  ws_connected + 32개 SUBSCRIBE SUCCESS
  ws_first_tick_received: 000660 (SK하이닉스) ₩1,028,000
  ```

### Bug #5: 진입 실패 시 로그 스팸 + API 폭풍 (MEDIUM)
- **증상 1**: 272210 종목 진입 3회 실패 후 `entry_blocked_too_many_failures` 경고가 매 틱마다 반복 출력 (5초에 30회+)
- **원인 1**: `_entry_blocked_today` set 없이 매 틱마다 DB 쿼리 + 경고 로그 반복
- **증상 2**: 잔고 부족 상황에서 여러 종목(272210, 064350, 267250)이 각각 3회 × 3 retry = 종목당 9 API 호출 낭비
- **원인 2**: 글로벌 진입 차단 없이 종목별로만 쿨다운 적용
- **수정**:
  - `bot/intraday_monitor.py`:
    1. `_entry_blocked_today: set[str]` 추가 — 3회 실패 종목은 하루 종일 차단, 로그 1회만 출력
    2. `_global_entry_block_until` 추가 — 주문 실패 시 모든 진입 5분간 일괄 차단
- **배포**: 09:14 KST (1차), 09:17 KST (2차, 글로벌 차단 추가)
- **확인**:
  ```
  entry_blocked_too_many_failures: ticker=272210 (1회만 출력 후 무음)
  entry_blocked_too_many_failures: ticker=064350 (1회만 출력 후 무음)
  global_entry_blocked: ticker=267250, block_seconds=300.0 (모든 진입 5분 차단)
  이후 entry_order_failed: 0건 (API 낭비 완전 차단)
  ```

### Bug #6: KR 미체결 주문 조회 Paper 모드 미지원 (LOW)
- **증상**: post_market (16:00) 시 `[90000000] 모의투자에서는 해당업무가 제공되지 않습니다.` 에러 (3회 retry 후 실패)
- **원인**: `_kr_get_unfilled_orders()`가 `VTTC8036R` TR 사용 → KIS Paper 모의투자에서 미지원
- **영향**: 에러 로그 발생하나 try/except로 핸들링되어 cancelled=0으로 정상 진행 (크래시 아님)
- **수정**: `broker/kis_rest.py` — `_kr_get_unfilled_orders()`에서 `is_paper` 시 빈 리스트 즉시 반환
- **배포**: 16:03 KST 서버 반영 (다음 실행 시 적용, 봇 재시작 불필요)

---

## 3. 장 오픈 모니터링

### KST 09:00 — Market Open 이벤트
- [x] 스케줄러 kr_market_open 트리거 확인 (09:00 → Bug #4로 실패, 09:09 catchup으로 성공)
- [x] KR pre_market signals 로드 확인 (32개 시그널)
- [x] WebSocket 연결 + KR 종목 구독 확인 (32개 전부 SUBSCRIBE SUCCESS)
- [x] 첫 틱 수신 확인 (000660 ₩1,028,000)

### KST 16:00 — Post-Market 이벤트
- [x] 스케줄러 kr_post_market 트리거 확인 (16:00:00 정시)
- [x] kr_intraday 모니터 정지 확인 (`kr_intraday_stopped`)
- [x] 포지션 동기화 완료 (5개 matched, 불일치 0)
- [x] 일일 리포트 생성 (equity=₩10,000,000, daily_pnl=₩0, positions=5)
- [x] post_market 완료 (5.54초 소요)

---

## 4. 매매 활동 요약

### 장중 진입 시도 (잔고 부족으로 전부 실패)
| 종목 | 시그널 | 가격 | 수량 | 결과 | 비고 |
|------|--------|------|------|------|------|
| 272210 | entry | ₩136,500~139,100 | 7주 | FAILED | 모의투자 주문가능금액 부족 (3회) |
| 064350 | entry | ₩257,000~258,500 | 4주 | FAILED | 모의투자 주문가능금액 부족 (2회) |
| 267250 | entry | ₩310,000~314,500 | 4주 | FAILED | 모의투자 주문가능금액 부족 (1회) → 글로벌 차단 발동 |

> **참고**: Paper 모의투자 계좌의 주문가능금액이 0원 (기존 US 포지션에 자본 소진). `get_balance` API는 총 현금 ₩10,000,000을 리턴하지만, KIS 서버 내부 주문가능금액은 별도 관리.

### 장중 청산
- 없음 (기존 5개 포지션 유지)

### 일일 실적
- **총 자산**: ₩10,000,000
- **일일 손익**: ₩0
- **보유 포지션**: 5개
- **마켓 필터**: True (통과)

---

## 5. 장중 안정성 지표

### 봇 성능 (09:17 마지막 재시작 이후)
| 지표 | 값 | 비고 |
|------|------|------|
| 운영 시간 | ~6시간 43분 (09:17~16:00) | 재시작 0회 |
| 총 틱 수신 | 468,517 | 27개 종목 |
| fill_check | 801회 | pending_orders=0 |
| 진입 실패 | 16건 | 모두 잔고 부족, ~11:05 이후 0건 |
| WS 재연결 | 5회 | 시간당 1회 (정상) |
| 메모리 | 108~110MB | 안정 |
| 비잔고 에러 | 0건 | |

---

## 6. 실시간 로그 타임라인

| 시각 (KST) | 이벤트 | 비고 |
|------------|--------|------|
| 07:00:00 | kr_daily_screening 시작 | pykrx fundamental data 수집 시작 |
| 08:00:00 | kr_pre_market 시작 | |
| 08:00:02 | kr_pre_market 완료 | market_filter=True, signals=32, watchlist=27, positions=5 |
| 08:51:00 | kr_daily_screening 완료 | universe=3667, watchlist=27, 6662초 소요 |
| 09:00:00 | kr_market_open 실행 | `'Position' object has no attribute 'market'` → 실패 |
| 09:09:12 | **봇 재시작 (Bug #4 수정)** | catchup → pre_market + intraday 즉시 실행 |
| 09:09:12 | kr_intraday_started | 32개 종목, WS 연결 OK |
| 09:09:12 | 첫 틱 수신 | 000660 (SK하이닉스) ₩1,028,000 |
| 09:09:14~09:11:26 | 272210 진입 실패 ×3 | 모의투자 잔고 부족 |
| 09:12:37 | entry_blocked_too_many_failures 스팸 발견 | 매 틱마다 로그 반복 (Bug #5) |
| 09:14:10 | **봇 재시작 (Bug #5-1차 수정)** | _entry_blocked_today set 추가 |
| 09:14:17~09:15:25 | 064350, 267250 진입 실패 | 새 종목도 잔고 부족 |
| 09:16:48 | **봇 재시작 (Bug #5-2차 수정)** | 글로벌 진입 차단 추가 |
| 09:16:55 | global_entry_blocked 발동 | 267250 실패 → 모든 진입 5분 차단 |
| 09:17:20 | 안정 확인 | 추가 entry_order_failed 0건, 틱 정상 수신 |
| ~11:05 | 모든 시그널 종목 차단 완료 | 이후 진입 실패 0건 |
| 15:30:00 | 장 마감 | 틱 수신 사실상 정지 |
| 15:55:05 | 마지막 heartbeat | tick_count=468,517, unique_tickers=27 |
| 16:00:00 | kr_post_market 실행 | 정시 트리거 |
| 16:00:00 | kr_intraday_stopped | intraday 모니터 정상 종료 |
| 16:00:02 | post_market_sync_done | 5개 포지션 매칭, 불일치 0 |
| 16:00:05 | unfilled_processing_error (Bug #6) | VTTC8036R Paper 미지원 → try/except 처리 |
| 16:00:05 | kr_post_market_complete | equity=₩10M, daily_pnl=₩0, 5.54초 소요 |

---

## 7. 수정 파일 목록

| 파일 | 수정 내용 | 배포 시각 |
|------|----------|----------|
| `core/models.py` | Position 데이터클래스에 `market: str = "US"` 필드 추가 | 09:09 |
| `portfolio/position_manager.py` | `_row_to_position()`에 `market=row[15]` 매핑 추가 | 09:09 |
| `bot/intraday_monitor.py` | (1) `_entry_blocked_today` set, (2) `_global_entry_block_until` 글로벌 차단 | 09:14, 09:17 |
| `broker/kis_rest.py` | `_kr_get_unfilled_orders()` Paper 모드 시 빈 리스트 반환 | 16:03 |

---

## 8. 종합 평가

### 성과
- KR 장 첫 라이브 모니터링 완료 (07:00~16:05)
- 3건의 버그 발견 및 즉시 수정 (Bug #4, #5, #6)
- 마지막 재시작(09:17) 이후 ~6시간 43분 무중단 운영
- 46만+ 틱 정상 수신, 비잔고 에러 0건

### 알려진 제한사항
- Paper 모의투자 계좌의 주문가능금액이 US 포지션에 소진 → KR 진입 불가
- Paper 모드에서 KR 미체결 주문 조회 API (`VTTC8036R`) 미지원 (Bug #6으로 수정 완료)
- pykrx 라이브러리 로그 노이즈 (봇 기능에 영향 없음)

### 다음 액션
- [ ] 실전 투자 전환 시 주문가능금액 분리 확인
- [ ] pykrx 로그 억제 검토 (선택)
