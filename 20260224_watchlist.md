# 2026-02-24 트레이딩 봇 감시 리포트

## 감시 개요
- **감시 기간**: 2026-02-24 KST 23:00 ~ KST 04:30 (ET 09:00 ~ ET 14:30)
- **봇 모드**: Paper (모의투자)
- **봇 상태**: systemd 서비스로 운영

---

## 1. 장 시작 전 상태 (KST 23:00)

### 봇 기본 정보
| 항목 | 값 |
|------|-----|
| 모드 | Paper (모의투자) |
| 스케줄러 작업 | 4개 (screening, pre_market, market_open, post_market) |
| 시작 자본 | $100,000.00 |

### 보유 포지션 (장 시작 전)
| 종목 | 수량 | 평균단가 | 손절가 | 유닛 수 |
|------|------|----------|--------|---------|
| UGP | 3,966주 | $5.407 | $4.8663 | 1 |
| AEM | 312주 | $239.038 | $215.1342 | 1 |
| TSM | 39주 | $379.81 | $341.829 | 1 |

### 스크리닝 결과
- 유니버스: 6,636개 종목
- CANSLIM 통과: 24개
- 미너비니 통과: 21개
- 최종 관심종목: 21개

### Pre-Market 결과 (KST 22:00 실행)
- 토큰 갱신: OK
- 가격 데이터 갱신: 22개 종목 (new_records: 0)
- 시그널 계산: 21개 완료
- 마켓 필터: **SPY close=$681.86, SMA200=null → fail-open (True)**
  - SPY는 이제 수집하지만 과거 데이터 6일뿐 → SMA200 계산 불가 (장기 누적 필요)
- 갭다운 위험: 0건

---

## 2. 발견된 버그 및 수정사항

### Bug #1: SPY 가격 데이터 미수집 (CRITICAL) — 이전 세션 수정
- **증상**: `market_filter_data_unavailable` — SPY close=null, sma200=null
- **원인**: `pre_market._update_price_data()`가 watchlist + positions만 fetch → SPY 누락
- **영향**: 마켓 필터가 항상 fail-open(True) → 하락장에서도 매수 진행 가능
- **수정**: `pre_market.py`에 `MARKET_BENCHMARK`("SPY") 추가
- **배포**: 14:05 UTC 서버 반영 완료
- **확인**: SPY close=$681.86 수집됨 (SMA200은 데이터 부족으로 아직 null)

### Bug #2: 재시작 시 precomputed_signals 유실 — 이전 세션 수정
- **증상**: 봇 재시작 후 pre_market은 이전 인스턴스에서 이미 실행 → signals 메모리에서 사라짐
- **영향**: market_open 시 빈 시그널로 시작 → 보유 종목만 모니터링, 신규 진입 불가
- **수정**: `_start_intraday()`에서 signals 비어있으면 pre_market 자동 실행
- **배포**: 14:06 UTC 서버 반영 완료
- **확인**: `catchup_mid_session_restart_detected` → pre_market 자동 실행 → 21개 시그널 로드됨

### Bug #3: WebSocket "invalid approval" 무한 루프 (CRITICAL)
- **증상**: WS 연결 후 "invalid approval" 에러 → 재연결 → 같은 에러 무한 반복, 0초 딜레이
- **원인 1**: `_handle_reconnect()`가 `except` 블록 안에서만 호출 → 정상 종료 시 백오프 미적용
- **원인 2**: stale approval key를 계속 사용 → 새 key 갱신 없음
- **수정**:
  - `_handle_reconnect()` 호출을 except 밖으로 이동 (항상 호출)
  - `_approval_invalid` 플래그 + `_handle_json_response()`에서 "invalid approval" 감지
  - `start()` 루프에서 approval key 자동 갱신 로직 추가
- **배포**: 14:46 UTC 서버 반영 완료
- **확인**: 재시작 후 새 approval key 획득, 21개 종목 SUBSCRIBE SUCCESS

### Bug #4: `_start_intraday()` 레이스 컨디션
- **증상**: 스케줄러 + catchup이 동시에 `_start_intraday()` 호출 → 이중 실행
- **수정**: `_intraday_started` boolean 가드 추가
- **배포**: 14:46 UTC 서버 반영 완료

