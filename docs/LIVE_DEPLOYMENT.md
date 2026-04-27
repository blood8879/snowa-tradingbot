# Snowa Trading Bot — Live 모드 AWS 배포 가이드

> **목적**: 새로운 AWS EC2 인스턴스에 **실전(live) 모드 전용** Snowa Trading Bot을 설치한다. 기존 paper 모드 서버(43.202.181.170)와 **완전히 독립**된 인스턴스를 구축하며, paper 서버와 동일한 소프트웨어 스택/systemd 설정을 유지한다.
>
> **대상**: 이 문서를 읽고 그대로 실행하는 AI 에이전트. 사람이 단계별로 따라가는 가이드이자, AI가 자동화 스크립트로 변환할 수 있는 실행 지시서이다.
>
> **중요**: 본 문서의 명령어는 **복사-붙여넣기 실행 가능**한 완성형이다. `<PLACEHOLDER>`로 표시된 부분만 사용자 환경에 맞게 치환하면 된다.

---

## 목차

1. [기존 Paper 서버 스펙 (복제 대상)](#1-기존-paper-서버-스펙-복제-대상)
2. [사전 준비물 체크리스트](#2-사전-준비물-체크리스트)
3. [AWS 인프라 구축](#3-aws-인프라-구축)
4. [EC2 OS 초기 설정](#4-ec2-os-초기-설정)
5. [런타임 설치 (Python + Node.js)](#5-런타임-설치-python--nodejs)
6. [프로젝트 배포 & 빌드](#6-프로젝트-배포--빌드)
7. [Live 모드 .env 설정 (핵심)](#7-live-모드-env-설정-핵심)
8. [systemd 서비스 등록](#8-systemd-서비스-등록)
9. [실행 & 검증](#9-실행--검증)
10. [운영 자동화 (백업 + 헬스체크)](#10-운영-자동화-백업--헬스체크)
11. [Paper ↔ Live 서버 간 데이터 격리](#11-paper--live-서버-간-데이터-격리)
12. [Live 전환 전 최종 체크리스트](#12-live-전환-전-최종-체크리스트)
13. [트러블슈팅](#13-트러블슈팅)
14. [알려진 이슈 / 이번 배포에서 수정된 항목](#14-알려진-이슈--이번-배포에서-수정된-항목)
15. [부록: 단일 스크립트 버전](#15-부록-단일-스크립트-버전)

---

## 1. 기존 Paper 서버 스펙 (복제 대상)

신규 Live 서버는 아래 paper 서버 스펙과 **동일**하게 구성한다.

| 항목 | Paper 서버 현황 | Live 서버 목표 |
|------|----------------|---------------|
| **인스턴스 IP** | 43.202.181.170 | 신규 Elastic IP |
| **리전** | ap-northeast-2 (서울) | ap-northeast-2 (서울) |
| **OS** | Ubuntu 24.04.4 LTS (Noble) | Ubuntu 24.04 LTS |
| **인스턴스 유형** | t3.small (권장) | **t3.small** |
| **디스크** | 29GB gp3 | **30GB gp3** |
| **Swap** | 2GB swapfile | **2GB swapfile** |
| **Python** | 3.12.3 (OS 기본) | **3.12 (OS 기본)** |
| **Node.js** | v18.19.1 | **v20.x (LTS)** |
| **프로젝트 경로** | `/home/ubuntu/apps/snowa_tradingbot` | **동일** |
| **가상환경 경로** | `.venv` (프로젝트 루트 아래) | **동일** |
| **DB 파일** | `data/snowa.db` (SQLite, ~200MB) | **빈 DB에서 시작** |
| **시간대** | Asia/Seoul (KST) | **Asia/Seoul (KST)** |
| **systemd 서비스** | `snowa-bot`, `snowa-dashboard` | **동일** |
| **대시보드 포트** | 8000 (직접, nginx 없음) | **동일** |
| **Nginx** | 미사용 | 미사용 |
| **User 계정** | ubuntu:ubuntu | **ubuntu:ubuntu** |
| **Trading Mode** | paper | **live** ⚠️ |

> Paper 서버는 nginx 없이 uvicorn이 직접 포트 8000으로 대시보드를 서빙한다. Live 서버도 동일 구조를 유지한다. HTTPS 필요 시 나중에 Nginx + Let's Encrypt를 별도로 추가한다.

---

## 2. 사전 준비물 체크리스트

배포 시작 전 반드시 아래 항목을 확보한다. **하나라도 빠지면 중간에 멈춤**.

### 2.1 AWS 계정
- AWS 콘솔 로그인 가능 (https://console.aws.amazon.com)
- 결제 정보 등록 완료
- 리전: **ap-northeast-2 (서울)** 로 전환

### 2.2 KIS 실전 API 발급 (Paper와 다름!)

한국투자증권 실전 API는 **별도 발급**이 필요하다.

1. https://apiportal.koreainvestment.com 접속
2. 로그인 (증권 계좌와 연결)
3. 상단 메뉴 **신청 > 실전투자 신청**
4. 필요 정보:
   - **KIS_APP_KEY** (실전)
   - **KIS_APP_SECRET** (실전)
   - **KIS_ACCOUNT_NO** (실전 계좌번호, 8자리-01 형식. 예: `50012345-01`)

> Paper API는 `openapivts.koreainvestment.com:29443`, Live API는 `openapi.koreainvestment.com:9443`로 엔드포인트가 다르다. 코드는 `.env`의 `TRADING_MODE`에 따라 자동 선택한다.

#### 2.2.1 KIS 키 형식 검증 (실수 방지)

발급된 키를 `.env`에 입력하기 전 형식부터 확인하면 시간 낭비를 줄인다. **잘못된 키를 그대로 운영하면 봇이 5회 재시도 후 EGW00103으로 죽는다.**

| 항목 | 정상 형식 | 자주 보는 오류 |
|---|---|---|
| `KIS_APP_KEY` | **36자**, 영문/숫자만 (보통 `PS...` 대문자 시작) | 35자(누락 1자), underscore 포함, 소문자 prefix(`bg_...`) → 다른 서비스 키 잘못 복사 |
| `KIS_APP_SECRET` | 64자, base64-like (영문/숫자/`+/=`) | 공백·줄바꿈 포함 |
| `KIS_ACCOUNT_NO` | `XXXXXXXX-01` (8자리-2자리, 11자) | 하이픈 누락, 후행 주석 같이 복사 (`12345678-01 # 실전계좌`) |

검증 쉘 (값을 노출하지 않고 길이/패턴만 체크):
```bash
awk -F= '/^KIS_APP_KEY=/ {v=$2; print "len="length(v), "alphanum_only="(v ~ /^[A-Za-z0-9]+$/?"YES":"NO")}' .env
awk -F= '/^KIS_ACCOUNT_NO=/ {v=$2; print "len="length(v), "format_match="(v ~ /^[0-9]{8}-[0-9]{2}$/?"YES":"NO")}' .env
```
- `KIS_APP_KEY`: `len=36 alphanum_only=YES`
- `KIS_ACCOUNT_NO`: `len=11 format_match=YES`

이 두 라인 통과 못 하면 `.env` 다시 편집한다.

### 2.3 텔레그램 봇

Paper 서버와 동일한 봇을 재사용하면 알림이 섞이므로, **Live 전용 별도 봇**을 만드는 것을 권장한다.

1. 텔레그램에서 `@BotFather` 검색 → 대화 시작
2. `/newbot` 명령 → 봇 이름/사용자명 설정
3. 발급된 **HTTP API Token** 저장 → `TELEGRAM_BOT_TOKEN`
4. 새 봇과 대화 시작 → `@userinfobot`에게 Chat ID 요청 → `TELEGRAM_CHAT_ID`

### 2.4 GitHub 저장소 접근

- Public 저장소인 경우 HTTPS clone으로 충분
- Private 저장소인 경우 SSH key를 EC2에 등록해야 함

### 2.5 로컬 SSH 키

EC2 접속용. 본 가이드에서는 AWS에서 `snowa-live-key.pem`을 새로 발급한다.

---

## 3. AWS 인프라 구축

### 3.1 키 페어 생성

1. AWS 콘솔 → **EC2** → 좌측 메뉴 **네트워크 및 보안** → **키 페어**
2. 우측 상단 **키 페어 생성** 클릭
3. 설정:
   - **이름**: `snowa-live-key`
   - **키 페어 유형**: `RSA`
   - **프라이빗 키 파일 형식**: `.pem`
4. **키 페어 생성** 클릭 → `snowa-live-key.pem`이 자동 다운로드됨
5. 로컬 터미널에서:

```bash
mv ~/Downloads/snowa-live-key.pem ~/.ssh/snowa-live-key.pem
chmod 400 ~/.ssh/snowa-live-key.pem
```

### 3.2 보안 그룹 생성

1. AWS 콘솔 → **EC2** → **보안 그룹** → **보안 그룹 생성**
2. 기본 정보:
   - **보안 그룹 이름**: `snowa-live-sg`
   - **설명**: `Snowa Live Trading Bot`
   - **VPC**: 기본 VPC
3. **인바운드 규칙** — "규칙 추가"로 아래 2개 추가:

| 유형 | 프로토콜 | 포트 범위 | 소스 | 설명 |
|------|---------|----------|------|------|
| SSH | TCP | 22 | **내 IP** (드롭다운) | SSH 접속 |
| 사용자 지정 TCP | TCP | 8000 | **내 IP** (드롭다운) | 대시보드 접속 |

> ⚠️ **절대로** 소스를 `0.0.0.0/0`(Anywhere)으로 설정하지 않는다. 실전 서버는 침해 시 실계좌 주문이 나갈 수 있다.

4. **아웃바운드 규칙**: 기본값 유지 (모든 트래픽 허용 — KIS API/yfinance/Telegram 호출용)
5. **보안 그룹 생성** 클릭

### 3.3 EC2 인스턴스 생성

1. AWS 콘솔 → **EC2** → **인스턴스 시작**
2. 설정:

| 항목 | 값 |
|------|-----|
| **이름** | `snowa-live-bot` |
| **AMI** | Ubuntu Server 24.04 LTS (HVM), SSD Volume Type |
| **아키텍처** | 64비트 (x86) |
| **인스턴스 유형** | **t3.small** (2 vCPU, 2GB RAM) |
| **키 페어** | `snowa-live-key` |
| **네트워크 설정** | 편집 → **기존 보안 그룹 선택** → `snowa-live-sg` |
| **스토리지** | 30 GiB, gp3 |

3. **고급 세부 정보** 펼치기:
   - **종료 방지 (Termination Protection)**: ✅ **활성화**
   - **중지 방지 (Stop Protection)**: ✅ **활성화**
   - **구매 옵션 → 스팟 인스턴스 요청**: ❌ **체크 해제** (반드시 온디맨드)

4. **인스턴스 시작** 클릭 → 1분 내 `running` 상태 확인

### 3.4 Elastic IP 할당

재부팅 시에도 고정 IP를 유지하기 위해 필수다.

1. AWS 콘솔 → **EC2** → **탄력적 IP** → **탄력적 IP 주소 할당**
2. 기본값 → **할당**
3. 할당된 IP 클릭 → **탄력적 IP 주소 연결**
4. 리소스 유형: `인스턴스` → 인스턴스: `snowa-live-bot` → **연결**
5. 이 IP를 **`<LIVE_ELASTIC_IP>`**로 저장 (이후 명령어에서 사용)

### 3.5 CloudWatch Auto Recovery

EC2 하드웨어 장애 시 AWS가 자동으로 새 하드웨어에서 인스턴스를 재시작하도록 설정.

1. AWS 콘솔 → **CloudWatch** → **경보** → **모든 경보** → **경보 생성**
2. **지표 선택**:
   - `EC2` → `인스턴스별 지표`
   - 검색창에 `snowa-live-bot`의 인스턴스 ID 입력
   - `StatusCheckFailed_System` 체크 → **지표 선택**
3. 조건:
   - **통계**: `최소`
   - **기간**: `1분`
   - **임계값**: `보다 크거나 같음`, `1`
4. **다음** → 작업 설정:
   - **EC2 작업 추가** → `이 인스턴스 복구`
5. **다음** → 경보 이름: `snowa-live-auto-recovery` → **경보 생성**

---

## 4. EC2 OS 초기 설정

### 4.1 SSH 접속

로컬 터미널에서:

```bash
ssh -i ~/.ssh/snowa-live-key.pem ubuntu@<LIVE_ELASTIC_IP>
```

처음 접속 시 `yes` 입력하여 호스트 키 수락.

### 4.2 OS 업데이트 + 기본 패키지

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  git curl wget unzip build-essential \
  sqlite3 libsqlite3-0 \
  python3-venv python3-dev \
  ca-certificates gnupg
```

### 4.3 시간대 설정 (필수 — KST)

```bash
sudo timedatectl set-timezone Asia/Seoul
timedatectl | head -5
```

출력에서 `Time zone: Asia/Seoul (KST, +0900)` 확인.

### 4.4 Swap 파일 생성 (2GB)

t3.small 메모리 부족 방지 (프론트엔드 빌드 시 필요). Paper 서버와 동일 설정.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

swapon --show
free -h
```

`swapon --show` 에 `/swapfile 2G` 가 보이면 성공.

---

## 5. 런타임 설치 (Python + Node.js)

### 5.1 Python 3.12 확인

Ubuntu 24.04는 기본으로 Python 3.12가 설치되어 있다.

```bash
python3 --version
```

출력이 `Python 3.12.x` 이어야 한다. 그렇지 않으면 중단하고 원인 파악.

### 5.2 Node.js 20 (LTS) 설치

Paper 서버는 Node 18을 쓰지만, Live 서버는 최신 LTS인 **Node 20**을 설치한다 (프론트엔드 빌드 호환성 향상, 기존 번들과 동일 결과).

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

node --version   # v20.x.x
npm --version    # 10.x.x
```

---

## 6. 프로젝트 배포 & 빌드

### 6.1 저장소 클론

```bash
mkdir -p /home/ubuntu/apps
cd /home/ubuntu/apps
git clone https://github.com/blood8879/snowa-tradingbot.git snowa_tradingbot
cd snowa_tradingbot
```

> Private 저장소라면 GitHub Personal Access Token 또는 SSH key를 사전에 세팅해야 한다.

### 6.2 Python 가상환경 + 의존성

```bash
cd /home/ubuntu/apps/snowa_tradingbot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
deactivate
```

설치 시간: 약 2~3분. pandas/numpy/yfinance가 가장 큰 패키지.

### 6.3 프론트엔드 빌드

```bash
cd /home/ubuntu/apps/snowa_tradingbot/web/frontend
npm ci
npm run build
```

빌드 완료 시 `dist/index.html`과 `dist/assets/` 확인:

```bash
ls -la dist/
```

빌드가 메모리 부족(OOM)으로 실패하면 swap이 활성화됐는지 재확인(`free -h`). 4.4 단계에서 이미 2GB swap이 활성화되어 있어야 한다.

### 6.4 필수 디렉토리 생성

```bash
cd /home/ubuntu/apps/snowa_tradingbot
mkdir -p data logs
```

---

## 7. Live 모드 .env 설정 (핵심)

**이 단계가 가장 중요하다.** `.env` 하나로 paper/live가 결정된다.

### 7.1 .env 파일 생성

```bash
cd /home/ubuntu/apps/snowa_tradingbot
cp .env.example .env
chmod 600 .env
nano .env
```

### 7.2 .env 내용 (Live 모드)

아래를 붙여넣고 `<PLACEHOLDER>` 부분을 실제 값으로 치환:

```env
# ===== Trading Mode =====
TRADING_MODE=live

# ===== Korea Investment Securities API =====
# 실전 (Live) — 이 서버에서 사용
KIS_APP_KEY=<LIVE_APP_KEY>
KIS_APP_SECRET=<LIVE_APP_SECRET>
KIS_ACCOUNT_NO=<LIVE_ACCOUNT_NO_FORMAT_12345678-01>

# 모의 (Paper) — live 서버에서는 빈값 가능하지만 키 자체는 유지 (코드가 참조)
KIS_PAPER_APP_KEY=
KIS_PAPER_APP_SECRET=
KIS_PAPER_ACCOUNT_NO=

# ===== Telegram (Live 전용 봇 권장) =====
TELEGRAM_BOT_TOKEN=<LIVE_BOT_TOKEN>
TELEGRAM_CHAT_ID=<YOUR_CHAT_ID>

# ===== Database =====
DB_PATH=data/snowa.db

# ===== Logging =====
LOG_LEVEL=INFO
LOG_FILE=logs/snowa_bot.log
```

### 7.3 .env 검증

```bash
cd /home/ubuntu/apps/snowa_tradingbot
ls -la .env
grep -v '^#' .env | grep -v '^$'
```

- 파일 권한이 `-rw-------` (600)인지 확인
- `TRADING_MODE=live` 확인
- `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`에 실값이 들어있는지 확인

> ⚠️ **실전 계좌번호 오타 주의.** `12345678-01` 형식. 하이픈과 상품코드(`-01`, `-02` 등)를 정확히 기입. 잘못 입력하면 주문 거부 또는 (드물게) 다른 계좌에 영향.

#### 7.3.1 후행 주석 트랩 (반드시 처리)

`.env.example` 템플릿은 라인 끝에 `# paper or live` 같은 도움말 주석을 가진다. 일부 dotenv 파서는 이 주석까지 값으로 읽어 **`TRADING_MODE`가 `live`가 아니라 `live                       # paper or live`(39자)로 인식**되어 KIS API에 잘못된 모드 문자열이 전달된다.

7.2에서 값을 채운 직후 아래 한 줄 sed로 *값 자체에 공백·`#`이 없는 키만* 안전하게 후행 주석을 제거한다 (KIS_APP_SECRET 같은 base64는 공백/`#`이 없으므로 매칭 안전):

```bash
sed -i.backup -E 's/^([A-Z_]+=[^[:space:]#]*)[[:space:]]+#.*$/\1/' .env
```

검증:
```bash
awk -F= '/^[A-Z_]+=/ {gsub(/[[:space:]]+$/, "", $2); print $1" len="length($2)}' .env
```
- `TRADING_MODE`: 4 (live)
- `KIS_APP_KEY`: 36
- `KIS_APP_SECRET`: 64
- `KIS_ACCOUNT_NO`: 11
- `KIS_PAPER_*`: 0 (live 서버에서는 비어있어야 함)
- `TELEGRAM_BOT_TOKEN`: 46
- `TELEGRAM_CHAT_ID`: 9~10

길이가 위와 다르면 `.env.backup`으로 롤백 후 수동 편집.

또한 **`KIS_PAPER_*` 키가 채워져있는데 `TRADING_MODE=live`이면 충돌 위험**. live 서버에서는 명시적으로 빈값으로 둔다:
```bash
sed -i -E 's/^KIS_PAPER_APP_KEY=.*/KIS_PAPER_APP_KEY=/' .env
sed -i -E 's/^KIS_PAPER_APP_SECRET=.*/KIS_PAPER_APP_SECRET=/' .env
sed -i -E 's/^KIS_PAPER_ACCOUNT_NO=.*/KIS_PAPER_ACCOUNT_NO=/' .env
```

### 7.4 KIS API 연결 테스트 (선택)

systemd 등록 전, 실전 API가 제대로 인증되는지 빠르게 확인:

```bash
cd /home/ubuntu/apps/snowa_tradingbot
source .venv/bin/activate
python -c "
import asyncio
from config.settings import get_settings
from broker.kis_rest import KISRestClient
from broker.kis_auth import KISAuth

async def test():
    settings = get_settings()
    print(f'TRADING_MODE: {settings.trading_mode}')
    print(f'APP_KEY prefix: {settings.kis_app_key[:10]}...')
    print(f'ACCOUNT_NO: {settings.kis_account_no}')
    auth = KISAuth(settings)
    await auth.initialize()
    print('Auth OK, token acquired.')

asyncio.run(test())
"
deactivate
```

`Auth OK` 가 나오면 성공. 에러(`EGW00123` 등)가 나면 KIS 콘솔에서 API 승인 상태 재확인.

---

## 8. systemd 서비스 등록

### 8.1 snowa-bot.service 작성

```bash
sudo tee /etc/systemd/system/snowa-bot.service > /dev/null <<'EOF'
[Unit]
StartLimitIntervalSec=600
StartLimitBurst=3
Description=Snowa Trading Bot (LIVE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/apps/snowa_tradingbot
Environment="PATH=/home/ubuntu/apps/snowa_tradingbot/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/ubuntu/apps/snowa_tradingbot/.env
ExecStart=/home/ubuntu/apps/snowa_tradingbot/.venv/bin/python -m scripts.run_bot
Restart=always
RestartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snowa-bot

[Install]
WantedBy=multi-user.target
EOF
```

### 8.2 snowa-dashboard.service 작성

```bash
sudo tee /etc/systemd/system/snowa-dashboard.service > /dev/null <<'EOF'
[Unit]
Description=Snowa Trading Dashboard (FastAPI, LIVE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/apps/snowa_tradingbot
Environment="PATH=/home/ubuntu/apps/snowa_tradingbot/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/ubuntu/apps/snowa_tradingbot/.env
ExecStart=/home/ubuntu/apps/snowa_tradingbot/.venv/bin/uvicorn web.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snowa-dashboard

[Install]
WantedBy=multi-user.target
EOF
```

> 이 파일 내용은 paper 서버의 실제 서비스 파일과 **동일**하다. `Description`만 `(LIVE)`로 표시.

### 8.3 서비스 enable + start

```bash
sudo systemctl daemon-reload
sudo systemctl enable snowa-bot.service snowa-dashboard.service
sudo systemctl start snowa-dashboard.service
sleep 3
sudo systemctl start snowa-bot.service
```

> 대시보드를 먼저 시작하고 3초 후 봇을 시작하는 이유: 봇은 DB 스키마 마이그레이션을 수행하므로 대시보드가 단순 읽기로 충돌하지 않도록.

### 8.4 OS 방화벽 (ufw) — Vultr 등 일부 이미지 필수

AWS Ubuntu 24.04 AMI는 ufw가 비활성 상태로 출고되어 보안 그룹만으로 충분하지만, **Vultr/일부 클라우드 Ubuntu 이미지는 ufw가 default deny로 활성화**되어 있어 EC2 보안 그룹을 열어도 OS 안에서 8000을 막는다. 인스턴스에서 직접 확인:

```bash
sudo ufw status verbose | head -10
```

`Status: active`이고 8000이 ALLOW 목록에 없으면 추가:

```bash
sudo ufw allow 8000/tcp comment 'Snowa dashboard'
sudo ufw status verbose | head -10
```

> AWS 환경에서도 사용자가 임의로 ufw를 활성화한 경우 동일 조치. 보안 그룹 + ufw 이중 방어를 유지하려면 ufw에서도 SSH 22, Dashboard 8000만 허용한다.

---

## 9. 실행 & 검증

### 9.1 서비스 상태 확인

```bash
sudo systemctl status snowa-dashboard.service --no-pager | head -15
sudo systemctl status snowa-bot.service --no-pager | head -15
```

두 서비스 모두 `active (running)` 이어야 한다.

### 9.2 실시간 로그 확인 (5분간 관찰)

```bash
sudo journalctl -u snowa-bot.service -f
```

정상 케이스 로그 예시:
- `database_initialized path=... schema_version=1`
- `migration_applied migration=...` (여러 줄)
- `kis_auth_token_acquired`
- `scheduler_started`
- 오류 없이 스케줄러가 대기 상태로 들어감

`Ctrl+C`로 로그 모니터링 종료.

### 9.3 대시보드 접속

로컬 브라우저에서:

```
http://<LIVE_ELASTIC_IP>:8000
```

- 페이지가 로드되는지 확인
- 우측 상단 **Trading Mode** 표시가 `LIVE`인지 확인
- 포트폴리오 대시보드가 비어있는 초기 상태로 표시됨 (정상 — 신규 DB)

### 9.4 DB 스키마 검증

```bash
cd /home/ubuntu/apps/snowa_tradingbot
sqlite3 data/snowa.db ".tables"
```

출력에 `positions`, `orders`, `watchlist`, `daily_prices`, `bot_state` 등 14개 내외 테이블이 보여야 한다.

```bash
sqlite3 data/snowa.db "PRAGMA table_info(positions);" | grep -E "force_exit|market"
```

`force_exit_flag`, `force_exit_reason`, `force_exit_set_at`, `market` 컬럼이 포함되어야 한다 (마이그레이션 적용 증명).

---

## 10. 운영 자동화 (백업 + 헬스체크)

### 10.1 DB 백업 (S3)

**S3 버킷 생성:**

1. AWS 콘솔 → **S3** → **버킷 만들기**
2. 버킷 이름: `snowa-live-backups-<USER_ID>` (전역 고유)
3. 리전: ap-northeast-2
4. 나머지 기본값 → **버킷 만들기**

**IAM 역할로 EC2 권한 부여:**

1. AWS 콘솔 → **IAM** → **역할** → **역할 생성**
2. 신뢰할 엔터티: `AWS 서비스` → 사용 사례: `EC2`
3. 권한 정책: `AmazonS3FullAccess` (간단용; 프로덕션은 버킷 한정 정책 권장)
4. 역할 이름: `snowa-live-ec2-s3-role` → **역할 생성**
5. EC2 콘솔 → `snowa-live-bot` 선택 → **작업 → 보안 → IAM 역할 수정** → `snowa-live-ec2-s3-role`

**백업 스크립트:**

```bash
tee /home/ubuntu/backup_db.sh > /dev/null <<'EOF'
#!/bin/bash
DB_PATH="/home/ubuntu/apps/snowa_tradingbot/data/snowa.db"
S3_BUCKET="snowa-live-backups-<USER_ID>"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="snowa_live_${TIMESTAMP}.db"

sqlite3 "$DB_PATH" ".backup /tmp/${BACKUP_NAME}"
aws s3 cp "/tmp/${BACKUP_NAME}" "s3://${S3_BUCKET}/db-backups/${BACKUP_NAME}"
rm -f "/tmp/${BACKUP_NAME}"
echo "[$(date)] Backup: ${BACKUP_NAME}"
EOF
chmod +x /home/ubuntu/backup_db.sh
```

`<USER_ID>` 치환 후 `aws cli` 설치:

```bash
sudo snap install aws-cli --classic
# 또는: sudo apt install -y awscli
```

크론 등록 (매일 KST 07:00):

```bash
crontab -e
```

아래 줄 추가:

```
0 7 * * * /home/ubuntu/backup_db.sh >> /home/ubuntu/apps/snowa_tradingbot/logs/backup.log 2>&1
```

### 10.2 헬스체크

```bash
tee /home/ubuntu/healthcheck.sh > /dev/null <<'EOF'
#!/bin/bash
DASHBOARD_URL="http://localhost:8000/api/health"
TELEGRAM_BOT_TOKEN="<LIVE_BOT_TOKEN>"
TELEGRAM_CHAT_ID="<YOUR_CHAT_ID>"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASHBOARD_URL")

if [ "$HTTP_CODE" != "200" ]; then
    MESSAGE="[LIVE ALERT] Dashboard HTTP ${HTTP_CODE}. Restarting..."
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" -d text="${MESSAGE}"
    sudo systemctl restart snowa-dashboard.service
fi
EOF
chmod +x /home/ubuntu/healthcheck.sh
```

`<LIVE_BOT_TOKEN>` / `<YOUR_CHAT_ID>` 치환 후 크론 등록:

```bash
crontab -e
```

```
*/5 * * * * /home/ubuntu/healthcheck.sh >> /home/ubuntu/apps/snowa_tradingbot/logs/healthcheck.log 2>&1
```

---

## 11. Paper ↔ Live 서버 간 데이터 격리

두 서버는 **절대** DB/계좌를 공유해서는 안 된다.

### 11.1 DB 분리

- Paper 서버 DB: `43.202.181.170:/home/ubuntu/apps/snowa_tradingbot/data/snowa.db`
- Live 서버 DB: `<LIVE_ELASTIC_IP>:/home/ubuntu/apps/snowa_tradingbot/data/snowa.db`
- **서로 SCP 또는 동기화하지 않는다**
- Watchlist/breakout history는 각자 쌓이며, 시간이 지나면 비슷한 내용이 되지만 독립적으로 운영

### 11.2 데이터 시드 — 신규 DB는 스크리닝이 0개 통과한다 (필수 단계)

**이 섹션은 옵션이 아니다.** 빈 DB로 봇을 띄운 뒤 첫 스크리닝(KST 20:00)이 돌면 universe ~6,700 종목을 검사하지만 **CANSLIM/Minervini 통과는 0개**가 나온다. 원인:

- yfinance가 신규 fetch 시 historical EPS/매출을 모든 종목에 대해 충분히 내려주지 않음 (예: `earnings_targets=65, stale_targets=500`)
- 결과: `quarterly_eps_growth`, `annual_eps_cagr` 계산 불가 → C·A 필터에서 자동 탈락

**해결**: Paper 서버의 fundamentals + daily_prices + watchlist를 통째 시드. trading state(positions/orders/units/daily_log/bot_state) 테이블만 비우면 Live 계좌와 안전하게 분리된다.

#### 11.2.1 Paper DB 통째 복사 (권장)

```bash
# 1) Paper에서 일관 스냅샷 (.backup은 sqlite의 atomic copy)
ssh -i ~/Downloads/canslim.pem ubuntu@43.202.181.170 \
    "sqlite3 /home/ubuntu/apps/snowa_tradingbot/data/snowa.db '.backup /tmp/snowa_paper_snapshot.db'"

# 2) AWS → 로컬 → Live (약 350MB, 1~3분)
scp -i ~/Downloads/canslim.pem \
    ubuntu@43.202.181.170:/tmp/snowa_paper_snapshot.db /tmp/snowa_paper_snapshot.db
scp -i ~/.ssh/snowa-live-key.pem \
    /tmp/snowa_paper_snapshot.db ubuntu@<LIVE_ELASTIC_IP>:/tmp/

# 3) Live 서버에서 덮어쓰기 + trading state 초기화
ssh -i ~/.ssh/snowa-live-key.pem ubuntu@<LIVE_ELASTIC_IP>
sudo systemctl stop snowa-bot.service snowa-dashboard.service
cd /home/ubuntu/apps/snowa_tradingbot
cp data/snowa.db data/snowa.db.backup-$(date +%Y%m%d-%H%M%S)
cp /tmp/snowa_paper_snapshot.db data/snowa.db
chown ubuntu:ubuntu data/snowa.db

sqlite3 data/snowa.db <<'SQL'
DELETE FROM positions;
DELETE FROM orders;
DELETE FROM units;
DELETE FROM daily_log;
DELETE FROM bot_logs;
DELETE FROM breakout_history;
DELETE FROM watchlist_history;
DELETE FROM bot_state;
SQL

sudo systemctl start snowa-dashboard.service
sleep 3
sudo systemctl start snowa-bot.service

# 4) 정리
rm /tmp/snowa_paper_snapshot.db
```

> ⚠️ **trading state 정리는 절대 생략 금지**. Paper 계좌의 positions/orders가 Live DB에 남으면 Live 봇이 존재하지 않는 종목을 보유 중이라고 착각해 첫 사이클부터 사고가 난다.

#### 11.2.2 KR 종목명 캐시 (`universe_kr_cache.csv`)

**대시보드 KR 워치리스트에서 종목명이 안 뜨면 이 단계 누락이 원인이다.** `data/snowa.db`에는 `name`이 비어있고, `data/universe_kr_cache.csv`(`ticker,name,exchange,market_cap,is_etf`)를 매핑 소스로 쓴다. DB와 별개 파일이라 SCP에 따라오지 않는다.

```bash
# Paper에서 가져와 Live로 전달
scp -i ~/Downloads/canslim.pem \
    ubuntu@43.202.181.170:/home/ubuntu/apps/snowa_tradingbot/data/universe_kr_cache.csv \
    /tmp/universe_kr_cache.csv
scp -i ~/.ssh/snowa-live-key.pem \
    /tmp/universe_kr_cache.csv \
    ubuntu@<LIVE_ELASTIC_IP>:/home/ubuntu/apps/snowa_tradingbot/data/universe_kr_cache.csv
```

> KR 시장을 운영하지 않을 계획이라도 복사해두는 편이 안전하다 — 추후 KR 활성화 시 종목명이 즉시 표시된다.

#### 11.2.3 DB 인덱스 추가 (성능 필수)

스키마에 누락된 복합 인덱스 두 개를 추가한다. **이걸 안 하면 `/api/watchlist`가 콜드 캐시에서 25초 이상 걸리고 frontend timeout으로 "데이터를 불러오는 중 오류가 발생했습니다" 에러가 뜬다.** (인덱스 추가는 idempotent — 이미 있으면 무시됨.)

```bash
# Live 서버에서 — 봇 정지 후 수행 권장
sudo systemctl stop snowa-bot.service
sqlite3 /home/ubuntu/apps/snowa_tradingbot/data/snowa.db <<'SQL'
CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker_date ON daily_prices(ticker, date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_report ON fundamentals(ticker, report_date);
ANALYZE;
SQL
sudo systemctl start snowa-bot.service
```

> `ANALYZE`까지 같이 돌리는 이유: query optimizer 통계 갱신. 신규 import된 DB는 통계가 없어 plan을 잘못 짤 수 있다.

#### 11.2.4 검증

```bash
ssh -i ~/.ssh/snowa-live-key.pem ubuntu@<LIVE_ELASTIC_IP> \
    "sqlite3 /home/ubuntu/apps/snowa_tradingbot/data/snowa.db \"
SELECT 'fundamentals', COUNT(*) FROM fundamentals
UNION ALL SELECT 'daily_prices', COUNT(*) FROM daily_prices
UNION ALL SELECT 'watchlist (US)', COUNT(*) FROM watchlist WHERE market='US' AND status='ACTIVE'
UNION ALL SELECT 'positions', COUNT(*) FROM positions
UNION ALL SELECT 'orders', COUNT(*) FROM orders;\""
```

기대 출력 (대략):
- `fundamentals`: 50,000+
- `daily_prices`: 3,000,000+
- `watchlist (US)`: 30~80 (시장 상황별)
- `positions`: **0**
- `orders`: **0**

대시보드에서 `/api/watchlist?market=US`가 1~3초 안에 응답하면 인덱스가 잘 적용된 것.

> Positions/orders/units는 절대 복사하지 않는다. Paper와 Live는 계좌가 다르므로 포지션 정보가 섞이면 현실과 DB가 불일치해 바로 사고가 난다.

### 11.3 Telegram 봇 분리

- Paper 봇: 기존 그대로
- Live 봇: 2.3에서 신규 발급. 메시지 prefix에 `[LIVE]` 포함되면 식별 용이

### 11.4 대시보드 구분

브라우저 북마크 분리:
- Paper: `http://43.202.181.170:8000`
- Live: `http://<LIVE_ELASTIC_IP>:8000`

대시보드 상단에 `LIVE` 배지가 표시되는지 매번 확인하는 습관 들이기.

---

## 12. Live 전환 전 최종 체크리스트

실제 자금으로 주문이 나가기 전에 **반드시** 아래 항목을 모두 확인한다.

### 12.1 인프라
- [ ] EC2 종료 보호 + 중지 보호 활성화
- [ ] Elastic IP 연결됨
- [ ] CloudWatch Auto Recovery 경보 생성됨
- [ ] 보안 그룹이 내 IP로만 제한됨
- [ ] Swap 2GB 활성화됨
- [ ] 시간대 Asia/Seoul

### 12.2 소프트웨어
- [ ] Python 3.12, Node 20 설치됨
- [ ] 프론트엔드 `dist/` 생성됨
- [ ] systemd 서비스 `enable` + `active (running)`
- [ ] DB 스키마 마이그레이션 완료 (positions 테이블에 force_exit_* 컬럼 존재)

### 12.3 보안
- [ ] `.env` 권한 600
- [ ] `.env`에 `TRADING_MODE=live`
- [ ] KIS APP_KEY/SECRET이 **실전 키**로 채워짐 (paper 키와 혼동 안됨)
- [ ] `KIS_ACCOUNT_NO`가 실전 계좌번호 (형식 `XXXXXXXX-01`)
- [ ] Telegram 봇이 Live 전용
- [ ] KIS API 인증 테스트(7.4) 통과

### 12.4 운영
- [ ] DB 백업 cron 등록됨
- [ ] 헬스체크 cron 등록됨
- [ ] 대시보드 브라우저 접속 확인
- [ ] 대시보드에 **LIVE** 배지 표시됨
- [ ] `journalctl -u snowa-bot -f` 5분간 에러 없음

### 12.5 계좌/자금
- [ ] 실전 계좌에 **최소 시드머니만** 입금 (처음엔 전체 자산 넣지 말 것)
- [ ] KIS HTS/MTS에서 직접 확인한 잔고와 대시보드 잔고가 일치
- [ ] 주문 가능 금액이 예상대로 표시됨

### 12.6 전략 파라미터
- [ ] `config/constants.py`의 RISK_PER_TRADE_PCT 확인 (기본 2%, Live는 더 보수적으로 시작 권장)
- [ ] `MAX_POSITION_VALUE_PCT` 확인
- [ ] 첫 운영 주는 최대 **1~2개 포지션**만 허용하도록 의식적 제한

---

## 13. 트러블슈팅

### 13.1 systemd 서비스가 `activating` 또는 `failed` 상태

```bash
sudo journalctl -u snowa-bot.service -n 50 --no-pager
```

자주 발생:
- `ModuleNotFoundError`: `pip install -e .` 재실행
- `KIS auth failed`: `.env`의 APP_KEY/SECRET 재확인, KIS 콘솔에서 API 승인 여부 확인
- `database is locked`: 봇과 대시보드가 동시에 쓰기를 시도한 경우. WAL 모드가 활성화됐는지 확인 (`PRAGMA journal_mode=WAL;`)

### 13.2 대시보드 접속 불가

1. 보안 그룹 인바운드 규칙에 내 IP로 8000 포트 추가되어 있는가
2. `sudo ss -tlnp | grep 8000` 으로 uvicorn이 실제 리스닝 중인지 확인
3. `curl -v http://localhost:8000/api/health` EC2 내부에서 응답하는가

### 13.3 KIS API 인증 오류

Live 모드 첫 접속 시 자주 만남:
- **EGW00123**: APP_KEY/SECRET 불일치 또는 미승인. KIS 포털에서 키 재발급.
- **EGW00201**: 초당 거래건수 초과. 재시도 간격 확보.
- **"ALREADY IN USE appkey"**: 이전 WebSocket 세션이 살아있음. `systemctl stop snowa-bot` 후 60초 대기, 다시 `start`.

### 13.4 프론트엔드 빌드 OOM

2GB swap이 이미 활성화된 상태에서도 실패하면:

```bash
sudo fallocate -l 4G /swapfile2
sudo chmod 600 /swapfile2
sudo mkswap /swapfile2
sudo swapon /swapfile2
cd /home/ubuntu/apps/snowa_tradingbot/web/frontend
npm run build
sudo swapoff /swapfile2
sudo rm /swapfile2
```

빌드 후 swap은 제거하여 디스크 공간 확보.

### 13.5 실계좌 첫 주문 테스트 실패

Live에서 첫 주문은 반드시 **수동으로 작게** 테스트:
1. 대시보드 → Watchlist → 1주만 사는 시나리오 찾기
2. 장중에 실제 breakout 발생 시 봇이 주문 내는지 관찰
3. 주문 후 KIS HTS에서 직접 체결 확인
4. DB의 `positions`, `orders`, `units` 기록이 HTS와 일치하는지 확인

첫 주문에서 한 줄이라도 불일치하면 즉시 `systemctl stop snowa-bot` 하고 원인 파악.

### 13.6 대시보드: "데이터를 불러오는 중 오류가 발생했습니다"

거의 모두 같은 두 원인.

**원인 A — 옛 KIS 키 캐시 잔존**: 봇은 새 키로 재시작했지만 dashboard 서비스는 그대로 두면 메모리에 옛 토큰이 남아 EGW00103 반복.
```bash
sudo systemctl restart snowa-dashboard.service
```

**원인 B — 인덱스/캐시 콜드로 `/api/watchlist`가 frontend 10s timeout 초과**: 11.2.3 인덱스 추가가 누락된 경우. F12 Network에서 `/api/watchlist?market=US`가 빨갛게 뜨면 이 케이스. 11.2.3 단계로 인덱스 추가하고 dashboard 재시작.

검증:
```bash
ssh -i ~/.ssh/snowa-live-key.pem ubuntu@<LIVE_ELASTIC_IP> \
    "time curl -s -o /dev/null -w 'HTTP %{http_code} time=%{time_total}s\n' \
    --max-time 30 'http://localhost:8000/api/watchlist?market=US'"
```
1~3초 안에 HTTP 200이 나오면 정상.

### 13.7 KR 워치리스트에서 종목명이 비어있음

`data/universe_kr_cache.csv` 누락. 11.2.2 단계로 SCP 복사. 봇/대시보드 재시작 불필요 (코드가 매 요청마다 CSV 읽음).

### 13.8 nano: "Error opening terminal: xterm-ghostty"

Ghostty 등 일부 터미널의 `TERM` 값이 서버에 등록되어 있지 않아 발생. 임시:
```bash
TERM=xterm-256color nano .env
```
영구 해결 (서버 측):
```bash
echo 'export TERM=xterm-256color' >> ~/.bashrc && source ~/.bashrc
```

### 13.9 `kis_token_rate_limited` (재시작 직후만)

봇과 대시보드가 거의 동시에 KIS 토큰을 요청하면 두 번째 호출이 65초 retry로 들어간다. 정상 자동 복구 — 60~70초 기다리면 됨. 매 요청마다 발생한다면 다른 인스턴스가 같은 appkey로 동시 운영 중인지 확인 (Paper와 Live는 별도 키여야 함).

### 13.10 `/api/account/reset` 가 403을 반환

**의도된 동작**입니다. Live 모드에서는 frontend의 "계좌 초기화" 버튼이 숨겨지고, 백엔드가 직접 호출도 거부합니다 (`web/api/routes/account_reset.py`의 live mode guard). Paper 서버에서만 동작.

---

## 14. 알려진 이슈 / 이번 배포에서 수정된 항목

신규 운영 서버를 띄우는 사람이 모르고 지나치면 시간 낭비를 야기하는 함정들. 본 가이드의 단계는 이미 이 이슈들을 회피하도록 작성되어 있지만, 코드 흐름을 이해하려면 알아두면 좋다.

### 14.1 main 브랜치에서 이미 수정됨 (체크아웃 후 자동 적용)

| 이슈 | 커밋 | 효과 |
|---|---|---|
| `broker/account.py`: paper-mode US cash가 `ord_psbl_frcr_amt=0`이라 equity 누락 | `fix(broker): fallback to frcr_ord_psbl_amt1` | 대시보드 손익분석에 가짜 음수 PnL 사라짐 |
| `core/database.py`: `watchlist.name` 컬럼 마이그레이션 누락 → 신규 DB에서 `/api/trades`, `/api/alerts` 500 | `fix(db): add migration for watchlist.name column` | 신규 DB에서도 자동으로 `ALTER TABLE` 적용됨 |
| `web/api/routes/watchlist.py`: 96 sequential SQL + daily_prices 3.3M ROW_NUMBER 메인 join → 25초 | `perf(watchlist): batch fetch + drop daily_prices join` | ~0.2초 |
| `web/frontend/src/lib/fetcher.ts`: 10s timeout이 무거운 endpoint에 짧음 | 동일 PR | 30s로 상향 |
| Live 모드 계좌 초기화 차단 (UI 숨김 + API 403) | `fix: hide account reset in live mode` | 실수로 Live DB가 초기화되는 사고 방지 |

### 14.2 이번 배포에서 처리해야 하는 사항

| 항목 | 처리 단계 |
|---|---|
| **DB 인덱스 누락** (`(ticker, date)` on daily_prices, `(ticker, report_date)` on fundamentals) | 11.2.3 |
| **`universe_kr_cache.csv` 미동봉** | 11.2.2 |
| **신규 DB는 fundamental 부족으로 watchlist 0개** | 11.2.1 (Paper DB 통째 시드) |
| **OS-level ufw 활성 이미지** (Vultr 등) | 8.4 |
| **`.env` 후행 주석으로 인한 파싱 오류** | 7.3.1 |

### 14.3 Open Issue (별도 작업 필요)

#### 14.3.1 Telegram 봇이 wire-up되어 있지 않음

`notifications/telegram_bot.py`에 `TelegramNotifier` 클래스(명령어 10개: `/start`, `/stop`, `/mode`, `/status`, `/positions`, `/watchlist`, `/orders`, `/pnl`, `/trades`, `/journal`)와 알림 발송 메서드가 정의되어 있으나, **`bot/trading_bot.py` / `scripts/run_bot.py` 어디에서도 import해 시작하지 않는다**.

증상:
- `.env`에 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`를 채워도 알림이 오지 않음
- 텔레그램 봇에 `/status` 등 명령어를 보내도 응답 없음

활성화하려면 (별도 PR 권장, 1~2시간):
1. `bot/trading_bot.py`의 lifecycle에 `TelegramNotifier` 인스턴스 생성·`start()`/`stop()` 추가
2. 진입·청산·손절·에러 발생 지점에 `notifier.send_message(...)` 호출 삽입
3. (선택) chat_id 검증 미들웨어로 본인만 명령 가능하도록 제한

본 배포 가이드는 이 작업이 완료되지 않은 상태임을 가정하고 작성되었다 — 즉시 운영에는 문제 없으나, 텔레그램 알림에 의존하지 말 것.

#### 14.3.2 `data/universe_kr_cache.csv` 자동 갱신 여부 미확인

11.2.2에서 Paper에서 복사한 CSV는 복사 시점 스냅샷. 이후 신규 KR 상장 종목은 누락된다. 갱신 로직(아마 `data/universe_kr.py`)이 봇 사이클 안에서 자동으로 CSV를 다시 쓰는지는 별도 검증 필요. 첫 KR 운영 시 신규 상장 종목 누락 여부를 모니터링.

---

## 15. 부록: 단일 스크립트 버전

AI 에이전트가 한 번에 실행할 수 있도록 4~10단계를 하나의 bash 스크립트로 통합.

**전제**: 3단계(AWS 인프라)는 웹 콘솔 작업이므로 스크립트화 불가. 이미 EC2가 생성되고 SSH 접속이 성공한 상태에서 실행한다.

```bash
#!/bin/bash
set -euo pipefail

# ── 환경 변수 치환 지점 ──
GITHUB_REPO="https://github.com/blood8879/snowa-tradingbot.git"
PROJECT_DIR="/home/ubuntu/apps/snowa_tradingbot"

# ── 1. OS + 패키지 ──
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget unzip build-essential \
  sqlite3 libsqlite3-0 python3-venv python3-dev \
  ca-certificates gnupg

sudo timedatectl set-timezone Asia/Seoul

# ── 2. Swap ──
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# ── 3. Node.js 20 ──
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
fi

# ── 4. 프로젝트 clone ──
mkdir -p /home/ubuntu/apps
if [ ! -d "$PROJECT_DIR" ]; then
  git clone "$GITHUB_REPO" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

# ── 5. Python venv + deps ──
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
deactivate

# ── 6. Frontend build ──
cd web/frontend
npm ci
npm run build
cd ../..

# ── 7. 디렉토리 ──
mkdir -p data logs

# ── 8. .env 생성 (빈 템플릿 — AI/사용자가 채워야 함) ──
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo ""
  echo "=== .env 파일이 생성되었습니다. 다음을 수동으로 편집하십시오: ==="
  echo "nano $PROJECT_DIR/.env"
  echo ""
  echo "반드시 TRADING_MODE=live 로 설정하고 KIS 실전 키를 입력하십시오."
  exit 1
fi

# ── 9. systemd 서비스 등록 ──
sudo tee /etc/systemd/system/snowa-bot.service > /dev/null <<EOF
[Unit]
StartLimitIntervalSec=600
StartLimitBurst=3
Description=Snowa Trading Bot (LIVE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/.venv/bin/python -m scripts.run_bot
Restart=always
RestartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snowa-bot

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/snowa-dashboard.service > /dev/null <<EOF
[Unit]
Description=Snowa Trading Dashboard (FastAPI, LIVE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/.venv/bin/uvicorn web.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snowa-dashboard

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable snowa-bot.service snowa-dashboard.service

# ── 10. 시작 ──
sudo systemctl start snowa-dashboard.service
sleep 3
sudo systemctl start snowa-bot.service

sleep 5
echo ""
echo "=== 서비스 상태 ==="
sudo systemctl status snowa-dashboard.service --no-pager | head -10
sudo systemctl status snowa-bot.service --no-pager | head -10
```

AI 에이전트는 위 스크립트를 `/home/ubuntu/setup_live.sh`로 저장 후:

```bash
chmod +x /home/ubuntu/setup_live.sh
/home/ubuntu/setup_live.sh
```

실행. `.env`가 없으면 생성 후 `exit 1`로 중단되며, 사용자/AI가 `.env`를 채운 뒤 스크립트를 재실행하면 systemd 등록까지 자동 완료된다.

---

## 완료 후 다음 작업

1. **첫 24시간 모니터링**: `journalctl -u snowa-bot -f` 로 스케줄러 동작, KIS WS 연결, 첫 watchlist 스크리닝 결과 관찰
2. **첫 주 1주일간 소량 시드머니**로만 운영
3. 안정성 확인 후 점진적 자금 증액
4. 매주 DB 백업 S3 업로드 확인
5. Paper 서버와 수익률/거래 비교 (같은 전략인데 결과가 크게 다르면 버그 의심)
