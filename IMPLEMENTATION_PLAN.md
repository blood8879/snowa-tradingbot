# CANSLIM x Turtle Trading Bot - Implementation Plan

> **Project**: snowa_tradingbot
> **Language**: Python 3.11+
> **Broker**: Korea Investment Securities (한국투자증권) Open API
> **Strategy**: CANSLIM 종목 선정 + Turtle Trading 매매 실행
> **Author**: Auto-generated from strategy analysis
> **Date**: 2026-02-14

---

## 0. 의사결정 요약 (Decision Log)

모든 구현 결정의 근거를 기록한다. 애매한 부분 없이 확정된 사항만 포함.

| # | 결정 사항 | 선택 | 근거 |
|---|----------|------|------|
| D1 | 프로그래밍 언어 | Python 3.11+ | 금융 데이터 생태계 최강 (pandas, numpy), 한투 API 공식 샘플이 Python |
| D2 | 브로커 API | 한국투자증권 Open API | 사용자 선택. 해외주식 거래 지원, WebSocket 실시간 데이터 |
| D3 | 주문 실행 방식 | 실시간 모니터링 + 지정가 주문 | 한투 API에 스톱/시장가 주문 미지원 → 봇이 직접 가격 감시 후 지정가 주문 |
| D4 | 실행 시간 | US 정규장 (KST 23:30~06:00) 실시간 | 터틀 원전: 돌파 시점에 스톱 오더 → 장중 자동 체결 방식. 이를 모니터링으로 재현 |
| D5 | CANSLIM 스크리닝 | 공개 데이터 완전 자동화 + 근사치 | IBD 고유 지표(Composite, SMR)는 자체 스코어링으로 대체 |
| D6 | 가격 데이터 | 실시간: 한투 WebSocket, 과거: yfinance → SQLite 캐시 | 초기 벌크 로드 후 증분 업데이트 |
| D7 | 재무 데이터 | yfinance 초기 벌크 + 분기별 증분 업데이트 | 무료, 충분한 품질 |
| D8 | 상태 저장 | SQLite | 로컬 파일 DB, 설정 불필요, 백업 간편 |
| D9 | 트레이딩 모드 | Paper / Live 설정으로 전환 | 한투 모의투자 API(별도 키) + 실전 API |
| D10 | 운용 자본 | Paper: $100,000 / Live: $10,000 | 설정 값, 코드에서 동적으로 읽음 |
| D11 | 소액 계좌 대응 | 1% 리스크 유지, int(shares) ≥ 1이면 진입 | $200+ 주식도 가능한 수량만큼 진입. 0주면 스킵 |
| D12 | 알림 | Telegram Bot | 주문 체결, 에러, 일일 요약 |
| D13 | 백테스팅 | 초기 제외, 추후 추가 | 스코프 관리 |
| D14 | 배포 환경 | 클라우드 서버 | US 장시간 동안 안정적 실행 필요 |
| D15 | UI | 웹 대시보드 (FastAPI+React) + Telegram 명령 확장 | 포지션, 워치리스트, 매매일지, 수익률 모두 조회 가능 |

---

## 1. 아키텍처 개요

### 1.1 시스템 구성도

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLOUD SERVER                             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    TRADING BOT                            │  │
│  │                                                           │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │  │
│  │  │  Scheduler   │  │  Main Engine  │  │  Telegram Bot   │  │  │
│  │  │ (APScheduler)│→ │ (Event Loop)  │→ │  (Notifications)│  │  │
│  │  └─────────────┘  └──────┬───────┘  └────────────────┘  │  │
│  │                          │                                │  │
│  │         ┌────────────────┼────────────────┐              │  │
│  │         ▼                ▼                ▼              │  │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────┐      │  │
│  │  │  Strategy   │  │  Execution  │  │    Risk       │      │  │
│  │  │  Engine     │  │  Engine     │  │  Manager      │      │  │
│  │  │            │  │            │  │              │      │  │
│  │  │ • CANSLIM  │  │ • Orders   │  │ • Position   │      │  │
│  │  │ • Donchian │  │ • Fills    │  │   Limits     │      │  │
│  │  │ • ATR/N    │  │ • Stop-loss│  │ • Correlation│      │  │
│  │  │ • Pyramid  │  │   Monitor  │  │   Groups     │      │  │
│  │  └──────┬─────┘  └──────┬─────┘  └──────┬───────┘      │  │
│  │         │               │               │              │  │
│  │         └───────────────┼───────────────┘              │  │
│  │                         ▼                               │  │
│  │              ┌─────────────────────┐                    │  │
│  │              │     Data Layer       │                    │  │
│  │              │                     │                    │  │
│  │              │  ┌───────────────┐  │                    │  │
│  │              │  │   SQLite DB    │  │                    │  │
│  │              │  └───────────────┘  │                    │  │
│  │              │  ┌───────────────┐  │                    │  │
│  │              │  │ KIS REST API   │  │                    │  │
│  │              │  └───────────────┘  │                    │  │
│  │              │  ┌───────────────┐  │                    │  │
│  │              │  │ KIS WebSocket  │  │                    │  │
│  │              │  └───────────────┘  │                    │  │
│  │              │  ┌───────────────┐  │                    │  │
│  │              │  │ yfinance       │  │                    │  │
│  │              │  └───────────────┘  │                    │  │
│  │              └─────────────────────┘                    │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 실행 흐름 (일일 사이클)