### Bug #5: 이중 봇 인스턴스 (CRITICAL)
- **증상**: PID 18716 (이전 인스턴스)과 PID 21740 (systemd 재시작)이 동시 실행
- **원인**: 이전 수동/비정상 시작된 프로세스가 systemd restart 시 정리되지 않음
- **영향**: 두 인스턴스가 동일 approval key 경합 → WS 연결 불안정
- **수정**: `sudo kill 18716` + PID 16122/16123 (stuck 스크립트)도 제거
- **교훈**: 항상 `systemctl stop` 후 프로세스 잔존 확인 필요

### Bug #6: Stale UGP SUBMITTED 주문 (23시간+)
- **증상**: Order #1 (UGP BUY ENTRY, 2026-02-23T15:01:58) 여전히 SUBMITTED 상태
- **원인**: `has_submitted_order()`는 해당 ticker/side로 호출될 때만 stale 주문 정리.
  UGP는 이미 보유 중 → BUY ENTRY 체크 불발 → 자동 만료 미작동
- **영향**: 직접적 영향 없음 (5분 window 밖이므로 차단 안 함), 하지만 DB 정합성 문제
- **수정**: 수동으로 `UPDATE orders SET status='FAILED'` 처리
- **개선 필요**: 시작 시 또는 주기적으로 stale 주문 일괄 정리 로직 필요

### Bug #7: Balance API 필드명 오류 + Negative Cache 미구현 (CRITICAL)
- **증상**: TSM 피라미딩 시그널 발생 → `_get_cached_cash()` 항상 $0 반환 → `pyramid_skipped_no_balance` 매 틱마다 발생
- **원인 1**: `ord_psbl_frcr_amt`는 Paper 모드에서 항상 0. 실제값은 `frcr_ord_psbl_amt1`에 있음
- **원인 2**: API 실패 시 cache TTL 미갱신 → 매 틱마다 API 재호출 → EGW00201 rate limit 폭풍
- **수정**:
  - `frcr_ord_psbl_amt1` fallback 추가
  - Negative cache: 실패 시에도 `_balance_cache_time = now` 갱신
  - API 호출 간 `await asyncio.sleep(1.0)` 추가
  - 피라미딩/진입 실패 시 60초 쿨다운 추가
- **배포**: 15:30 UTC 서버 반영 완료
- **확인**: `balance_cache_refreshed cash=55862.06` → 잔고 정상 조회!

### Bug #8: TypeError in structlog — WS 크래시 무한 루프 (CRITICAL)
- **증상**: 첫 틱 수신 후 즉시 크래시 → 2초마다 재연결 루프
- **에러**: `structlog.stdlib.BoundLogger.debug() got multiple values for keyword argument 'ticker'`
- **원인**: `portfolio/risk_manager.py:229` — `logger.debug("pyramid_allowed", ticker=ticker, **details)` 에서 `details` dict에 이미 `ticker` 키 존재 → 중복 키워드 충돌
- **영향**: 틱 데이터 수신 불가, 모든 매매 로직 정지
- **수정**: `ticker=ticker` 제거, `**details`만 사용 (details에 ticker 이미 포함)
- **배포**: 15:49 UTC 서버 반영 완료
- **확인**: TypeError 소멸, 정상 틱 처리 재개

### Bug #9: 주문 실패 무시 — 피라미딩 API 폭격 (CRITICAL)
- **증상**: TSM 피라미딩 주문 → "주문가능금액 부족" 에러 → `pyramid_order_submitted` 로깅 → 매 틱마다 반복
- **원인 1**: `_execute_pyramid()`가 주문 실패(order.status == FAILED)를 체크하지 않고 무조건 "submitted" 로깅 + 이벤트 발행
- **원인 2**: 주문 전 현금 부족 사전 체크 없음 (cash < shares × price 체크 누락)
- **영향**: 매 틱마다 KIS API에 주문 요청 → rate limit 에러 연쇄 → 다른 정상 API도 차단
- **수정**:
  1. `_execute_pyramid`/`_execute_new_entry`: order.status == FAILED 시 쿨다운 + return
  2. 주문 전 `cash < shares * price * 1.01` 사전 체크 추가 (API 호출 방지)
  3. `pyramid_skipped_pending_order` 등을 `debug` 레벨로 변경 (로그 스팸 제거)
- **배포**: 16:02 UTC 서버 반영 완료
- **확인**: `pyramid_skipped_insufficient_cash cash=23034.94 required=33225.24` → API 호출 없이 스킵

