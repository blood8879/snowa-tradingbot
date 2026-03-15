# 한국 장 자동매매 확장 - 작업 체크리스트

> 상위 계획: [korean-market-support.md](korean-market-support.md)
> 생성일: 2026-02-28
> 총 예상: 신규 2개 파일 + 변경 ~20개 파일, ~2,440줄

---

## Phase 1: 마켓 추상화 + KIS 국내 API (핵심 인프라)

> 목표: 코드베이스에 "마켓" 개념 도입 + KIS 국내주식 API 통합
> 예상 코드량: ~930줄

### 1.1 MarketConfig 추상화 레이어
- [ ] `config/market_config.py` 신규 생성
  - [ ] `MarketConfig` dataclass 정의 (market_id, exchanges, currency, 장시간 등)
  - [ ] `US_MARKET` 인스턴스 생성 (기존 미국 설정 이관)
  - [ ] `KR_MARKET` 인스턴스 생성 (한국 설정)
  - [ ] `get_market_config(market_id)` 헬퍼 함수
- [ ] `config/constants.py` 수정
  - [ ] `MARKET_BENCHMARK = "SPY"` → MarketConfig로 이동
  - [ ] 마켓별 독립 상수 분리

### 1.2 DB 스키마 마이그레이션
- [ ] `core/database.py` 수정
  - [ ] `watchlist` 테이블에 `market TEXT DEFAULT 'US'` 컬럼 추가
  - [ ] `positions` 테이블에 `market TEXT DEFAULT 'US'` 컬럼 추가
  - [ ] `orders` 테이블에 `market TEXT DEFAULT 'US'` 컬럼 추가
  - [ ] `daily_log` 테이블에 `market TEXT DEFAULT 'US'` 컬럼 추가
  - [ ] `daily_log` PK를 `(date, market)`으로 변경 (마이그레이션)
  - [ ] `_run_migrations()`에 새 마이그레이션 추가
  - [ ] 기존 데이터 무결성 검증 (기존 행은 모두 `US` 기본값)

### 1.3 KIS REST 국내주식 API
- [ ] `broker/kis_rest.py` 수정
  - [ ] `_get_current_price_kr(ticker)` — TR: FHKST01010100
  - [ ] `_get_daily_prices_kr(ticker, period)` — TR: FHKST01010400
  - [ ] `_place_order_kr(ticker, side, qty, price)` — TR: TTTC0802U/VTTC0802U (매수), TTTC0801U/VTTC0801U (매도)
  - [ ] `_get_balance_kr()` — TR: TTTC8434R/VTTC8434R
  - [ ] `_get_filled_orders_kr()` — TR: TTTC8001R/VTTC8001R
  - [ ] `_get_unfilled_orders_kr()` — TR: TTTC8001R/VTTC8001R
  - [ ] `_get_purchasable_amount_kr()` — TR: TTTC8908R/VTTC8908R
  - [ ] 라우터 메서드: `get_current_price(ticker, market)` → US/KR 분기
  - [ ] 라우터 메서드: `place_order(ticker, side, qty, price, market)` → US/KR 분기
  - [ ] 라우터 메서드: `get_balance(market)` → US/KR 분기
  - [ ] 호가단위(tick size) 가격 조정 함수 `_adjust_to_tick_size(price)`
  - [ ] Paper 모드 TR_ID 분기 (`TTTC` → `VTTC`)
- [ ] KIS 국내 API 호출 테스트 (Paper 모드)
  - [ ] 현재가 조회 테스트 (삼성전자 005930)
  - [ ] 일별시세 조회 테스트
  - [ ] 매수가능금액 조회 테스트
  - [ ] 모의 주문 테스트

### 1.4 KIS WebSocket 국내주식 구독
- [ ] `broker/kis_websocket.py` 수정
  - [ ] `subscribe()` 메서드에 `market` 파라미터 추가
  - [ ] 국내 TR_ID `H0STCNT0` 구독 로직
  - [ ] 국내 tr_key 형식: 6자리 종목코드 (exchange 매핑 불필요)
  - [ ] 국내 실시간 체결 데이터 파싱 (필드 구조가 해외와 다름)
  - [ ] `unsubscribe_all()` 마켓 전환 시 기존 구독 해제
  - [ ] 20종목 구독 제한 관리 (국내+해외 합계)