```
┌─────────────────────────────────────────────────────────────────┐
│ KST 22:00 — PRE-MARKET PREPARATION                             │
│                                                                 │
│  1. 한투 API 토큰 갱신 (24시간 만료)                              │
│  2. 계좌 잔고 / 보유 포지션 동기화                                  │
│  3. 일일 OHLCV 데이터 업데이트 (한투 API: 해외주식 기간별시세)        │
│  4. ATR(N) 재계산 (모든 워치리스트 종목)                           │
│  5. Donchian 채널 레벨 계산 (20일/55일 고가, 10일/20일 저가)       │
│  6. SPY 200일 SMA 시장 필터 확인                                  │
│  7. 진입/손절/청산/피라미드 트리거 가격 사전 계산                     │
│  8. 결과를 메모리에 로드 (TradeSignals 객체)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│ KST 23:30 — MARKET OPEN                                        │
│                                                                 │
│  1. WebSocket 연결: 워치리스트 + 보유종목 실시간 구독               │
│  2. 갭 처리:                                                     │
│     - 보유종목이 손절가 아래에서 시가 형성 → 즉시 매도 주문          │
│     - 워치리스트 종목이 돌파가 위에서 시가 형성 → 돌파 진입 처리     │
│                                                                 │
│  [실시간 모니터링 루프 시작]                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│ KST 23:30~06:00 — INTRADAY MONITORING LOOP                     │
│                                                                 │
│  WebSocket 틱 수신 시 (각 종목별):                                │
│                                                                 │
│  ┌─ [우선순위 1] 손절 체크 ──────────────────────────────────┐   │
│  │  보유종목 현재가 ≤ 손절가?                                  │   │
│  │  → YES: 즉시 지정가 매도 (현재가 - 슬리피지 버퍼)           │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ [우선순위 2] 피라미딩 체크 ──────────────────────────────┐   │
│  │  보유종목 현재가 ≥ 직전진입가 + 0.5N?                       │   │
│  │  AND 유닛 수 < 4? AND 포지션 한도 여유?                     │   │
│  │  → YES: 추가 유닛 지정가 매수 + 전체 손절 갱신              │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ [우선순위 3] 신규 진입 체크 ─────────────────────────────┐   │
│  │  워치리스트 종목 현재가 > Donchian Upper (20일 or 55일)?     │   │
│  │  AND 시장 필터 통과? AND 포지션 한도 여유?                   │   │
│  │  AND System 1 필터 통과? (직전 돌파 손실이었는지)            │   │
│  │  → YES: 유닛 크기 계산 → 지정가 매수 + 손절 설정            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ [우선순위 4] Donchian 청산 체크 ─────────────────────────┐   │
│  │  ※ 종가 기준이므로 장 마감 전 15분(05:45 KST)에 확인       │   │
│  │  보유종목 현재가 < Donchian Lower (S1:10일 / S2:20일)?      │   │
│  │  → YES: 전량 매도 주문                                      │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [병렬] 주문 상태 모니터링                                        │
│  - 미체결 주문 추적                                               │
│  - 부분 체결 처리                                                 │
│  - 주문 실패 시 재시도                                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│ KST 06:00 — MARKET CLOSE                                       │
│                                                                 │
│  1. WebSocket 연결 종료                                          │
│  2. 미체결 주문 처리 (취소 or 유지 결정)                           │
│  3. 포지션 최종 동기화 (브로커 잔고 vs 로컬 DB)                    │
│  4. 오늘의 종가 데이터로 돌파 이력 업데이트                         │
│  5. 일일 P&L 계산 및 기록                                         │
│  6. Telegram 일일 요약 리포트 발송                                 │
│  7. 다음 거래일 CANSLIM 워치리스트 갱신 (주 1-2회)                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 핵심 기술적 챌린지 & 해결 방안

### 2.1 스톱 주문 미지원 → 소프트웨어 스톱 구현

**문제**: 한투 API는 해외주식에 스톱 주문/시장가 주문이 없다. 지정가만 가능.

**해결**: 봇이 실시간 가격을 모니터링하다가 손절 조건 발생 시 **즉시 지정가 매도 주문**을 넣는다.

```python
# 손절 트리거 시 주문 가격 결정 로직
def calculate_stop_sell_price(current_price: float, stop_price: float) -> float:
    """
    손절 발동 시 지정가 매도 가격 계산
    
    지정가이므로 현재가보다 충분히 낮게 설정해야 체결 확률이 높다.
    "aggressive limit order" = 사실상 시장가처럼 동작.
    
    전략: 현재가에서 추가 0.5% 아래로 지정가 설정
    → 급락장에서도 체결 확률을 높이면서, 극단적 슬리피지 방지
    """
    STOP_SELL_BUFFER_PCT = 0.005  # 0.5% 버퍼
    sell_price = current_price * (1 - STOP_SELL_BUFFER_PCT)
    
    # 최소 틱 단위 맞춤 (미국 주식: $0.01)
    sell_price = round(sell_price, 2)
    
    return sell_price
```

**리스크 & 대응**:

| 리스크 | 발생 확률 | 대응 |
|--------|----------|------|
| 급락 중 지정가 미체결 | 낮음 (0.5% 버퍼) | 미체결 시 5초 후 가격 갱신하여 재주문 |
| WebSocket 끊김 중 급락 | 중간 | REST 폴백 (30초 간격) + 재연결 로직 |
| 갭 다운으로 시가가 손절가 아래 | 있음 | 장 시작 시 즉시 시가 기준 매도 주문 |
| 봇 크래시 | 낮음 | 프로세스 매니저(systemd)로 자동 재시작 + 시작 시 포지션 동기화 |

### 2.2 WebSocket 안정성

US 정규장 6.5시간 동안 WebSocket 연결 유지가 핵심이다.

```python
# WebSocket 안정성 패턴
class ReliableWebSocket:
    """
    3중 안전장치:
    1. 자동 재연결 (지수 백오프)
    2. 하트비트/Ping 모니터링
    3. REST 폴링 폴백
    """
    
    RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30, 30, 30]  # 초 단위, 최대 30초
    HEARTBEAT_TIMEOUT = 60  # 60초 무응답 시 재연결
    REST_FALLBACK_INTERVAL = 30  # WebSocket 실패 시 30초마다 REST 조회
    
    # 상태: CONNECTED, RECONNECTING, FALLBACK_REST, DISCONNECTED
```

**핵심 설계 원칙**:
- WebSocket이 죽으면 REST API 폴링으로 **자동 전환** (degraded mode)
- REST 폴링 중에도 손절 모니터링은 계속됨 (30초 간격)
- 재연결 성공 시 WebSocket으로 **자동 복귀**
- 모든 연결 상태 변경은 Telegram 알림

### 2.3 지정가 주문의 돌파 진입

**문제**: 돌파가 $50.01인데, 지정가 매수를 $50.01에 넣으면 이미 $50.05로 올라가 미체결.

**해결**: 돌파 감지 시 **현재가 + 슬리피지 버퍼**로 지정가 매수.

```python
def calculate_breakout_buy_price(current_price: float, breakout_price: float) -> float:
    """
    돌파 진입 시 지정가 매수 가격 계산
    
    현재가가 이미 돌파가를 넘었으므로, 현재가 위에 버퍼를 두어 체결 확보.
    """
    BUY_BUFFER_PCT = 0.003  # 0.3% 버퍼
    buy_price = current_price * (1 + BUY_BUFFER_PCT)
    return round(buy_price, 2)
```

### 2.4 동시성 모델

```
asyncio 기반 단일 스레드 이벤트 루프

이유:
- WebSocket은 본질적으로 async
- 여러 종목의 틱을 하나의 이벤트 루프에서 처리
- 주문 API 호출도 async (aiohttp)
- GIL 문제 없음 (I/O 바운드 작업)
- 디버깅이 threading보다 단순

구조:
  main_loop:
    ├── ws_handler (WebSocket 메시지 수신)
    ├── signal_processor (신호 판단 & 주문 생성)
    ├── order_monitor (주문 상태 추적)
    ├── heartbeat_checker (연결 상태 감시)
    └── rest_fallback (폴백 가격 조회)