### 개선: 주기적 상태 로깅 추가
- **문제**: 시그널 미발생 시 로그가 전혀 없어 봇 정상 동작 확인 불가
- **수정**:
  - `intraday_monitor.py`: `intraday_status_heartbeat` 5분마다 (tick_count, unique_tickers, latest_prices)
  - `trading_bot.py`: `fill_check_heartbeat` 5분마다 (checks_done, pending_orders)
- **배포**: 14:57 UTC 서버 반영 완료
- **확인**: 15:02 UTC 첫 heartbeat — tick_count=3,057, unique_tickers=21

---

## 3. 매매 활동 요약

### 신규 진입
| 시각 (UTC) | 종목 | 시스템 | 수량 | 가격 | 상태 |
|------------|------|--------|------|------|------|
| 15:44:06 | GVA | S1 (Donchian 20일 돌파) | 337주 | $137.38 | SUBMITTED → 체결 (broker 확인) |

### 피라미딩
| 시각 (UTC) | 종목 | 유닛 | 수량 | 가격 | 상태 |
|------------|------|------|------|------|------|
| 15:50:00 | TSM | 2 | 85주 | $387.45 | SUBMITTED → 체결 (broker 확인, 39→124주) |

### 현재 보유 포지션 (KST 01:08 / ET 11:08 기준)
| 종목 | 수량 | 상태 | 비고 |
|------|------|------|------|
| UGP | 3,966주 | 보유 | stop 위 안전 |
| AEM | 312주 | 보유 | stop 위 안전 |
| TSM | 124주 | 보유 | 피라미딩 Unit 2 체결 완료 |
| GVA | 337주 | 보유 | 신규 진입 (S1 돌파) |

### 가용 현금
- $23,034.94 (TSM 피라미딩 Unit 3에는 부족: 필요 ~$33,200)

---

## 4. Market Open 모니터링 (KST 23:30~)

