# SNOWA Trading Bot — 설정 및 실행 가이드

> CANSLIM × Turtle Trading 하이브리드 자동매매 봇  
> 한국투자증권 Open API 기반 미국 주식 자동매매

---

## 목차

1. [시스템 요구사항](#1-시스템-요구사항)
2. [프로젝트 설치](#2-프로젝트-설치)
3. [한국투자증권 API 설정](#3-한국투자증권-api-설정)
4. [Telegram 봇 설정](#4-telegram-봇-설정)
5. [환경변수 설정 (.env)](#5-환경변수-설정-env)
6. [초기 데이터 수집](#6-초기-데이터-수집)
7. [봇 실행](#7-봇-실행)
8. [웹 대시보드 실행](#8-웹-대시보드-실행)
9. [운영 모드 (Paper/Live)](#9-운영-모드-paperlive)
10. [주요 명령어 및 기능](#10-주요-명령어-및-기능)
11. [로그 및 모니터링](#11-로그-및-모니터링)
12. [긴급 정지 (킬스위치)](#12-긴급-정지-킬스위치)
13. [클라우드 서버 배포](#13-클라우드-서버-배포)
14. [문제 해결 (FAQ)](#14-문제-해결-faq)
15. [프로젝트 구조](#15-프로젝트-구조)

---

## 1. 시스템 요구사항

| 항목 | 최소 요구 | 권장 |
|------|-----------|------|
| Python | 3.11 이상 | 3.12 |
| OS | macOS / Linux / Windows (WSL) | Ubuntu 22.04+ |
| RAM | 2GB | 4GB |
| 디스크 | 1GB | 5GB (데이터 캐시 포함) |
| 네트워크 | 안정적 인터넷 연결 필수 | 유선 or 클라우드 서버 |

### 필수 외부 서비스
- **한국투자증권 계좌** — Open API 신청 완료
- **Telegram 봇** — BotFather로 생성
- **(선택) 클라우드 서버** — 24시간 운영 시 (AWS EC2, DigitalOcean 등)

---

## 2. 프로젝트 설치

### 2.1 저장소 클론

```bash
git clone <repository-url> snowa_tradingbot
cd snowa_tradingbot
```

### 2.2 가상환경 생성 및 활성화

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
```

### 2.3 의존성 설치

```bash
pip install -e .
```

개발 도구 포함 설치:
```bash
pip install -e ".[dev]"
```

### 2.4 디렉토리 생성

```bash
mkdir -p data logs
```

---

## 3. 한국투자증권 API 설정

### 3.1 API 신청

1. [한국투자증권 Open API](https://apiportal.koreainvestment.com/) 접속
2. 회원가입 후 **API 이용 신청**
3. **모의투자 API** 먼저 발급 (Paper Trading용)
4. 실전 운용 시 **실전 API** 별도 발급

### 3.2 발급받는 키

| 키 | 설명 | 사용처 |
|-----|------|--------|
| `APP_KEY` | 앱 키 | REST API 인증 |
| `APP_SECRET` | 앱 시크릿 | REST API 인증 |
| `계좌번호` | `XXXXXXXX-XX` 형식 | 주문/잔고 조회 |

> **중요**: 모의투자와 실전의 APP_KEY/SECRET이 **다릅니다**. 각각 별도 발급.

### 3.3 모의투자 계좌 개설

1. 한국투자증권 앱 → 메뉴 → 모의투자 → 해외주식 모의투자 신청
2. 모의투자 계좌번호 확인 (실전 계좌번호와 다름)

---

## 4. Telegram 봇 설정

### 4.1 봇 생성

1. Telegram에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령 입력
3. 봇 이름 설정 (예: `SNOWA Trading Bot`)
4. 봇 유저네임 설정 (예: `snowa_trading_bot`)
5. **HTTP API Token** 복사 → `.env`의 `TELEGRAM_BOT_TOKEN`에 입력

### 4.2 Chat ID 확인

1. 생성한 봇에게 아무 메시지 전송
2. 브라우저에서 접속: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. 응답에서 `"chat":{"id":123456789}` 값 복사
4. `.env`의 `TELEGRAM_CHAT_ID`에 입력

> **보안 주의**: Chat ID를 설정하면 해당 사용자만 봇 명령어를 사용할 수 있습니다.

---

## 5. 환경변수 설정 (.env)

`.env.example`을 복사하여 `.env` 파일을 생성합니다:

```bash
cp .env.example .env
```

`.env` 파일 편집:

```ini
# ===== Trading Mode =====
TRADING_MODE=paper                    # paper(모의) 또는 live(실전)

# ===== 한투 API — 실전 =====
KIS_APP_KEY=your_live_app_key
KIS_APP_SECRET=your_live_app_secret
KIS_ACCOUNT_NO=12345678-01           # 실전 계좌번호-상품코드

# ===== 한투 API — 모의투자 =====
KIS_PAPER_APP_KEY=your_paper_app_key
KIS_PAPER_APP_SECRET=your_paper_app_secret
KIS_PAPER_ACCOUNT_NO=12345678-01     # 모의투자 계좌번호-상품코드

# ===== Telegram =====
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIjKlMnOpQrStUvWxYz
TELEGRAM_CHAT_ID=123456789

# ===== 데이터베이스 =====
DB_PATH=data/snowa.db

# ===== 로깅 =====
LOG_LEVEL=INFO                        # DEBUG, INFO, WARNING, ERROR
LOG_FILE=logs/snowa_bot.log

# ===== 웹 대시보드 (선택) =====
# DASHBOARD_API_KEY=your_secret_key   # 설정하면 API 키 인증 활성화
```

> **보안**: `.env` 파일은 절대 Git에 커밋하지 마세요. `.gitignore`에 이미 포함되어 있습니다.

---

## 6. 초기 데이터 수집

봇을 처음 실행하기 전에 과거 데이터를 수집해야 합니다.  
**약 2~4시간 소요** (8,000+ 종목 대상).

### 6.1 전체 데이터 수집 (권장)

```bash
source .venv/bin/activate
python -m scripts.initial_data_load --mode all
```

### 6.2 개별 수집

```bash
# 유니버스 (NYSE + NASDAQ 종목 리스트)
python -m scripts.initial_data_load --mode universe

# 가격 데이터 (300일 일봉 OHLCV)
python -m scripts.initial_data_load --mode prices

# 재무 데이터 (EPS, 매출, 기관보유 등)
python -m scripts.initial_data_load --mode fundamentals
```

### 6.3 수집 완료 확인

```bash
# DB 파일 크기 확인 (정상: 수백 MB)
ls -lh data/snowa.db

# 테이블 행 수 확인
python -c "
import sqlite3
conn = sqlite3.connect('data/snowa.db')
for table in ['daily_prices', 'fundamentals', 'watchlist']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {count:,} 행')
conn.close()
"
```

---

## 7. 봇 실행

### 7.1 기본 실행

```bash
source .venv/bin/activate
python -m scripts.run_bot
```

또는 설치된 엔트리포인트 사용:

```bash
snowa-bot
```

### 7.2 봇 동작 사이클 (자동)

| 시간 (KST) | 동작 | 설명 |
|------------|------|------|
| **22:00** | 장전 준비 | 토큰 갱신, 데이터 갱신, ATR/Donchian 계산, 트리거 사전 계산 |
| **23:30** | 장 시작 | WebSocket 연결, 실시간 모니터링 시작 |
| **23:30~06:00** | 장중 모니터링 | 실시간 틱 수신 → 손절/피라미딩/진입/청산 신호 판단 |
| **06:00** | 장 종료 | WebSocket 종료 |
| **06:30** | 장후 정리 | 브로커 동기화, 미체결 처리, 일일 리포트 생성 |

### 7.3 백그라운드 실행 (서버)

```bash
# nohup으로 백그라운드 실행
nohup python -m scripts.run_bot > /dev/null 2>&1 &

# systemd 서비스로 등록 (권장 — 아래 13장 참조)
```

---

## 8. 웹 대시보드 실행

### 8.1 API 서버 실행

```bash
source .venv/bin/activate
uvicorn web.api.main:app --host 0.0.0.0 --port 8000
```

### 8.2 접속

- API 문서: `http://localhost:8000/docs` (Swagger UI)
- 헬스 체크: `http://localhost:8000/api/health`

### 8.3 주요 API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/status` | 봇 상태 (모드, 시장필터, 유닛, 계좌) |
| `GET /api/positions` | 보유 포지션 (유닛별 상세) |
| `GET /api/watchlist` | 워치리스트 (CANSLIM 점수) |
| `GET /api/trades?limit=20` | 최근 거래 내역 |
| `GET /api/pnl?period=daily` | 수익률 (일/주/월별) |
| `GET /api/journal?month=2026-02` | 매매일지 (승률, R:R) |

### 8.4 API 키 인증 (선택)

`.env`에 `DASHBOARD_API_KEY`를 설정하면 모든 API 요청에 헤더 필요:

```bash
curl -H "X-API-Key: your_secret_key" http://localhost:8000/api/status
```

---

## 9. 운영 모드 (Paper/Live)

### 9.1 모드 전환

`.env` 파일에서 `TRADING_MODE` 값 변경:

```ini
# 모의투자 (기본값)
TRADING_MODE=paper

# 실전투자
TRADING_MODE=live
```

> **주의**: 모드 전환 시 봇을 재시작해야 합니다.

### 9.2 모드별 차이

| 항목 | Paper | Live |
|------|-------|------|
| API 서버 | `openapivts.koreainvestment.com:29443` | `openapi.koreainvestment.com:9443` |
| WebSocket | `ops.koreainvestment.com:31000` | `ops.koreainvestment.com:21000` |
| 주문 TR_ID | `VTTT1002U` (매수) | `TTTT1002U` (매수) |
| 자본 기준 | 모의계좌 잔고 자동 인식 | 실전계좌 잔고 자동 인식 |
| 실제 주문 | 모의 체결 | **실제 돈으로 체결** |

### 9.3 Live 전환 체크리스트

- [ ] Paper 모드에서 최소 2주 이상 정상 운영 확인
- [ ] 실전 API 키 발급 및 `.env`에 입력
- [ ] 실제 계좌에 투자 금액 입금 확인 (봇 시작 시 자동으로 계좌 잔고를 조회하여 기록)
- [ ] `TRADING_MODE=live`로 변경
- [ ] Telegram으로 모드 확인: `/mode` 명령
- [ ] 소액으로 시작 후 점진적 증액 권장

---

## 10. 주요 명령어 및 기능

### 10.1 Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 시작 + 명령어 목록 |
| `/stop` | **긴급 정지** (모든 모니터링 중단) |
| `/mode` | 현재 모드 확인 (Paper/Live) |
| `/status` | 봇 상태 (연결, 시장필터, 유닛 사용량) |
| `/positions` | 보유 포지션 상세 (유닛별 진입가, 손절, P&L) |
| `/watchlist` | 감시 리스트 (CANSLIM 점수 + 돌파 레벨) |
| `/orders` | 미체결 주문 현황 |
| `/pnl` | 수익률 요약 (오늘/주간/월간/누적) |
| `/trades` | 최근 거래 내역 (기본 10건) |
| `/trades 20` | 최근 20건 |
| `/journal` | 이번 달 매매일지 |
| `/journal 2026-01` | 특정 월 매매일지 |

### 10.2 자동 알림

봇이 다음 이벤트 발생 시 자동으로 Telegram 알림을 보냅니다:

- 🟢 **진입 알림** — 종목, 시스템, 유닛, 수량, 가격, 손절, 리스크
- 🔴 **손절 알림** — 종목, 원인, 수량, 가격, 손실
- 🔵 **청산 알림** — 종목, 시스템 청산, 수량, 가격, 손익
- ⚠️ **에러 알림** — 연결 끊김, 주문 실패
- 📊 **일일 요약** — 장후 자동 발송 (계좌, 보유, 오늘 활동)

---

## 11. 로그 및 모니터링

### 11.1 로그 위치

```
logs/snowa_bot.log    # 메인 봇 로그
```

### 11.2 로그 레벨 변경

`.env`에서 `LOG_LEVEL` 변경:

```ini
LOG_LEVEL=DEBUG     # 최대 상세 (개발/디버깅)
LOG_LEVEL=INFO      # 일반 운영 (기본값)
LOG_LEVEL=WARNING   # 경고 이상만
```

### 11.3 실시간 로그 확인

```bash
tail -f logs/snowa_bot.log
```

### 11.4 구조화 로그 (structlog)

모든 로그는 JSON 형식 구조화 로그입니다:

```json
{"event": "order_entry_submitted", "ticker": "NVDA", "shares": 12, "price": 450.25, "timestamp": "2026-02-14T23:45:00Z"}
```

---

## 12. 긴급 정지 (킬스위치)

### 방법 1: Telegram 명령어

```
/stop
```

### 방법 2: 킬스위치 파일

프로젝트 루트에 `KILL_SWITCH` 파일 생성:

```bash
touch KILL_SWITCH
```

봇이 1초 간격으로 이 파일을 감지하며, 발견 시 즉시 정지합니다.

### 정지 후 재시작

```bash
# 킬스위치 파일 제거
rm KILL_SWITCH

# 봇 재시작
python -m scripts.run_bot
```

> **참고**: 긴급 정지는 **모니터링만 중단**합니다. 기존 보유 포지션은 유지됩니다.  
> 포지션 수동 청산은 한국투자증권 앱/웹에서 직접 처리하세요.

---

## 13. 클라우드 서버 배포

### 13.1 권장 사양

| 항목 | 사양 |
|------|------|
| 인스턴스 | AWS EC2 `t3.small` 또는 DigitalOcean `s-1vcpu-2gb` |
| OS | Ubuntu 22.04 LTS |
| CPU | 1 vCPU |
| RAM | 2GB |
| 스토리지 | 20GB SSD |
| 월 비용 | 약 $10~15 |

### 13.2 서버 초기 설정

```bash
# Python 3.11 설치 (Ubuntu)
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git

# 프로젝트 클론
git clone <repository-url> ~/snowa_tradingbot
cd ~/snowa_tradingbot

# 가상환경 + 의존성
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# 환경변수 설정
cp .env.example .env
nano .env    # 키 입력

# 디렉토리 생성
mkdir -p data logs

# 초기 데이터 수집
python -m scripts.initial_data_load --mode all
```

### 13.3 systemd 서비스 등록

`/etc/systemd/system/snowa-bot.service` 파일 생성:

```ini
[Unit]
Description=SNOWA Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/snowa_tradingbot
ExecStart=/home/ubuntu/snowa_tradingbot/.venv/bin/python -m scripts.run_bot
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

서비스 등록 및 시작:

```bash
sudo systemctl daemon-reload
sudo systemctl enable snowa-bot
sudo systemctl start snowa-bot

# 상태 확인
sudo systemctl status snowa-bot

# 로그 확인
sudo journalctl -u snowa-bot -f
```

### 13.4 웹 대시보드 서비스 (선택)

`/etc/systemd/system/snowa-web.service`:

```ini
[Unit]
Description=SNOWA Trading Bot Web Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/snowa_tradingbot
ExecStart=/home/ubuntu/snowa_tradingbot/.venv/bin/uvicorn web.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 13.5 Nginx 리버스 프록시 (선택)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        root /home/ubuntu/snowa_tradingbot/web/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

---

## 14. 문제 해결 (FAQ)

### Q: "토큰 발급 실패" 에러가 나요

**원인**: 한투 API 키가 잘못되었거나 만료됨  
**해결**:
1. `.env`의 `KIS_APP_KEY`, `KIS_APP_SECRET` 확인
2. 모의/실전 키가 섞이지 않았는지 확인
3. API 포털에서 키 재발급

### Q: WebSocket 연결이 자꾸 끊겨요

**원인**: 네트워크 불안정 또는 한투 서버 점검  
**해결**:
- 봇은 자동 재연결합니다 (지수 백오프: 1→2→4→8→16→30초)
- 60초 이상 무응답 시 자동 재연결 트리거
- WS 완전 실패 시 REST 폴링 폴백 (30초 간격)

### Q: 주문이 체결되지 않아요

**원인**: 지정가 주문이므로 시장가와 차이가 클 수 있음  
**해결**:
- 진입: 현재가 + 0.3% 버퍼로 지정가
- 손절: 현재가 - 0.5% 버퍼로 지정가, 최대 3회 재시도
- 미체결 주문은 장후에 자동 취소됨

### Q: Telegram 봇이 응답하지 않아요

**원인**: 토큰 오류 또는 Chat ID 불일치  
**해결**:
1. `TELEGRAM_BOT_TOKEN` 정확한지 확인
2. `TELEGRAM_CHAT_ID` 숫자 맞는지 확인
3. 봇에게 먼저 `/start` 메시지를 보냈는지 확인

### Q: 데이터 수집이 너무 오래 걸려요

**원인**: 8,000+ 종목 대상, yfinance 속도 제한  
**해결**:
- 첫 수집은 2~4시간 정상
- 배치 100종목씩 + 1초 딜레이 (차단 방지)
- 이후 증분 업데이트만 하므로 빠름

### Q: DB 파일이 손상된 것 같아요

**해결**:
```bash
# DB 백업
cp data/snowa.db data/snowa_backup_$(date +%Y%m%d).db

# DB 초기화 (데이터 재수집 필요)
rm data/snowa.db
python -m scripts.initial_data_load --mode all
```

---

## 15. 프로젝트 구조

```
snowa_tradingbot/
├── .env                    # 환경변수 (절대 커밋 금지!)
├── .env.example            # 환경변수 템플릿
├── pyproject.toml          # 프로젝트 설정 + 의존성
├── SETUP_GUIDE.md          # ← 이 파일
├── IMPLEMENTATION_PLAN.md  # 구현 계획서
├── TURTLE_TRADING_STRATEGY.md  # 전략 명세서
├── QUANTIFIED_STRATEGY.md  # CANSLIM 정량화 기준
│
├── config/                 # 설정
│   ├── settings.py         # pydantic-settings (환경변수 로드)
│   ├── constants.py        # 전략 상수 (204줄, 모든 임계값)
│   └── logging_config.py   # structlog 설정
│
├── core/                   # 핵심 인프라
│   ├── database.py         # SQLite 9개 테이블
│   ├── models.py           # 14개 dataclass + 12개 enum
│   └── events.py           # 비동기 이벤트 버스
│
├── broker/                 # 한투 API 연동
│   ├── kis_auth.py         # OAuth 인증
│   ├── kis_rest.py         # REST 클라이언트
│   ├── kis_websocket.py    # WebSocket 클라이언트
│   ├── order_executor.py   # 주문 실행 엔진
│   └── account.py          # 계좌 관리
│
├── data/                   # 데이터 레이어
│   ├── universe.py         # NYSE+NASDAQ 유니버스
│   ├── fundamental_data.py # 재무 데이터 (yfinance)
│   ├── price_cache.py      # 가격 캐시
│   └── market_data.py      # 통합 시세 인터페이스
│
├── screening/              # CANSLIM 스크리닝
│   ├── canslim_screener.py # 7개 필터 (C,A,N,S,L,I,추가)
│   ├── rs_rating.py        # RS Rating 계산기
│   ├── custom_composite.py # Composite Score
│   ├── minervini_template.py # Minervini 8조건
│   └── watchlist_manager.py  # 워치리스트 매니저
│
├── strategy/               # 매매 전략 (순수 함수)
│   ├── atr.py              # ATR(N) 계산
│   ├── donchian.py         # Donchian Channel
│   ├── entry_signals.py    # System 1/2 진입 신호
│   ├── exit_signals.py     # Donchian 청산 신호
│   ├── stop_loss.py        # 하이브리드 손절 (min(2N, 10%))
│   ├── pyramiding.py       # 피라미딩 (0.5N 간격)
│   ├── breakout_tracker.py # 돌파 이력 추적
│   └── market_filter.py    # 시장 필터 (SPY > 200SMA)
│
├── portfolio/              # 포트폴리오 관리
│   ├── position_sizer.py   # 유닛 크기 계산
│   ├── position_manager.py # 포지션 CRUD
│   ├── risk_manager.py     # 리스크 한도 관리
│   └── correlation_groups.py # 상관 그룹
│
├── bot/                    # 봇 오케스트레이션
│   ├── trading_bot.py      # 메인 오케스트레이터
│   ├── pre_market.py       # 장전 준비
│   ├── intraday_monitor.py # 장중 모니터링
│   ├── post_market.py      # 장후 정리
│   └── mode.py             # Paper/Live 모드
│
├── notifications/          # 알림
│   └── telegram_bot.py     # Telegram 봇 (11개 명령어)
│
├── web/                    # 웹 대시보드
│   ├── api/
│   │   ├── main.py         # FastAPI 엔트리포인트
│   │   ├── dependencies.py # DB, 인증
│   │   └── routes/         # 6개 API 라우트
│   └── frontend/           # React (향후 확장)
│
├── scripts/                # 유틸리티
│   ├── run_bot.py          # 메인 진입점
│   └── initial_data_load.py # 벌크 데이터 로더
│
├── data/                   # 런타임 데이터
│   └── snowa.db            # SQLite 데이터베이스
│
└── logs/                   # 로그 파일
    └── snowa_bot.log
```

---

## 빠른 시작 체크리스트

```
[ ] 1. Python 3.11+ 설치
[ ] 2. 가상환경 생성 + 의존성 설치
[ ] 3. 한투 API 키 발급 (모의투자)
[ ] 4. Telegram 봇 생성 + Chat ID 확인
[ ] 5. .env 파일 작성 (모든 키 입력)
[ ] 6. 초기 데이터 수집 (python -m scripts.initial_data_load --mode all)
[ ] 7. 봇 실행 (python -m scripts.run_bot)
[ ] 8. Telegram에서 /status 확인
[ ] 9. 2주 이상 Paper 모드 운영 후 Live 전환 검토
```