```

---

## 3. 프로젝트 구조

```
snowa_tradingbot/
│
├── config/
│   ├── __init__.py
│   ├── settings.py              # 환경 설정 (API 키, DB 경로, 모드 등)
│   ├── constants.py             # 전략 상수 (TURTLE_TRADING_STRATEGY.md에서 추출)
│   └── logging_config.py        # 로깅 설정
│
├── core/
│   ├── __init__.py
│   ├── database.py              # SQLite 연결, 스키마 관리, 마이그레이션
│   ├── models.py                # 데이터 모델 (Position, Order, Signal, WatchlistStock 등)
│   └── events.py                # 내부 이벤트 버스 (신호 전달)
│
├── broker/
│   ├── __init__.py
│   ├── kis_auth.py              # 한투 API 인증 (OAuth 토큰, 해시키)
│   ├── kis_rest.py              # 한투 REST API 클라이언트 (주문, 잔고, 시세)
│   ├── kis_websocket.py         # 한투 WebSocket 클라이언트 (실시간 체결가/호가)
│   ├── order_executor.py        # 주문 실행 (지정가 매수/매도, 정정/취소)
│   └── account.py               # 계좌 관리 (잔고 조회, 포지션 동기화)
│
├── data/
│   ├── __init__.py
│   ├── market_data.py           # 통합 시세 인터페이스 (실시간 + 과거)
│   ├── price_cache.py           # 가격 데이터 캐싱 (SQLite)
│   ├── fundamental_data.py      # 재무 데이터 관리 (yfinance → SQLite)
│   ├── yfinance_collector.py    # yfinance 벌크/증분 수집기
│   └── universe.py              # 미국 주식 유니버스 관리 (종목 목록)
│
├── screening/
│   ├── __init__.py
│   ├── canslim_screener.py      # CANSLIM 스크리닝 엔진 (C, A, N, S, L, I)
│   ├── rs_rating.py             # Relative Strength 근사 계산
│   ├── custom_composite.py      # 자체 Composite Score 계산
│   ├── minervini_template.py    # Minervini Trend Template 필터
│   └── watchlist_manager.py     # 워치리스트 관리 (추가/제거/갱신)
│
├── strategy/
│   ├── __init__.py
│   ├── market_filter.py         # SPY 200일 SMA 시장 필터
│   ├── atr.py                   # ATR(N) 계산 (20일 EMA of True Range)
│   ├── donchian.py              # Donchian Channel 계산 (20/55일 상단, 10/20일 하단)
│   ├── entry_signals.py         # 진입 신호 (System 1 & System 2, 필터 포함)
│   ├── exit_signals.py          # 청산 신호 (Donchian 하단 이탈)
│   ├── stop_loss.py             # 손절 관리 (min(2N, 10%) 하이브리드)
│   ├── pyramiding.py            # 피라미딩 (1/2N 간격, 최대 4유닛)
│   └── breakout_tracker.py      # 돌파 이력 추적 (System 1 필터용)
│
├── portfolio/
│   ├── __init__.py
│   ├── position_manager.py      # 포지션 추적 (유닛별 진입가, 손절가, 수량)
│   ├── position_sizer.py        # 유닛 크기 계산 (Minervini 리스크 기반)
│   ├── risk_manager.py          # 포지션 한도 (단일4, 상관6, 느슨10, 전체12)
│   └── correlation_groups.py    # 상관 그룹 관리 (IBD Industry → GICS 근사)
│
├── bot/
│   ├── __init__.py
│   ├── trading_bot.py           # 메인 봇 오케스트레이션 (일일 사이클 관리)
│   ├── pre_market.py            # 장전 준비 (데이터 갱신, 레벨 계산)
│   ├── intraday_monitor.py      # 장중 실시간 모니터링 (이벤트 루프)
│   ├── post_market.py           # 장후 처리 (동기화, 리포트)
│   └── mode.py                  # Paper/Live 모드 관리
│
├── notifications/
│   ├── __init__.py
│   └── telegram_bot.py          # Telegram 알림 + 조회 명령 (/positions, /pnl 등)
│
├── web/
│   ├── api/                         # FastAPI 백엔드
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI 앱 엔트리포인트
│   │   ├── dependencies.py          # DB 세션, 인증 의존성
│   │   └── routes/                  # API 라우트 (/positions, /pnl, /watchlist 등)
│   │
│   └── frontend/                    # React 프론트엔드
│       ├── src/
│       │   ├── pages/               # Dashboard, Positions, Watchlist, Trades, Journal
│       │   └── components/          # 재사용 컴포넌트
│       └── dist/                    # 빌드 결과 (FastAPI static serve)
│
├── scripts/
│   ├── initial_data_load.py     # 초기 데이터 벌크 로드 (최초 1회)
│   ├── update_fundamentals.py   # 재무 데이터 증분 업데이트 (분기별)
│   └── run_bot.py               # 메인 엔트리포인트
│
├── tests/
│   ├── test_atr.py
│   ├── test_donchian.py
│   ├── test_position_sizer.py
│   ├── test_entry_signals.py
│   ├── test_stop_loss.py
│   ├── test_pyramiding.py
│   ├── test_risk_manager.py
│   └── ...
│
├── data/                        # 런타임 데이터 디렉토리
│   └── snowa.db                 # SQLite 데이터베이스 파일
│
├── requirements.txt
├── .env.example                 # 환경 변수 템플릿
├── TURTLE_TRADING_STRATEGY.md   # 전략 명세서 (기존)
├── QUANTIFIED_STRATEGY.md       # CANSLIM 상세 (기존)
└── IMPLEMENTATION_PLAN.md       # 이 문서
```

---

## 4. 데이터베이스 스키마 (SQLite)

### 4.1 핵심 테이블

```sql
-- ===================================================================
-- 1. 워치리스트 (CANSLIM 필터 통과 종목)
-- ===================================================================
CREATE TABLE watchlist (
    ticker TEXT PRIMARY KEY,
    added_date TEXT NOT NULL,              -- ISO 8601
    last_screened TEXT NOT NULL,            -- 마지막 스크리닝 날짜
    
    -- CANSLIM 스코어
    quarterly_eps_growth REAL,             -- C: 분기 EPS YoY 성장률
    annual_eps_cagr REAL,                  -- A: 5년 연간 EPS CAGR
    rs_rating REAL,                        -- L: RS Rating 근사치 (0-99)
    institutional_holders INTEGER,         -- I: 기관 보유 수
    institutional_change_pct REAL,         -- I: QoQ 기관 보유 변화율
    custom_composite_score REAL,           -- 자체 Composite 점수
    
    -- Minervini Trend Template
    minervini_pass INTEGER DEFAULT 0,      -- 8개 조건 통과 여부 (1/0)
    
    -- 메타
    sector TEXT,                           -- GICS Sector
    industry TEXT,                         -- GICS Industry (상관 그룹용)
    avg_daily_volume INTEGER,              -- 50일 평균 거래량
    market_cap REAL,                       -- 시가총액
    
    status TEXT DEFAULT 'ACTIVE'           -- ACTIVE, REMOVED, SUSPENDED
);

-- ===================================================================
-- 2. 가격 데이터 캐시 (일봉 OHLCV)
-- ===================================================================
CREATE TABLE daily_prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,                    -- YYYY-MM-DD
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    
    PRIMARY KEY (ticker, date)
);

CREATE INDEX idx_daily_prices_date ON daily_prices(date);

-- ===================================================================
-- 3. 재무 데이터 캐시
-- ===================================================================
CREATE TABLE fundamentals (
    ticker TEXT NOT NULL,
    report_date TEXT NOT NULL,             -- 실적 발표일
    period TEXT NOT NULL,                  -- 'Q1_2025', 'FY_2024' 등
    period_type TEXT NOT NULL,             -- 'quarterly' or 'annual'
    
    eps REAL,                              -- 주당순이익
    revenue REAL,                          -- 매출
    net_income REAL,                       -- 순이익
    shares_outstanding REAL,               -- 발행주식수
    debt_to_equity REAL,                   -- 부채비율
    
    updated_at TEXT NOT NULL,              -- 데이터 수집 시각
    
    PRIMARY KEY (ticker, period)
);

-- ===================================================================
-- 4. 포지션 (현재 보유 중인 포지션)
-- ===================================================================
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    system TEXT NOT NULL,                  -- 'S1' or 'S2'
    status TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN, CLOSED
    
    -- 집계
    total_shares INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0,    -- 총 매수 금액
    avg_entry_price REAL NOT NULL DEFAULT 0,
    current_stop_price REAL NOT NULL,      -- 현재 적용 중인 손절가
    n_at_entry REAL NOT NULL,              -- 진입 시점의 N (ATR)
    
    -- 한도 관리용
    sector TEXT,
    industry TEXT,
    
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    close_reason TEXT,                     -- STOP_LOSS, SYSTEM1_EXIT, SYSTEM2_EXIT, MANUAL
    realized_pnl REAL,
    
    UNIQUE(ticker, status)                 -- 종목당 OPEN 포지션은 하나만
);

-- ===================================================================
-- 5. 유닛 (포지션 내 개별 진입 단위)
-- ===================================================================
CREATE TABLE units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    unit_number INTEGER NOT NULL,          -- 1, 2, 3, 4
    
    entry_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    entry_stop_price REAL NOT NULL,        -- 이 유닛의 초기 손절가
    current_stop_price REAL NOT NULL,      -- 현재 적용 중인 손절가 (피라미딩으로 갱신됨)
    
    entered_at TEXT NOT NULL,
    
    UNIQUE(position_id, unit_number)
);

-- ===================================================================
-- 6. 주문 이력
-- ===================================================================
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT,                  -- 한투 API 주문번호
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                    -- BUY, SELL
    order_type TEXT NOT NULL,              -- ENTRY, PYRAMID, STOP_LOSS, EXIT, MANUAL
    
    requested_shares INTEGER NOT NULL,
    requested_price REAL NOT NULL,
    
    filled_shares INTEGER DEFAULT 0,
    filled_price REAL,
    
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, SUBMITTED, PARTIAL, FILLED, CANCELLED, FAILED
    
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    filled_at TEXT,
    
    notes TEXT                             -- 주문 사유, 에러 메시지 등
);