- [ ] WebSocket 국내 구독 테스트
  - [ ] 삼성전자(005930) 실시간 틱 수신 확인
  - [ ] 여러 종목 동시 구독 테스트

### 1.5 OrderExecutor 마켓 지원
- [ ] `broker/order_executor.py` 수정
  - [ ] `execute_entry_buy()` 마켓 파라미터 전달
  - [ ] `execute_stop_loss_sell()` 마켓 파라미터 전달
  - [ ] `check_order_fills()` 마켓별 체결 확인 API 분기
  - [ ] 호가단위 적용 (한국 주문 시 가격 조정)
  - [ ] 시장가 주문 지원 (한국은 시장가 가능, 미국은 지정가만)

### 1.6 듀얼 스케줄러
- [ ] `bot/trading_bot.py` 수정
  - [ ] 한국 장 스케줄 추가:
    - [ ] KST 07:00 — 한국 Daily Screening
    - [ ] KST 08:00 — 한국 Pre-Market
    - [ ] KST 09:00 — 한국 Market Open (WS + 장중 모니터링)
    - [ ] KST 15:30 — 한국 Market Close
    - [ ] KST 16:00 — 한국 Post-Market
  - [ ] `is_market_enabled(market)` 메서드 추가
  - [ ] 마켓별 활성화 상태를 `bot_state`에 저장
  - [ ] 비활성 마켓은 스케줄 실행 스킵
  - [ ] `_catchup_if_market_open()` 한국 장 시간 지원

### 1.7 봇 모듈 마켓 지원
- [ ] `bot/pre_market.py` 수정
  - [ ] `run_pre_market(market)` 마켓 파라미터 추가
  - [ ] 마켓별 워치리스트 로딩 (`WHERE market = ?`)
  - [ ] 마켓별 벤치마크 필터 (SPY / KODEX200)
  - [ ] 마켓별 가격 데이터 소스 분기
- [ ] `bot/intraday_monitor.py` 수정
  - [ ] `start_intraday(market)` 마켓 파라미터 추가
  - [ ] 마켓별 포지션/시그널 분리 관리
  - [ ] 마켓별 현금 잔고 조회 분기
  - [ ] Donchian exit 시간 체크: 한국 15:15~15:30 / 미국 15:45~16:00
- [ ] `bot/post_market.py` 수정
  - [ ] `run_post_market(market)` 마켓 파라미터 추가
  - [ ] 마켓별 포지션 동기화 (sync_positions)
  - [ ] 마켓별 미체결 주문 취소
  - [ ] 마켓별 일일 수익 계산

### 1.8 Phase 1 통합 테스트
- [ ] Paper 모드로 한국 장 시간에 봇 기동 테스트
  - [ ] KIS 국내 API 인증 정상 확인
  - [ ] 현재가/잔고 조회 정상 확인
  - [ ] WS 국내 종목 구독 정상 확인
  - [ ] 기존 미국 장 기능 회귀 테스트 (기존 5개 포지션 영향 없음)
- [ ] 서버 배포 + 가동 테스트

---

## Phase 2: 한국 주식 스크리닝 + 전략 적용

> 목표: KOSPI/KOSDAQ 유니버스 구축 + CANSLIM + Turtle Trading 적용
> 예상 코드량: ~710줄
> 선행 조건: Phase 1 완료

### 2.1 한국 주식 유니버스
- [ ] `data/universe_kr.py` 신규 생성
  - [ ] KOSPI 종목 리스트 로딩 (pykrx 또는 KRX API)
  - [ ] KOSDAQ 종목 리스트 로딩
  - [ ] 필터링: 관리종목/거래정지 제외
  - [ ] 필터링: 우선주/ETF/ETN/SPAC 제외
  - [ ] 필터링: 시가총액 > 1,000억원
  - [ ] 필터링: 일평균 거래량 > 50,000주
  - [ ] 캐시: `data/universe_kr_cache.csv` (7일 갱신)
  - [ ] exchange 매핑: `{ticker: "KOSPI"|"KOSDAQ"}`
