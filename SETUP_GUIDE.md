# SNOWA Trading Bot — 설정 및 실행 가이드

> CANSLIM × Turtle Trading 하이브리드 자동매매 봇
> 한국투자증권 Open API 기반 미국/한국 주식 자동매매

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
16. [한국 시장 (KR) 설정](#16-한국-시장-kr-설정)

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
**약 2~4시간 소요** (미국 8,000+ 종목 대상).

> **한국 시장**: 한국 시장 데이터는 pykrx를 통해 봇 실행 시 자동으로 수집됩니다. 별도의 초기 데이터 수집이 필요하지 않습니다.

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

#### 미국 시장 (US)

| 시간 (KST) | 동작 | 설명 |
|------------|------|------|
| **22:00** | 장전 준비 | 토큰 갱신, 데이터 갱신, ATR/Donchian 계산, 트리거 사전 계산 |
| **23:30** | 장 시작 | WebSocket 연결, 실시간 모니터링 시작 |
| **23:30~06:00** | 장중 모니터링 | 실시간 틱 수신 → 손절/피라미딩/진입/청산 신호 판단 |
| **06:00** | 장 종료 | WebSocket 종료 |
| **06:30** | 장후 정리 | 브로커 동기화, 미체결 처리, 일일 리포트 생성 |

#### 한국 시장 (KR)

| 시간 (KST) | 동작 | 설명 |
|------------|------|------|
| **08:00** | 장전 준비 | 토큰 갱신, pykrx 데이터 갱신, ATR/Donchian 계산 |
| **09:00** | 장 시작 | WebSocket 연결 (국내), 실시간 모니터링 시작 |
| **09:00~15:30** | 장중 모니터링 | 실시간 틱 수신 → 손절/피라미딩/진입/청산 신호 판단 |
| **15:30** | 장 종료 | WebSocket 종료 |
| **16:00** | 장후 정리 | 브로커 동기화, 미체결 처리, 일일 리포트 생성 |

> **참고**: 미국/한국 시장은 **독립적으로 스케줄링**됩니다. 두 시장을 동시에 활성화하면 각각의 스케줄에 따라 자동 운영됩니다.

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
| `GET /api/status?market=US` | 봇 상태 (모드, 시장필터, 유닛, 계좌) |
| `GET /api/positions?market=US` | 보유 포지션 (유닛별 상세) |
| `GET /api/watchlist?market=US` | 워치리스트 (CANSLIM 점수) |
| `GET /api/trades?limit=20&market=US` | 최근 거래 내역 |
| `GET /api/pnl?period=daily&market=US` | 수익률 (일/주/월별) |
| `GET /api/journal?month=2026-02` | 매매일지 (승률, R:R) |
| `GET /api/market/status` | 시장별 활성화 상태 조회 |
| `POST /api/market/{market_id}/toggle` | 시장 활성화/비활성화 토글 |

> **market 파라미터**: 모든 조회 API에 `market=US` (기본값) 또는 `market=KR`을 지정할 수 있습니다. 생략 시 미국 시장이 조회됩니다.

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

### Q: 한국 시장 워치리스트가 비어있어요

**원인**: pykrx 미설치 또는 한국 시장 미활성화
**해결**:
1. `pip install pykrx` 설치 확인
2. API로 한국 시장 활성화: `POST /api/market/KR/toggle` with `{"enabled": true}`
3. 봇 재시작 후 한국 장전 준비(08:00 KST)에 자동 스크리닝 실행 대기
4. 수동 확인: `curl http://localhost:8000/api/watchlist?market=KR`

### Q: KODEX200 시장 필터가 FAIL이에요

**원인**: pykrx에서 KODEX200 데이터를 가져오지 못했거나 시장 약세
**해결**:
- `curl http://localhost:8000/api/status?market=KR`로 시장 필터 상태 확인
- `close < sma200`이면 정상적인 FAIL (약세장 → 신규 진입 차단)
- 데이터 미수신 시 pykrx 버전 업데이트: `pip install --upgrade pykrx`

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
│   ├── constants.py        # 전략 상수 (모든 임계값)
│   ├── market_config.py    # 시장별 설정 (US/KR 스케줄, 거래소, 벤치마크)
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
│   ├── universe.py         # NYSE+NASDAQ 유니버스 (US)
│   ├── universe_kr.py      # KOSPI+KOSDAQ 유니버스 (KR, pykrx)
│   ├── fundamental_data.py # 재무 데이터 (US: yfinance, KR: pykrx)
│   ├── price_cache.py      # 가격 캐시 (US: yfinance, KR: pykrx)
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
│   │   └── routes/         # API 라우트 (시장별 필터 지원)
│   │       ├── status.py           # 봇 상태
│   │       ├── positions.py        # 포지션 조회
│   │       ├── watchlist.py        # 워치리스트
│   │       ├── trades.py           # 거래 내역
│   │       ├── performance.py      # 수익률
│   │       ├── journal.py          # 매매일지
│   │       ├── market_control.py   # 시장 토글 API (US/KR)
│   │       └── ...
│   └── frontend/           # React SPA (시장 선택기 포함)
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

## 16. 한국 시장 (KR) 설정

### 16.1 개요

SNOWA Trading Bot은 미국 시장(US)과 한국 시장(KR)을 **동시에** 자동매매할 수 있습니다.

| 항목 | 미국 시장 (US) | 한국 시장 (KR) |
|------|---------------|---------------|
| 거래소 | NYSE, NASDAQ, AMEX | KOSPI, KOSDAQ |
| 통화 | USD | KRW |
| 벤치마크 | SPY (S&P 500 ETF) | KODEX200 (069500) |
| 데이터 소스 | yfinance | pykrx |
| 장 시간 (KST) | 23:30 ~ 06:00 | 09:00 ~ 15:30 |
| 시장 필터 | SPY > 200일 SMA | KODEX200 > 200일 SMA |

### 16.2 추가 의존성 설치

한국 시장 기능은 **pykrx** 라이브러리가 필요합니다:

```bash
source .venv/bin/activate
pip install pykrx
```

> pykrx는 한국거래소(KRX)에서 KOSPI/KOSDAQ 종목 리스트, OHLCV 가격, 재무 데이터를 가져옵니다.

### 16.3 한국 시장 활성화

한국 시장은 기본적으로 **비활성화** 상태입니다. 활성화 방법:

#### 방법 1: 웹 대시보드 (권장)

1. 대시보드 접속
2. 사이드바에서 시장 선택기 확인 (🇺🇸 US / 🇰🇷 KR / 🌐 전체)
3. 설정에서 한국 시장 토글을 **ON**으로 변경

#### 방법 2: API 호출

```bash
# 한국 시장 활성화
curl -X POST http://localhost:8000/api/market/KR/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# 시장 상태 확인
curl http://localhost:8000/api/market/status
```

응답 예시:
```json
{
  "markets": [
    {
      "market_id": "US",
      "display_name": "미국 주식",
      "enabled": true,
      "currency": "USD",
      "exchanges": ["NASD", "NYSE", "AMEX"]
    },
    {
      "market_id": "KR",
      "display_name": "한국 주식",
      "enabled": true,
      "currency": "KRW",
      "exchanges": ["KOSPI", "KOSDAQ"]
    }
  ]
}
```

### 16.4 한국 시장 데이터 조회

모든 API 엔드포인트에 `market=KR` 파라미터를 추가하면 한국 시장 데이터를 조회할 수 있습니다:

```bash
# 한국 시장 봇 상태
curl http://localhost:8000/api/status?market=KR

# 한국 시장 포지션
curl http://localhost:8000/api/positions?market=KR

# 한국 시장 워치리스트
curl http://localhost:8000/api/watchlist?market=KR

# 한국 시장 거래 내역
curl http://localhost:8000/api/trades?market=KR
```

### 16.5 한국 CANSLIM 스크리닝 기준

한국 시장은 미국 시장과 다른 스크리닝 임계값을 사용합니다:

| 항목 | 미국 (US) | 한국 (KR) | 이유 |
|------|-----------|-----------|------|
| 최소 가격 | $10 | ₩5,000 | 동전주 제외 |
| 최소 거래량 (ADV) | 500,000주 | 50,000주 | 유동성 규모 차이 |
| RS Rating 기준 | 상위 30% | 상위 30% | 동일 |
| 시장 필터 | SPY > 200 SMA | KODEX200 > 200 SMA | 각 시장 벤치마크 |

### 16.6 호가 단위 (Tick Size)

한국 시장은 가격대별로 호가 단위가 다릅니다. 봇이 주문 시 자동으로 적용합니다:

| 주가 범위 | 호가 단위 |
|-----------|----------|
| ~ ₩2,000 | ₩1 |
| ₩2,000 ~ ₩5,000 | ₩5 |
| ₩5,000 ~ ₩20,000 | ₩10 |
| ₩20,000 ~ ₩50,000 | ₩50 |
| ₩50,000 ~ ₩200,000 | ₩100 |
| ₩200,000 ~ ₩500,000 | ₩500 |
| ₩500,000 ~ | ₩1,000 |

### 16.7 대시보드 시장 선택기

웹 대시보드 사이드바에 시장 선택기가 포함되어 있습니다:

- 🇺🇸 **US** — 미국 시장 데이터만 표시
- 🇰🇷 **KR** — 한국 시장 데이터만 표시
- 🌐 **전체** — 모든 시장 데이터 표시

선택한 시장은 대시보드의 모든 페이지(상태, 포지션, 워치리스트, 거래, P&L)에 자동 반영됩니다.

### 16.8 한국 시장 주의사항

1. **pykrx 데이터 캐시**: 유니버스 데이터는 7일간 CSV 캐시됩니다 (`data/kr_universe_cache.csv`)
2. **장 시간 차이**: 한국 장(09:00~15:30 KST)과 미국 장(23:30~06:00 KST)은 겹치지 않아 동시 운영이 가능합니다
3. **KIS API 키**: 미국/한국 시장 모두 **같은 한국투자증권 API 키**를 사용합니다 (별도 발급 불필요)
4. **모의투자 제한**: Paper 모드에서 한국 시장 모의투자 이용 시 한국투자증권 앱에서 **국내 모의투자**도 별도 신청해야 합니다
5. **DB 마이그레이션**: 봇이 처음 실행될 때 기존 테이블에 `market` 컬럼이 자동 추가됩니다 (기존 데이터는 모두 `US`로 설정)

---

## 빠른 시작 체크리스트

### 미국 시장 (US)

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

### 한국 시장 (KR) 추가

```
[ ] 1. pykrx 설치 (pip install pykrx)
[ ] 2. 봇 실행 (미국 시장과 동일한 인스턴스)
[ ] 3. 대시보드 또는 API로 한국 시장 활성화
[ ] 4. 대시보드에서 시장 선택기로 KR 데이터 확인
[ ] 5. Paper 모드에서 충분히 테스트 후 Live 전환
```