-- ===================================================================
-- 7. 돌파 이력 (System 1 필터용)
-- ===================================================================
CREATE TABLE breakout_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    system TEXT NOT NULL,                  -- 'S1' or 'S2'
    breakout_date TEXT NOT NULL,
    breakout_price REAL NOT NULL,
    
    -- 가상 수익/손실 계산 (System 1 필터용)
    -- "이 돌파에 진입했다면 수익이었을까?"를 10일 저가로 판단
    would_have_been_winner INTEGER,        -- 1=수익, 0=손실, NULL=미확정
    hypothetical_exit_price REAL,
    hypothetical_exit_date TEXT,
    
    was_actually_entered INTEGER DEFAULT 0 -- 실제로 진입했는지
);

-- ===================================================================
-- 8. 일일 트레이딩 로그
-- ===================================================================
CREATE TABLE daily_log (
    date TEXT PRIMARY KEY,
    
    -- 시장 상태
    spy_close REAL,
    spy_sma200 REAL,
    market_filter_pass INTEGER,            -- 1=상승시장, 0=하락시장
    
    -- 포트폴리오
    account_equity REAL,                   -- 총 계좌 평가액
    cash_balance REAL,
    total_positions INTEGER,
    total_units INTEGER,
    
    -- 성과
    daily_pnl REAL,
    daily_pnl_pct REAL,
    cumulative_pnl REAL,
    max_drawdown_pct REAL,
    
    -- 활동
    entries_count INTEGER DEFAULT 0,
    exits_count INTEGER DEFAULT 0,
    stop_losses_count INTEGER DEFAULT 0
);

-- ===================================================================
-- 9. 설정 (런타임 상태)
-- ===================================================================
CREATE TABLE bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- 예: ('trading_mode', 'paper', '2026-02-14T...'),
--     ('last_data_update', '2026-02-14', '...'),
--     ('ws_status', 'connected', '...')
```

---

## 5. 구현 단계 (Phase별 상세)

### Phase 1: Foundation (1주)

**목표**: 프로젝트 골격, DB, 설정, 한투 API 인증 연결

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 1.1 | 프로젝트 초기화 (pyproject.toml, 가상환경) | 프로젝트 구조 | `pip install -e .` 성공 |
| 1.2 | 설정 관리 (pydantic-settings, .env) | `config/settings.py` | 환경별 설정 로드 확인 |
| 1.3 | 전략 상수 정의 | `config/constants.py` | TURTLE_TRADING_STRATEGY.md의 모든 상수 포함 |
| 1.4 | SQLite DB 스키마 생성 | `core/database.py` | 모든 테이블 생성, 마이그레이션 |
| 1.5 | 데이터 모델 정의 (dataclass/Pydantic) | `core/models.py` | 타입 검증 |
| 1.6 | 로깅 설정 (structlog) | `config/logging_config.py` | 파일+콘솔 로깅 |
| 1.7 | 한투 API 인증 (OAuth 토큰 발급) | `broker/kis_auth.py` | 토큰 발급 + 갱신 성공 |
| 1.8 | Paper/Live 모드 스위칭 | `bot/mode.py` | 모드별 다른 API URL/키 사용 확인 |

**핵심 의존성**:
```
python = ">=3.11"
pydantic = ">=2.0"
pydantic-settings = ">=2.0"
aiohttp = ">=3.9"
websockets = ">=12.0"
pandas = ">=2.0"
numpy = ">=1.24"
yfinance = ">=0.2.30"
structlog = ">=24.0"
apscheduler = ">=3.10"
python-telegram-bot = ">=20.0"
aiosqlite = ">=0.19"
fastapi = ">=0.109"
uvicorn = ">=0.27"
```

---

### Phase 2: Broker Integration (1.5주)

**목표**: 한투 API REST + WebSocket 완전 연동

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 2.1 | REST 클라이언트 기본 (인증, 에러 핸들링, 리트라이) | `broker/kis_rest.py` | 토큰 포함 요청 성공 |
| 2.2 | 해외주식 현재가 조회 | kis_rest.py 확장 | AAPL 현재가 조회 |
| 2.3 | 해외주식 기간별 시세 (일봉 OHLCV) | kis_rest.py 확장 | 300일 과거 데이터 수신 |
| 2.4 | 해외주식 주문 (지정가 매수/매도) | `broker/order_executor.py` | 모의투자에서 주문 체결 |
| 2.5 | 주문 정정/취소 | order_executor.py 확장 | 미체결 주문 취소 |
| 2.6 | 주문 체결 내역 조회 | order_executor.py 확장 | 체결 확인 |
| 2.7 | 계좌 잔고/보유종목 조회 | `broker/account.py` | 잔고, 보유종목 정확히 수신 |
| 2.8 | WebSocket 연결 (실시간 체결가) | `broker/kis_websocket.py` | AAPL 실시간 틱 수신 |
| 2.9 | WebSocket 안정성 (재연결, 하트비트) | kis_websocket.py 확장 | 의도적 끊기 후 자동 재연결 |
| 2.10 | REST 폴백 모드 | kis_websocket.py 확장 | WS 실패 시 REST로 가격 조회 |

**한투 API 참조**: `https://github.com/koreainvestment/open-trading-api`의 `overseas_stock/` 샘플 코드 기반.

**인증 플로우**:
```
1. appkey + appsecret → POST /oauth2/tokenP → access_token (24시간 유효)
2. access_token을 모든 REST 요청의 Authorization 헤더에 포함
3. WebSocket: POST /oauth2/Approval → approval_key → WS 연결 시 사용
4. 주문 시: POST /uapi/hashkey → hashkey (요청 바디 해싱)
```

---

### Phase 3: Data Layer (1주)

**목표**: 가격/재무 데이터 수집, 캐싱, 증분 업데이트

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 3.1 | 미국 주식 유니버스 구성 | `data/universe.py` | NYSE+NASDAQ 전 종목 리스트 (약 8,000) |
| 3.2 | yfinance 벌크 재무 데이터 수집 | `scripts/initial_data_load.py` | 8,000종목 EPS/매출 등 SQLite 저장 |
| 3.3 | yfinance 벌크 가격 데이터 수집 | initial_data_load.py 확장 | 300일 OHLCV SQLite 저장 |
| 3.4 | 증분 업데이트 로직 (재무) | `data/fundamental_data.py` | 신규 실적만 추가 |
| 3.5 | 일일 가격 업데이트 (한투 API) | `data/price_cache.py` | 매일 장후 당일 OHLCV 추가 |
| 3.6 | 통합 시세 인터페이스 | `data/market_data.py` | get_ohlcv(ticker, days) 단일 API |

**초기 데이터 로드 전략**:
```python
# scripts/initial_data_load.py
# 실행: 최초 1회 (약 2-4시간 소요)

# Step 1: 유니버스 구성
#   - NYSE + NASDAQ 상장 종목 리스트 (yfinance 또는 FMP)
#   - 최소 필터: 주가 ≥ $10, ADV ≥ 500,000

# Step 2: 가격 데이터 (yfinance)
#   - 각 종목 300일 일봉 OHLCV
#   - 배치 처리: 100종목씩 + 1초 딜레이 (차단 방지)
#   - SQLite daily_prices 테이블에 저장

# Step 3: 재무 데이터 (yfinance)
#   - ticker.quarterly_earnings, ticker.financials
#   - 최근 5년 분기별 EPS, 매출, 순이익
#   - SQLite fundamentals 테이블에 저장

# Step 4: 기관 보유 데이터 (yfinance)
#   - ticker.institutional_holders
#   - 기관 수, 보유 비율
```