- [ ] `pip install pykrx` (또는 대안) 의존성 추가
- [ ] 유니버스 로딩 테스트 (종목 수, 데이터 품질 확인)

### 2.2 한국 주식 가격 데이터
- [ ] `data/price_cache.py` 수정
  - [ ] `fetch_daily_prices_kr(ticker, days)` 추가
  - [ ] KIS API FHKST01010400 사용 (또는 pykrx 벌크)
  - [ ] 페이징 처리 (100건/요청 → 300일이면 3회 호출)
  - [ ] `daily_prices` 테이블에 저장 (기존 스키마 호환)
  - [ ] 벌크 가격 갱신 (한국 유니버스 ~2,500종목)
- [ ] 가격 데이터 정합성 테스트

### 2.3 한국 주식 재무 데이터
- [ ] `data/fundamental_data.py` 수정
  - [ ] DART OpenAPI 연동 (API Key 설정)
  - [ ] 분기 EPS 조회 (`/api/fnlttSinglAcntAll.json`)
  - [ ] 연간 EPS 조회 (5년 CAGR 계산용)
  - [ ] 매출/순이익 조회
  - [ ] `fundamentals` 테이블에 저장
- [ ] `.env`에 `DART_API_KEY` 추가
- [ ] 재무 데이터 품질 검증 (삼성전자 등 주요 종목)

### 2.4 한국 CANSLIM 스크리닝
- [ ] `screening/canslim_screener.py` 수정
  - [ ] `screen_stocks(market)` 마켓 파라미터 추가
  - [ ] 한국 유니버스 대상 CANSLIM 4대 필터 적용
    - [ ] C: 분기 EPS 성장률 >= 25%
    - [ ] A: 연간 EPS CAGR >= 25%
    - [ ] S: 일평균 거래량 >= 50,000주
    - [ ] L: RS Rating >= 80
  - [ ] 한국 기준 보조 필터 조정 (가격 >= 5,000원 등)
- [ ] `screening/rs_rating.py` 수정
  - [ ] 한국 유니버스 대비 RS Rating 별도 계산
  - [ ] `calculate_rs_ratings(prices, market)` 마켓 파라미터
- [ ] `screening/minervini_template.py` 수정
  - [ ] 마켓 파라미터 전달
  - [ ] 한국 종목 대상 Minervini 8항목 체크
- [ ] 스크리닝 결과 검증 (합리적인 종목 수 나오는지)

### 2.5 한국 마켓 필터
- [ ] `strategy/market_filter.py` 수정
  - [ ] `get_market_filter_status(market_data, market)` 마켓 파라미터
  - [ ] 한국 벤치마크: KODEX200 (069500) > 200SMA
  - [ ] KODEX200 가격 데이터 로딩 (200일 이상)
- [ ] 마켓 필터 동작 확인

### 2.6 한국 주식 특수 규칙
- [ ] `config/market_config.py` 수정
  - [ ] `TICK_SIZE_TABLE_KR` 호가단위 테이블 추가
  - [ ] `adjust_price_to_tick(price, table)` 함수
- [ ] `strategy/entry_signals.py` 수정
  - [ ] 호가단위 적용하여 진입가 조정
  - [ ] chase guard 비율 한국 시장 적합성 확인 (±30% 가격제한)
- [ ] `strategy/exit_signals.py` 수정
  - [ ] Donchian exit 시간: 한국 15:15~15:30 KST
- [ ] `portfolio/position_sizer.py` 수정
  - [ ] 원화(KRW) 기준 포지션 사이징
  - [ ] 한국 주식 1주 단위 (소수점 불가)

### 2.7 한국 Daily Screening 파이프라인
- [ ] `bot/daily_screening.py` 수정
  - [ ] `run_daily_screening(market)` 마켓 파라미터
  - [ ] 한국: KST 07:00 실행 (장 시작 2시간 전)
  - [ ] 한국 유니버스 로딩 → 가격 갱신 → CANSLIM → Minervini → 워치리스트
  - [ ] 미국 스크리닝과 독립 실행