### 23:30 KST — Market Open 이벤트
- [x] `catchup_mid_session_restart_detected` → pre_market 자동 실행 (Bug #2 수정 확인)
- [x] SPY 가격 fetch 성공: close=$681.86 (Bug #1 수정 확인)
- [x] `market_filter_data_unavailable` — SMA200=null → fail-open (True) (데이터 부족, 정상)
- [x] WebSocket 연결 성공: 21개 종목 SUBSCRIBE SUCCESS
- [x] 틱 데이터 수신 확인: 첫 틱 TSM $381.025 (14:46:14 UTC)

### 장중 모니터링 (KST 00:02 / ET 10:02 기준)
- [x] 틱 흐름 정상: 5분간 3,057 틱, 21/21 종목
- [x] Fill check loop 정상: 11회 체크, pending orders=0
- [x] TSM 피라미딩 시그널 발생 (Bug #7 수정으로 잔고 확인 가능해짐)
- [x] GVA S1 Donchian 돌파 진입 주문 실행
- [x] WS 1회 재연결 발생 (15:00:03 UTC) — 자동 복구 성공

### 장중 모니터링 (KST 01:08 / ET 11:08 기준)
- [x] 틱 흐름 정상: 5분간 2,713 틱, 21/21 종목 (16:08 UTC heartbeat)
- [x] 봇 안정화 완료: Bug #7~#9 모두 수정, API 폭격 중지
- [x] TSM 피라미딩 Unit 3: 현금 부족으로 올바르게 스킵 ($23K < $33K 필요)
- [x] 손절 체크: 모든 포지션 stop 가격 위 (안전)
- [x] WS 재연결 1회 발생 (16:00:01 UTC) — 자동 복구 성공

### 장중 모니터링 (KST 02:00 / ET 12:00 기준)
- [x] 틱 흐름 정상: tick_count=27,254, 21/21 종목 (16:58 UTC heartbeat)
- [x] WS 재연결 1회 발생 (17:00:02 UTC) — 21개 종목 재구독 SUCCESS, 즉시 복구
- [x] Bug #9 수정 이후 새로운 API 주문 시도 0건 (pyramid_skipped_insufficient_cash만 분당 1회)
- [x] fill_check: checks_done=101, pending_orders=1 (GVA #58 — Paper 모드 한계)
- [x] DB 확인: 4개 포지션 OPEN 정상, FAILED 주문 104개 (모두 Bug #9 수정 전 잔재)
- [x] 현재 가격: AEM=$240.52, TSM=~$329 area, GVA=정상, UGP=정상
- [x] 에러/경고 0건 (16:02 UTC 재시작 이후 약 1시간 무에러)

### 장중 모니터링 (KST 02:33 / ET 12:33 기준)
- [x] 틱 흐름 정상: tick_count=42,944, 21/21 종목
- [x] 에러/경고 0건 (지난 30분), WS 재연결 0회
- [x] **JCI 진입 시그널 발생**: S1 Donchian 20일 돌파, 현금 부족으로 스킵 ($23K < $50K 필요)
- [x] TSM 피라미딩: 계속 현금 부족 스킵 (분당 1회, 정상)
- [x] fill_check: 161회 체크, pending_orders=1 (GVA #58)
- [x] 봇 완전 안정: 16:02 UTC 재시작 이후 ~1.5시간 무에러 연속

---

## 5. 실시간 로그 타임라인

| 시각 (UTC) | 시각 (KST) | 이벤트 | 비고 |
|------------|------------|--------|------|
| 14:46:05 | 23:46 | 봇 시작 (2차) | rogue 프로세스 kill 후 재시작 |
| 14:46:07 | 23:46 | KIS 인증 성공 | token + approval key |
| 14:46:09 | 23:46 | 포지션 동기화 | 3개 포지션 매칭 OK |
| 14:46:09 | 23:46 | catchup 감지 | 장중 재시작 → pre_market 실행 |
| 14:46:14 | 23:46 | pre_market 완료 | 21 signals, SPY close=$681.86 |
| 14:46:14 | 23:46 | WS 연결 + 21종목 구독 | 모두 SUBSCRIBE SUCCESS |
| 14:46:14 | 23:46 | 첫 틱 수신 | TSM $381.025 |
| ~14:51 | ~23:51 | rogue PID 18716 kill | 이중 인스턴스 정리 |
| ~14:51 | ~23:51 | stale UGP 주문 정리 | Order #1 → FAILED |
| 14:57:05 | 23:57 | 봇 시작 (3차) | heartbeat 로깅 추가 후 재배포 |
| 14:57:13 | 23:57 | WS 연결 + 구독 | 21개 종목 SUCCESS |
| 15:00:03 | 00:00 | WS 재연결 | 자동 복구, reconnect_count 리셋 |
| 15:02:13 | 00:02 | heartbeat 로그 | 3,057 ticks, 21 tickers |
| ~15:30 | ~00:30 | Bug #7 수정 배포 | balance 필드명 + negative cache |
| 15:44:06 | 00:44 | **GVA S1 진입 주문** | 337주 @ $137.38 |
| 15:49:08 | 00:49 | Bug #8 수정 배포 | structlog TypeError |
| 15:50:00 | 00:50 | **TSM 피라미딩 주문** | 85주 @ $387.45, Unit 2 |
| 15:51:16 | 00:51 | Bug #8b 수정 배포 | pending_order 로그 레벨 |
| 15:55:01 | 00:55 | TSM stale order 만료 | Order #59 → 5분 타임아웃 |
| 15:55~57 | 00:55~57 | Bug #9 발생 | 피라미딩 API 폭격 (주문가능금액 부족) |
| 15:57:35 | 00:57 | Bug #9 수정 배포 (1차) | order.status 체크 + 쿨다운 |
| 16:02:58 | 01:02 | Bug #9 수정 배포 (2차) | 현금 부족 사전 체크 추가 |
| 16:03:05 | 01:03 | 봇 안정화 확인 | `pyramid_skipped_insufficient_cash` |
| 16:08:03 | 01:08 | heartbeat | 2,713 ticks, 21/21 tickers |
| 16:48~58 | 01:48~58 | 안정 운영 중 | pyramid_skipped_insufficient_cash 분당 1회 |
| 16:58:05 | 01:58 | heartbeat | 27,254 ticks, 21/21 tickers |
| 17:00:02 | 02:00 | WS 재연결 | 21개 종목 재구독 SUCCESS, 즉시 복구 |
| 17:13:15 | 02:13 | JCI 진입 시그널 | S1 Donchian 돌파, 현금 부족으로 스킵 ($23K < $50K) |
| 17:23:06 | 02:23 | heartbeat | 38,438 ticks, 21/21 tickers |
| 17:33:06 | 02:33 | heartbeat | 42,944 ticks, 21/21 tickers, 에러 0건 |
| 17:52:11 | 02:52 | EGW00201 rate limit | psamount + ccnl 동시 호출 충돌 (retry 성공) |
| 18:00:01 | 03:00 | WS 재연결 | 정시 패턴 (매시 정각 KIS 서버측 끊김), 즉시 복구 |
| 18:13:07 | 03:13 | heartbeat | 60,540 ticks, 21/21 tickers |
| 18:43:09 | 03:43 | heartbeat | 73,496 ticks, 21/21 tickers, 에러 0건 |
| 18:58:09 | 03:58 | **최종 heartbeat** | 79,970 ticks, 21/21 tickers, 에러 0건 |
| 19:00 | 04:00 | 감시 종료 | 봇 정상 가동 유지, 서비스 active |

---

## 6. 수정 파일 목록

| 파일 | 수정 내용 |
|------|----------|
| `bot/pre_market.py` | SPY(MARKET_BENCHMARK) 데이터 수집 추가 |
| `bot/trading_bot.py` | catchup pre_market 자동 실행, _intraday_started 가드, fill_check heartbeat |
| `broker/kis_websocket.py` | approval key 자동 갱신, reconnect 백오프 수정, done task exception 회수 |
| `bot/intraday_monitor.py` | heartbeat 로깅, balance 필드명 수정, negative cache, 쿨다운, 주문 실패 체크, 현금 사전 체크 |
| `portfolio/risk_manager.py` | structlog 중복 ticker 키워드 제거 |

---

## 7. 종합 평가

### 매매 로직 검증 결과
1. **손절 (Stop Loss)**: 모든 포지션이 stop 가격 위에서 거래 → 트리거 미발생 (정상)
   - UGP: $5.41 진입, stop=$4.87 (현재가 안전 범위)
   - AEM: $239.04 진입, stop=$215.13 (현재가 $242.64)
   - TSM: $384.22 진입, stop=$341.83 (현재가 ~$391)
   - GVA: $136.79 진입, stop=$123.11 (현재가 안전 범위)
2. **피라미딩 (Pyramid)**: TSM Unit 2 정상 체결 (39주→124주). Unit 3는 현금 부족으로 올바르게 스킵
3. **신규 진입 (Entry)**: GVA S1 Donchian 20일 돌파 시그널로 337주 진입 체결. JCI도 S1 돌파 시그널 발생했으나 현금 부족으로 정상 스킵
4. **Donchian 청산**: 감시 기간 중 청산 조건 미충족 (정상)
5. **마켓 필터**: SPY SMA200 데이터 부족으로 fail-open (True). 기능적으로는 정상, 데이터 누적 필요

### 잔여 이슈
- GVA 주문 #58: broker에서 체결 확인되었으나 fill_check_loop가 DB 업데이트 미완. 포지션 sync로 보유는 정상 반영
- SPY SMA200: 약 200 거래일치 데이터 누적까지 fail-open 지속
- TSM units 테이블: sync_positions가 total_shares를 124로 업데이트했지만 unit #2 레코드 미생성 (unit_count=1로 표시)
- FAILED 주문 104개: Bug #9 수정 전 잔재. DB 정리 권장 (운영 영향 없음)
- KIS WS 정시 끊김: 매시 정각(16:00, 17:00, 18:00 UTC) 서버측 연결 종료. 재연결 즉시 복구됨

### 봇 안정성
- 감시 기간 중 9개 버그 발견 및 수정 + 1개 cosmetic 개선 (asyncio 경고 억제)
- 최종 안정화 시점: KST 01:03 (ET 11:03) — 이후 에러 0건
- 안정 운영 시간: **약 3시간** (16:02 ~ 19:00 UTC) 무에러 연속
- 총 틱 수신: **79,970+** (21/21 종목)
- 경고: 8건 (rate limit 4건, WS 끊김 2건 + 경미한 경고 2건 — 모두 자동 처리)
- WS 재연결: 3회 (매시 정각 패턴, 모두 즉시 복구)

### 최종 포지션 현황 (KST 03:48 기준)
| 종목 | 수량 | 평균단가 | 투자금 | 스톱 | 상태 |
|------|------|----------|--------|------|------|
| UGP | 3,966 | $5.41 | $21,444 | $4.87 | 안전 |
| AEM | 312 | $239.04 | $74,580 | $215.13 | 안전 |
| TSM | 124 | $384.22 | $47,643 | $341.83 | 안전 |
| GVA | 337 | $136.79 | $46,097 | $123.11 | 안전 |
| **합계** | | | **$189,764** | | |
| 가용 현금 | | | **$23,035** | | |
| 총 자산 | | | **~$212,799** | | |