**증분 업데이트 전략**:
```
매일 (장후):
  - 워치리스트 + 보유종목의 당일 OHLCV → 한투 API로 수집
  - SPY 당일 OHLCV → 한투 API

주 1회 (주말):
  - CANSLIM 스크리닝 재실행 (전체 유니버스)
  - RS Rating 재계산 (전체 유니버스 순위)

분기별:
  - 실적 시즌(1/4/7/10월) 후 재무 데이터 업데이트
  - yfinance로 업데이트된 분기 실적만 수집
  - 업데이트 대상: 지난 분기 실적 발표한 종목만
```

---

### Phase 4: CANSLIM Screening Engine (1.5주)

**목표**: 자동화된 종목 스크리닝 → 워치리스트 생성

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 4.1 | C 필터 (분기 EPS 성장 ≥ 25%) | `screening/canslim_screener.py` | 알려진 고성장주 통과 확인 |
| 4.2 | A 필터 (5년 CAGR ≥ 25%) | canslim_screener.py 확장 | |
| 4.3 | N 필터 (52주 신고가 근접) | canslim_screener.py 확장 | |
| 4.4 | S 필터 (거래량 분석) | canslim_screener.py 확장 | |
| 4.5 | L 필터 (RS Rating 근사) | `screening/rs_rating.py` | 상위 20% 종목이 알려진 강세주와 일치 |
| 4.6 | I 필터 (기관 보유) | canslim_screener.py 확장 | |
| 4.7 | 추가 필터 (최소 주가, ADV, D/E) | canslim_screener.py 확장 | |
| 4.8 | 자체 Composite Score | `screening/custom_composite.py` | |
| 4.9 | Minervini Trend Template | `screening/minervini_template.py` | 8개 조건 구현 |
| 4.10 | 워치리스트 매니저 | `screening/watchlist_manager.py` | 워치리스트 갱신, 이력 관리 |

**RS Rating 근사 계산**:
```python
def calculate_rs_rating(ticker: str, all_tickers: list[str], 
                        price_data: dict) -> float:
    """
    IBD RS Rating 근사치 계산
    
    공식 (IBD 추정):
    RS = (2 × 3개월 수익률) + (6개월 수익률) + (9개월 수익률) + (12개월 수익률)
    
    이 값을 전체 종목 대비 백분위로 환산 (0-99)
    """
    # 1. 각 종목의 가중 수익률 계산
    # 2. 전체 종목 순위 매기기
    # 3. 백분위 환산 (0-99 스케일)
```

**자체 Composite Score** (IBD Composite Rating 대체):
```python
def calculate_custom_composite(stock_data: dict) -> float:
    """
    IBD Composite Rating을 대체하는 자체 점수 (0-99)
    
    구성:
    - EPS 성장 점수: 30% (분기 + 연간 결합)
    - RS Rating: 30%
    - 기관 매집 점수: 15%
    - 수급 점수: 15% (U/D Ratio, 거래량 추세)
    - 재무 건전성: 10% (D/E, 이익률)
    
    ※ 이 가중치는 초기 설정이며, 운용 경험에 따라 조정 가능
    """
```

---

### Phase 5: Strategy Engine (2주)

**목표**: 터틀 트레이딩 매매 로직 완전 구현

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 5.1 | 시장 필터 (SPY 200일 SMA) | `strategy/market_filter.py` | 과거 데이터로 ON/OFF 검증 |
| 5.2 | ATR(N) 계산 (20일 EMA) | `strategy/atr.py` | AAPL N값이 참조 데이터와 일치 |
| 5.3 | Donchian Channel 계산 | `strategy/donchian.py` | 20/55일 상단, 10/20일 하단 |
| 5.4 | System 1 진입 신호 (20일 돌파 + 필터) | `strategy/entry_signals.py` | 과거 돌파 이벤트 재현 |
| 5.5 | System 2 진입 신호 (55일 돌파, 필터 없음) | entry_signals.py 확장 | |
| 5.6 | 돌파 이력 추적 (System 1 필터용) | `strategy/breakout_tracker.py` | 가상 수익/손실 판단 로직 |
| 5.7 | 손절가 계산 (min(2N, 10%) 하이브리드) | `strategy/stop_loss.py` | 문서의 예시 케이스 재현 |
| 5.8 | 피라미딩 트리거 (1/2N 간격) | `strategy/pyramiding.py` | 4유닛 시나리오 검증 |
| 5.9 | 피라미딩 시 손절 갱신 로직 | stop_loss.py 확장 | 문서의 추적표 재현 |
| 5.10 | Donchian 청산 신호 (S1:10일, S2:20일) | `strategy/exit_signals.py` | |

**모든 전략 모듈은 순수 함수로 구현한다** — 입력(가격 배열, 파라미터)을 받아 출력(신호, 가격)을 반환. 부작용 없음. 단위 테스트가 쉬움.

```python
# 예시: strategy/atr.py
def calculate_n(
    highs: list[float], 
    lows: list[float], 
    closes: list[float], 
    period: int = ATR_PERIOD
) -> list[float]:
    """
    TURTLE_TRADING_STRATEGY.md §3.3의 정확한 구현
    입력: OHLCV 배열, 출력: N값 배열
    외부 의존성 없음. 순수 계산.
    """
```

---

### Phase 6: Portfolio Management (1주)

**목표**: 포지션 추적, 유닛 사이징, 리스크 한도 관리

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 6.1 | 유닛 크기 계산 (Minervini 리스크 기반) | `portfolio/position_sizer.py` | 문서의 3가지 예시 재현 |
| 6.2 | 소액 계좌 처리 (int(shares) ≥ 1) | position_sizer.py 포함 | $10K로 $200 주식 가능 확인 |
| 6.3 | 유동성 제한 (ADV의 5%) | position_sizer.py 포함 | |
| 6.4 | 포지션 매니저 (유닛 추가/제거/갱신) | `portfolio/position_manager.py` | 4유닛 피라미딩 시나리오 |
| 6.5 | 포지션 한도 체크 | `portfolio/risk_manager.py` | 단일(4), 상관(6), 느슨(10), 전체(12) |
| 6.6 | 상관 그룹 관리 (GICS 근사) | `portfolio/correlation_groups.py` | 같은 섹터/산업 종목 그룹핑 |

**소액 계좌 로직**:
```python
def calculate_unit_size(account_equity, entry_price, n_value, ...) -> int:
    """
    표준 Minervini 리스크 기반 사이징 후,
    결과가 0주이면 해당 종목 진입 스킵.
    1주 이상이면 그대로 진입.
    
    $10,000 계좌에서 $300 주식, N=$12 (N/P=4%):
    stop = min(2*12, 300*0.10) = min(24, 30) = 24
    shares = (10000 * 0.01) / 24 = 4.16 → 4주
    position = 4 * 300 = $1,200 (12% of account) ✓
    
    $10,000 계좌에서 $500 주식, N=$10 (N/P=2%):
    stop = min(2*10, 500*0.10) = min(20, 50) = 20
    shares = (10000 * 0.01) / 20 = 5주
    position = 5 * 500 = $2,500 (25% of account) ✓
    """
    shares = int(dollar_risk / actual_stop_distance)
    
    if shares < 1:
        return 0  # 이 종목은 현재 자본으로 거래 불가 → 스킵
    
    return shares
```

---

### Phase 7: Bot Orchestration (1.5주)