- [ ] 전체 스크리닝 파이프라인 E2E 테스트

### 2.8 Phase 2 통합 테스트
- [ ] 한국 CANSLIM 스크리닝 전체 파이프라인 실행
- [ ] 한국 워치리스트 → 시그널 계산 → 장중 모니터링 E2E
- [ ] 미국 장 기존 기능 회귀 테스트
- [ ] Paper 모드 모의 주문 실행 테스트
- [ ] 서버 배포 + 한국 장 시간 실전 테스트

---

## Phase 3: 대시보드 + 통합 테스트

> 목표: 대시보드에서 마켓별 제어 + 전체 통합 검증
> 예상 코드량: ~800줄
> 선행 조건: Phase 2 완료

### 3.1 대시보드 API 확장
- [ ] `web/api/main.py` 수정
  - [ ] `/api/watchlist?market=KR` 마켓 필터 파라미터 추가
  - [ ] `/api/positions?market=KR` 마켓 필터 파라미터 추가
  - [ ] `/api/trades?market=KR` 마켓 필터 파라미터 추가
  - [ ] `POST /api/market/{market_id}/toggle` 마켓 on/off API
  - [ ] `GET /api/market/status` 마켓별 상태 조회 API
  - [ ] `/api/performance?market=KR` 마켓별 수익률 API

### 3.2 프론트엔드 마켓 선택기
- [ ] 헤더에 마켓 토글 UI (US / KR / 전체)
- [ ] 포지션 페이지: 마켓별 필터 탭
- [ ] 워치리스트 페이지: 마켓별 필터 탭
- [ ] 주문내역 페이지: 마켓별 필터 탭
- [ ] 대시보드 홈: 마켓별 요약 카드
  - [ ] US: equity, positions, daily P&L
  - [ ] KR: equity, positions, daily P&L
- [ ] 마켓별 on/off 스위치 (설정 페이지)
- [ ] 마켓별 수익률 차트

### 3.3 통합 테스트
- [ ] **단위 테스트**
  - [ ] KIS 국내 REST API mock 테스트
  - [ ] 호가단위 계산 정확성 테스트
  - [ ] MarketConfig 파라미터 검증
  - [ ] 마켓별 스케줄러 독립 동작 테스트
- [ ] **통합 테스트 (Paper 모드)**
  - [ ] 한국 장 시간: 스크리닝 → 시그널 → 모니터링 → 주문
  - [ ] 미국 장 시간: 기존 동작 회귀 테스트
  - [ ] 양 마켓 동시 포지션 관리
  - [ ] 대시보드 마켓 토글 동작 확인
- [ ] **안정성 테스트**
  - [ ] 24시간 연속 가동 (한국 장 → 미국 장 전환)
  - [ ] WS 연결 관리 (20종목 제한 준수)
  - [ ] 마켓 토글 on/off 시 정상 전환
  - [ ] 메모리 누수 확인 (24시간+ 가동)
- [ ] **서버 배포 + 실전 Paper 운용**
  - [ ] 한국 장 1일 Paper 운용 관찰
  - [ ] 미국 장 1일 Paper 운용 관찰 (회귀 확인)
  - [ ] 감시 보고서 작성

---

## 진행 상황 요약

| Phase | 상태 | 완료 항목 | 전체 항목 | 진행률 |
|-------|------|----------|----------|--------|
| Phase 1: 인프라 | 미시작 | 0 | 50 | 0% |
| Phase 2: 스크리닝 | 미시작 | 0 | 38 | 0% |
| Phase 3: 대시보드 | 미시작 | 0 | 25 | 0% |
| **합계** | **미시작** | **0** | **113** | **0%** |

---

## 메모

- Phase 1 완료 후 한국 장 시간에 Paper 테스트로 기본 동작 검증
- Phase 2 완료 후 CANSLIM 스크리닝 품질 검증 (합리적인 종목 수 확인)
- Phase 3 완료 후 1주일 Paper 운용으로 안정성 확인 후 Live 전환 검토
- 각 Phase 완료 시 서버 배포 + 실전 테스트 필수