**목표**: 전체 트레이딩 사이클 통합, 메인 루프

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 7.1 | 장전 준비 로직 | `bot/pre_market.py` | 레벨 계산, 데이터 갱신 |
| 7.2 | 장중 모니터링 루프 (asyncio) | `bot/intraday_monitor.py` | WebSocket 틱 → 신호 판단 |
| 7.3 | 갭 처리 (장 시작 시 갭다운/갭업) | intraday_monitor.py 포함 | |
| 7.4 | Donchian 청산 (장 마감 전 15분) | intraday_monitor.py 포함 | |
| 7.5 | 장후 정리 로직 | `bot/post_market.py` | 동기화, 리포트 |
| 7.6 | 메인 봇 오케스트레이터 | `bot/trading_bot.py` | 전체 사이클 실행 |
| 7.7 | 스케줄러 (APScheduler) | trading_bot.py 포함 | 자동 시작/종료 |
| 7.8 | 비상 정지 기능 | trading_bot.py 포함 | Telegram 명령 or 파일 기반 킬스위치 |

**장중 모니터링 루프 핵심 로직**:
```python
async def on_price_update(ticker: str, price: float, timestamp: datetime):
    """
    WebSocket에서 가격 업데이트 수신 시 호출
    
    우선순위 순서:
    1. 손절 체크 (가장 긴급)
    2. 피라미딩 체크
    3. 신규 진입 체크
    4. (장 마감 15분 전만) Donchian 청산 체크
    """
    
    # 1. 손절
    if ticker in open_positions:
        position = open_positions[ticker]
        if price <= position.current_stop_price:
            await execute_stop_loss(ticker, price)
            return  # 손절 후 이 종목은 더 이상 체크 안 함
    
    # 2. 피라미딩
    if ticker in open_positions:
        pyramid_result = check_pyramid_add(position, price, account_equity)
        if pyramid_result['add']:
            await execute_pyramid(ticker, pyramid_result)
    
    # 3. 신규 진입
    elif ticker in watchlist and market_filter_pass:
        entry_result = check_entry_signal(ticker, price, trade_signals)
        if entry_result['signal']:
            await execute_entry(ticker, entry_result)
```

---

### Phase 8: Telegram Bot — 알림 + 조회 명령 (1주)

**목표**: 실시간 알림 + 대화형 명령어로 봇 상태/성과 조회

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 8.1 | Telegram Bot 기본 연결 (python-telegram-bot) | `notifications/telegram_bot.py` | 메시지 전송 성공 |
| 8.2 | 주문 알림 (진입/청산/손절) | telegram_bot.py 확장 | 주문 발생 시 즉시 알림 |
| 8.3 | 에러 알림 (연결 끊김, 주문 실패) | telegram_bot.py 확장 | |
| 8.4 | 일일 요약 리포트 (자동 발송) | telegram_bot.py 확장 | 장후 P&L, 포지션 현황 |
| 8.5 | `/stop` 킬스위치 명령 | telegram_bot.py 확장 | 봇 긴급 정지 |
| 8.6 | `/status` 봇 상태 조회 | telegram_bot.py 확장 | 연결 상태, 모드, 시장 필터 |
| 8.7 | `/positions` 보유 포지션 조회 | telegram_bot.py 확장 | 종목별 유닛, 손익, 손절가 |
| 8.8 | `/watchlist` 감시 리스트 조회 | telegram_bot.py 확장 | CANSLIM 통과 종목 + 돌파 레벨 |
| 8.9 | `/pnl` 수익률 조회 | telegram_bot.py 확장 | 오늘/주간/월간/누적 P&L |
| 8.10 | `/trades` 최근 거래 내역 | telegram_bot.py 확장 | 최근 N건 매매 이력 |
| 8.11 | `/journal` 매매일지 조회 | telegram_bot.py 확장 | 특정 기간 거래 요약 (승률, R:R 등) |

**Telegram 명령어 전체 목록**:

```
📡 봇 제어
  /start     — 봇 인사 + 명령어 목록
  /stop      — 긴급 정지 (모든 모니터링 중단, 포지션 유지)
  /mode      — 현재 모드 확인 (Paper/Live)

📊 실시간 현황
  /status    — 봇 상태 (연결, 시장필터, 모드, 유닛 사용량)
  /positions — 보유 포지션 상세
  /watchlist — 감시 리스트 (돌파 레벨 포함)
  /orders    — 미체결 주문 현황

💰 성과
  /pnl             — 수익률 요약 (오늘/주간/월간/누적)
  /pnl weekly      — 주간 상세
  /pnl monthly     — 월간 상세
  /trades          — 최근 10건 거래 내역
  /trades 20       — 최근 20건
  /journal         — 이번 달 매매일지 (승률, 평균 R:R, MDD)
  /journal 2026-01 — 특정 월 매매일지
```

**알림 메시지 예시**:
```
🟢 진입: NVDA
System: S1 (20일 돌파)
유닛: 1/4
수량: 12주 @ $450.25
손절: $432.25 (-4.0%)
리스크: $216 (계좌 0.98%)

🔴 손절: TSLA
원인: Stop-Loss (min(2N, 10%))
유닛: 2유닛 전량
수량: 25주 @ $238.50
손실: -$425 (계좌 -0.43%)

📊 일일 요약 (2026-02-14)
시장: SPY $512.30 > SMA200 $498.70 ✅
계좌: $99,425 (-0.58%)
보유: NVDA(2유닛), AAPL(3유닛)
오늘: 진입 1건, 손절 1건
```

**`/positions` 응답 예시**:
```
📋 보유 포지션 (3/12 유닛)

NVDA — S1 | 2유닛
  진입: $450.25 → 현재: $462.80 (+2.79%)
  유닛1: 12주 @ $450.25
  유닛2: 12주 @ $454.75
  손절: $445.50 (-1.05%)
  미실현 P&L: +$287.40

AAPL — S2 | 1유닛
  진입: $185.30 → 현재: $183.10 (-1.19%)
  유닛1: 28주 @ $185.30
  손절: $178.30 (-3.78%)
  미실현 P&L: -$61.60

💰 합계: +$225.80 (+0.23%)
```

**`/journal 2026-02` 응답 예시**:
```
📒 매매일지 — 2026년 2월

총 거래: 12건
  승: 4건 (33.3%)
  패: 8건 (66.7%)

평균 수익 (승): +$842 (+6.2%)
평균 손실 (패): -$215 (-3.1%)
손익비 (R:R): 3.92:1

최대 연속 손절: 5회
최대 단일 수익: NVDA +$1,890 (+12.4%)
최대 단일 손실: TSLA -$425 (-4.3%)

누적 P&L: +$1,258 (+1.26%)
최대 낙폭 (MDD): -3.8%
```

---

### Phase 8.5: Web Dashboard (2주)

**목표**: 브라우저에서 접근 가능한 트레이딩 대시보드

**기술 스택**: FastAPI (백엔드 API) + React (프론트엔드)
- FastAPI: 봇과 같은 Python 프로젝트에서 REST API를 간단히 제공
- React: 실시간 업데이트, 차트, 반응형 UI
- 대안: Streamlit (빠르지만 커스터마이징 한계) → React로 제대로 만드는 것을 권장

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 8.5.1 | FastAPI 백엔드 API 서버 | `web/api/` | `/api/positions`, `/api/pnl` 등 |
| 8.5.2 | API: 포지션 현황 엔드포인트 | `web/api/routes/positions.py` | JSON 응답 확인 |
| 8.5.3 | API: 수익률/성과 엔드포인트 | `web/api/routes/performance.py` | 일/주/월별 P&L |
| 8.5.4 | API: 워치리스트 엔드포인트 | `web/api/routes/watchlist.py` | CANSLIM 종목 + 돌파 레벨 |
| 8.5.5 | API: 주문/거래 이력 엔드포인트 | `web/api/routes/trades.py` | 필터링, 페이지네이션 |
| 8.5.6 | API: 봇 상태 엔드포인트 | `web/api/routes/status.py` | 연결, 모드, 시장 필터 |
| 8.5.7 | React: 프로젝트 초기화 (Vite + TailwindCSS) | `web/frontend/` | 빌드 성공 |
| 8.5.8 | React: 대시보드 메인 페이지 | 대시보드 UI | 계좌 요약, 포지션, P&L 차트 |
| 8.5.9 | React: 포지션 상세 페이지 | 포지션 UI | 유닛별 진입가, 손절, 미실현 P&L |
| 8.5.10 | React: 워치리스트 페이지 | 워치리스트 UI | CANSLIM 점수, 돌파 레벨, 시장필터 |
| 8.5.11 | React: 매매 이력/일지 페이지 | 트레이드 UI | 날짜 필터, 승패 통계, R:R |
| 8.5.12 | React: 수익률 차트 (equity curve) | 차트 UI | 일별 계좌 변화, MDD 시각화 |
| 8.5.13 | 인증 (간단한 API Key or 비밀번호) | 인증 미들웨어 | 비인가 접근 차단 |
| 8.5.14 | 배포 (Nginx reverse proxy + systemd) | 배포 설정 | 서버에서 접근 가능 |

**웹 대시보드 페이지 구성**:

```
┌─────────────────────────────────────────────────────────────┐
│  📊 SNOWA Trading Bot Dashboard                    [Paper]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ 계좌 요약 ──────────────────────────────────────────┐  │
│  │  계좌 평가: $101,258    일간 P&L: +$425 (+0.42%)     │  │
│  │  현금: $52,340          누적 P&L: +$1,258 (+1.26%)   │  │
│  │  유닛: 5/12 사용        MDD: -3.8%                   │  │
│  │  시장: SPY > 200MA ✅   모드: Paper                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Equity Curve (계좌 추이 차트) ──────────────────────┐  │
│  │  [───────────────/\──────/\────/\───────]            │  │
│  │  $100K                                    $101.2K    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 보유 포지션 ────────────────────────────────────────┐  │
│  │  종목  │ 시스템 │ 유닛 │ 평균가 │ 현재가 │ P&L      │  │
│  │  NVDA │ S1    │ 2/4  │$450.25│$462.80│+2.79%    │  │
│  │  AAPL │ S2    │ 1/4  │$185.30│$183.10│-1.19%    │  │
│  │  [클릭 시 유닛별 상세, 손절가, 피라미드 레벨 표시]    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 워치리스트 ─────────────────────────────────────────┐  │
│  │  종목  │ CS점수│RS│ 20일돌파│ 55일돌파│ 상태         │  │
│  │  META │  92  │95│ $585.20│ $542.80│ 근접 (1.2%)  │  │
│  │  COST │  88  │91│ $925.50│ $880.20│ 대기         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 최근 거래 ──────────────────────────────────────────┐  │
│  │  날짜      │ 종목 │ 유형    │ 수량  │ 가격   │ P&L   │  │
│  │  02-14    │ TSLA│ 손절    │ 25주 │$238.50│-$425 │  │
│  │  02-13    │ NVDA│ 피라미드│ 12주 │$454.75│ —    │  │
│  │  02-12    │ NVDA│ 진입    │ 12주 │$450.25│ —    │  │
│  │  [더보기 → 전체 매매일지 페이지]                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 매매 성과 통계 ─────────────────────────────────────┐  │
│  │  기간: [이번 달 ▼]                                    │  │
│  │  총 거래: 12건 | 승률: 33.3% | R:R: 3.92:1           │  │
│  │  최대 연속 손절: 5회                                   │  │
│  │  [승패 분포 차트] [월별 수익 바 차트]                  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**프로젝트 구조 추가분**:
```
snowa_tradingbot/
├── web/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI 앱 엔트리포인트
│   │   ├── dependencies.py          # DB 세션, 인증 등 의존성
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── status.py            # GET /api/status
│   │       ├── positions.py         # GET /api/positions
│   │       ├── watchlist.py         # GET /api/watchlist
│   │       ├── trades.py            # GET /api/trades
│   │       ├── performance.py       # GET /api/pnl
│   │       └── journal.py           # GET /api/journal
│   │
│   └── frontend/
│       ├── package.json
│       ├── vite.config.ts
│       ├── tailwind.config.js
│       ├── src/
│       │   ├── App.tsx
│       │   ├── pages/
│       │   │   ├── Dashboard.tsx     # 메인 대시보드
│       │   │   ├── Positions.tsx     # 포지션 상세
│       │   │   ├── Watchlist.tsx     # 워치리스트
│       │   │   ├── Trades.tsx        # 매매 이력
│       │   │   └── Journal.tsx       # 매매일지/성과
│       │   ├── components/
│       │   │   ├── AccountSummary.tsx
│       │   │   ├── EquityCurve.tsx   # 차트 (recharts)
│       │   │   ├── PositionTable.tsx
│       │   │   ├── WatchlistTable.tsx
│       │   │   ├── TradeHistory.tsx
│       │   │   └── PerformanceStats.tsx
│       │   └── lib/
│       │       └── api.ts            # API 클라이언트
│       └── dist/                     # 빌드 결과 (FastAPI에서 static serve)
```

**추가 의존성**:
```
# 백엔드
fastapi = ">=0.109"
uvicorn = ">=0.27"

# 프론트엔드 (package.json)
react, react-dom, react-router-dom
@tanstack/react-query     # 서버 상태 관리
recharts                  # 차트
tailwindcss               # 스타일
```

---

### Phase 9: Testing & Paper Trading (1주)

**목표**: 통합 테스트, 모의투자 실전 운영

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 9.1 | 전략 단위 테스트 (ATR, Donchian, 사이징 등) | `tests/` | 문서의 모든 예시 케이스 재현 |
| 9.2 | 통합 테스트 (시나리오 기반) | tests/ 확장 | 진입→피라미딩→손절 전체 흐름 |
| 9.3 | 모의투자 Dry Run (주문 없이 신호만) | 별도 모드 | 신호가 합리적인지 확인 |
| 9.4 | 모의투자 실전 (실제 주문 포함) | Paper Trading | 1-2주 실행 후 검증 |
| 9.5 | 배포 스크립트 (systemd, 환경 설정) | `deploy/` | 클라우드 서버에서 자동 실행 |

---

### Phase 10: Deployment (0.5주)

**목표**: 클라우드 서버 배포, 운영 안정화

| # | 작업 | 산출물 | 검증 방법 |
|---|------|--------|----------|
| 10.1 | 서버 프로비저닝 (AWS EC2 or DigitalOcean) | 서버 인스턴스 | SSH 접속 |
| 10.2 | 환경 설정 (Python, 의존성, .env) | 서버 환경 | 봇 실행 가능 |
| 10.3 | systemd 서비스 등록 | `deploy/snowa_bot.service` | 자동 시작/재시작 |
| 10.4 | 로그 관리 (logrotate) | 로그 설정 | |
| 10.5 | DB 백업 자동화 (cron) | 백업 스크립트 | 일일 SQLite 파일 백업 |
| 10.6 | 모니터링 (서버 상태) | 기본 헬스 체크 | |

**서버 추천 사양**:
```
인스턴스: AWS EC2 t3.small 또는 DigitalOcean $12/월 (2 vCPU, 2GB RAM)
OS: Ubuntu 22.04 LTS
리전: US East (us-east-1) — 미국 거래소에 가까운 네트워크 레이턴시
저장: 20GB SSD (SQLite + 로그)
비용: 약 $10-15/월
```

---

## 6. 일정 요약

| Phase | 내용 | 예상 기간 | 누적 |
|-------|------|----------|------|
| **Phase 1** | Foundation | 1주 | 1주 |
| **Phase 2** | Broker Integration | 1.5주 | 2.5주 |
| **Phase 3** | Data Layer | 1주 | 3.5주 |
| **Phase 4** | CANSLIM Screening | 1.5주 | 5주 |
| **Phase 5** | Strategy Engine | 2주 | 7주 |
| **Phase 6** | Portfolio Management | 1주 | 8주 |
| **Phase 7** | Bot Orchestration | 1.5주 | 9.5주 |
| **Phase 8** | Telegram (알림 + 조회 명령) | 1주 | 10.5주 |
| **Phase 8.5** | Web Dashboard (FastAPI + React) | 2주 | 12.5주 |
| **Phase 9** | Testing & Paper Trading | 1주 | 13.5주 |
| **Phase 10** | Deployment | 0.5주 | 14주 |
| **총 예상** | | **약 14주 (3.5개월)** | |

> **참고**: Phase 8(Telegram)은 봇 코어가 완성된 직후 붙이므로 모의투자를 Telegram으로 모니터링하면서 Phase 8.5(Web)를 병행할 수 있다. 이 경우 실질 일정은 13주로 단축 가능.

---

## 7. 리스크 & 완화 방안

### 7.1 기술 리스크

| 리스크 | 심각도 | 확률 | 완화 방안 |
|--------|--------|------|----------|
| WebSocket 장시간 끊김 | 🔴 높음 | 중간 | REST 폴백 (30초 간격), 재연결 로직, Telegram 즉시 알림 |
| 한투 API 점검/장애 | 🔴 높음 | 낮음 | 봇 일시 정지 → Telegram 알림 → 수동 개입 |
| 지정가 매도 미체결 (급락) | 🟡 중간 | 낮음 | 5초 후 가격 갱신 재주문, 최대 3회 재시도 |
| yfinance API 차단 | 🟡 중간 | 중간 | 배치 처리 + 딜레이, 차단 시 FMP 무료 티어 폴백 |
| SQLite 동시 접근 이슈 | 🟢 낮음 | 낮음 | 단일 프로세스(asyncio) 구조로 회피, WAL 모드 |

### 7.2 전략 리스크

| 리스크 | 설명 | 완화 |
|--------|------|------|
| $10,000 소액 한계 | 1-2종목 집중, 분산 어려움 | 1% 리스크 유지로 최대 손실 제한. 충분한 Paper Trading 후 실전 |
| CANSLIM 근사치 오차 | IBD 대비 70-85% 정확도 | 핵심 필터(C,A,N,S)는 95%+ 정확. 나머지는 보수적 임계값 |
| 연속 손절 심리 | 35-40% 승률 = 연속 5-7회 손절 가능 | 봇이 자동 실행하므로 심리 개입 최소화. 이게 봇의 장점 |

### 7.3 운영 리스크

| 리스크 | 완화 |
|--------|------|
| 서버 다운 | systemd 자동 재시작, 시작 시 포지션 동기화 |
| 네트워크 장애 | AWS us-east-1 리전, 고가용성 |
| API 키 유출 | .env 파일, git에 포함 안 함, 환경 변수 |
| 잘못된 주문 | Paper Trading으로 충분히 검증 후 실전 전환 |

---

## 8. 한투 API 핵심 엔드포인트 정리

### 8.1 실전/모의투자 URL

| 모드 | REST Base URL | WebSocket URL |
|------|--------------|---------------|
| 실전 | `https://openapi.koreainvestment.com:9443` | `ws://ops.koreainvestment.com:21000` |
| 모의 | `https://openapivts.koreainvestment.com:29443` | `ws://ops.koreainvestment.com:31000` |

### 8.2 사용할 주요 API

| 기능 | API 이름 | Method | Path | 용도 |
|------|---------|--------|------|------|
| 인증 | 접근토큰발급 | POST | `/oauth2/tokenP` | OAuth 토큰 |
| 인증 | 웹소켓접속키발급 | POST | `/oauth2/Approval` | WS 인증 |
| 시세 | 해외주식 현재가상세 | GET | `/uapi/overseas-price/v1/quotations/price-detail` | 현재가 |
| 시세 | 해외주식 기간별시세 | GET | `/uapi/overseas-price/v1/quotations/dailyprice` | 일봉 OHLCV |
| 주문 | 해외주식 주문 | POST | `/uapi/overseas-stock/v1/trading/order` | 매수/매도 |
| 주문 | 해외주식 정정취소주문 | POST | `/uapi/overseas-stock/v1/trading/order-rvsecncl` | 정정/취소 |
| 조회 | 해외주식 미체결내역 | GET | `/uapi/overseas-stock/v1/trading/inquire-nccs` | 미체결 |
| 조회 | 해외주식 잔고 | GET | `/uapi/overseas-stock/v1/trading/inquire-balance` | 보유종목 |
| 조회 | 해외주식 체결내역 | GET | `/uapi/overseas-stock/v1/trading/inquire-ccnl` | 체결 확인 |
| WS | 해외주식 실시간체결가 | WS | - | 실시간 가격 |
| WS | 해외주식 실시간호가 | WS | - | 실시간 호가 |
| WS | 해외주식 실시간체결통보 | WS | - | 주문 체결 알림 |

### 8.3 해외주식 거래소 코드

| 거래소 | 코드 | 비고 |
|--------|------|------|
| 나스닥 | NASD | 주요 성장주 |
| 뉴욕 | NYSE | 대형주 |
| 아멕스 | AMEX | 소형주/ETF |

---

## 9. 설정 파일 구조

### .env.example
```bash
# ===== Trading Mode =====
TRADING_MODE=paper                    # paper or live

# ===== Korea Investment Securities API =====
# 실전
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=12345678-01           # 계좌번호-상품코드

# 모의
KIS_PAPER_APP_KEY=your_paper_app_key
KIS_PAPER_APP_SECRET=your_paper_app_secret
KIS_PAPER_ACCOUNT_NO=12345678-01

# ===== Account =====
INITIAL_CAPITAL=100000                # Paper: $100,000 / Live: $10,000

# ===== Telegram =====
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# ===== Database =====
DB_PATH=data/snowa.db

# ===== Logging =====
LOG_LEVEL=INFO
LOG_FILE=logs/snowa_bot.log
```

---

## 10. 확인이 완료된 사항 (No Ambiguity)

아래 항목은 모두 확정되어 구현 시 추가 판단이 필요 없다:

- [x] 언어: Python 3.11+
- [x] 브로커: 한국투자증권 Open API (키 발급 완료)
- [x] 주문: 지정가만 (스톱/시장가 미지원 → 소프트웨어 스톱)
- [x] 실행: US 정규장 실시간 모니터링 (KST 23:30~06:00)
- [x] 데이터: yfinance (재무 벌크+증분) + 한투 API (실시간+과거 가격)
- [x] DB: SQLite
- [x] 모드: Paper ($100K) / Live ($10K) 설정으로 전환
- [x] 소액: 1% 리스크 유지, int(shares) ≥ 1이면 진입, 0이면 스킵
- [x] CANSLIM: C,A,N,S,I 자동화 + L,EPS,A/D 근사치 + Composite 자체 스코어
- [x] 알림: Telegram Bot
- [x] 백테스팅: 초기 제외
- [x] 배포: 클라우드 서버 (AWS/DO)
- [x] UI: 웹 대시보드 (FastAPI+React) + Telegram 명령 확장 (조회/제어)
- [x] 손절: min(2N, 10%) 하이브리드, 장중 실시간 모니터링
- [x] 진입: Donchian 돌파 시 즉시 (장중), 지정가+버퍼로 체결
- [x] 청산: Donchian 하단 이탈은 종가 기준 (장 마감 전 15분 확인)

---

## 부록: 향후 확장 계획 (Phase 2)

현재 스코프에서 제외했지만 추후 추가할 수 있는 기능:

1. **백테스팅 엔진** — 과거 데이터로 전략 시뮬레이션
2. **공매도 지원** — SHORT_ENABLED 활성화
3. **멀티 브로커** — IBKR, Alpaca 등 추가 브로커 지원
4. **ML 기반 필터** — CANSLIM 스코어 가중치 자동 최적화
5. **장전/장후 거래** — Extended hours 지원 (한투 API 확인 필요)
6. **모바일 앱** — React Native로 대시보드 모바일 버전
