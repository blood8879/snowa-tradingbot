# Snowa Trading Bot - AWS 배포 가이드

모든 AWS 설정은 **AWS Management Console (웹)** 기준으로 설명한다.

## 목차

1. [아키텍처 개요](#아키텍처-개요)
2. [사전 준비](#사전-준비)
3. [방법 1: EC2 단일 인스턴스 (권장)](#방법-1-ec2-단일-인스턴스-권장)
4. [방법 2: Docker + EC2](#방법-2-docker--ec2)
5. [운영 가이드](#운영-가이드)
6. [24/7 무중단 운영 체크리스트](#247-무중단-운영-체크리스트)
7. [보안 체크리스트](#보안-체크리스트)
8. [비용 예상](#비용-예상)
9. [부록: FAQ](#부록-자주-묻는-질문)

---

## 아키텍처 개요

Snowa Trading Bot은 **24시간 365일 무중단**으로 운영되어야 한다. 봇과 대시보드 모두 항상 실행 중이어야 하며, 사용자의 명시적 승인 없이 종료되어서는 안 된다.

두 개의 독립 프로세스로 구성된다.

```
┌─────────────────────────────────────────────────┐
│                  EC2 인스턴스                      │
│                                                   │
│  ┌──────────────────┐  ┌────────────────────────┐ │
│  │  snowa-bot        │  │  snowa-dashboard       │ │
│  │  (trading bot)    │  │  (FastAPI + React SPA) │ │
│  │                   │  │  port 8000             │ │
│  │  APScheduler 기반  │  │                        │ │
│  │  자동 매매 실행     │  │  web/frontend/dist/    │ │
│  │                   │  │  정적 파일 자동 서빙     │ │
│  └──────┬───────────┘  └────────┬───────────────┘ │
│         │                       │                  │
│         └───────────┬───────────┘                  │
│                     │                              │
│              data/snowa.db                         │
│              (SQLite, ~200MB)                      │
└─────────────────────┬──────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   한국투자증권     yfinance      Telegram
   REST API       (종목 스크리닝)  (알림)
   WebSocket
```

**트레이딩 봇** (`python -m scripts.run_bot`)
- APScheduler로 KST 기준 스케줄 실행 (프리마켓 22:00, 정규장 23:30~06:00, 애프터마켓 06:30)
- 한국투자증권(KIS) API를 통한 미국 주식 자동 매매
- yfinance로 종목 스크리닝 데이터 수집
- python-telegram-bot으로 매매 알림 전송

**대시보드** (`uvicorn web.api.main:app --host 0.0.0.0 --port 8000`)
- FastAPI 백엔드 + React(Vite + Tailwind) 프론트엔드
- 프론트엔드 빌드 결과물(`web/frontend/dist/`)을 FastAPI가 자동으로 서빙
- 포트폴리오 현황, 매매 내역, 봇 상태 모니터링

두 프로세스 모두 같은 SQLite DB(`data/snowa.db`)를 공유한다.

---

## 사전 준비

### AWS 계정

1. https://aws.amazon.com 접속
2. 우측 상단 "AWS 계정 생성" 클릭
3. 이메일, 비밀번호, 계정 이름 입력
4. 결제 정보 (신용카드) 등록
5. 본인 인증 완료 후 로그인

이미 계정이 있다면 https://console.aws.amazon.com 에서 로그인한다.

### 리전 설정

로그인 후 **우측 상단의 리전 드롭다운**에서 `아시아 태평양 (서울) ap-northeast-2`를 선택한다. KIS API 서버가 한국에 있으므로 서울 리전이 최적이다.

### KIS API 키 보안 관련 주의사항

한국투자증권 API 키는 절대로 소스코드에 하드코딩하지 않는다. 반드시 `.env` 파일로 관리한다.

- **APP_KEY**, **APP_SECRET**: KIS에서 발급한 앱 키와 시크릿
- 모의투자와 실전투자는 API 엔드포인트가 다르다
  - 모의: `openapivts.koreainvestment.com:29443`
  - 실전: `openapi.koreainvestment.com:9443`
- WebSocket 엔드포인트도 다르다
  - 모의: `ws://ops.koreainvestment.com:31000`
  - 실전: `ws://ops.koreainvestment.com:21000`

---

## 방법 1: EC2 단일 인스턴스 (권장)

개인 트레이딩 봇에 가장 적합한 방법이다. 설정이 단순하고, 비용이 저렴하며, 관리 포인트가 적다.

### 1단계. 키 페어 생성

EC2 서버에 SSH로 접속하기 위한 키를 만든다.

1. AWS 콘솔 > **EC2** > 좌측 메뉴 **네트워크 및 보안** > **키 페어**
2. **키 페어 생성** 클릭
3. 설정:
   - 이름: `snowa-key`
   - 키 페어 유형: `RSA`
   - 프라이빗 키 파일 형식: `.pem` (macOS/Linux) 또는 `.ppk` (Windows PuTTY)
4. **키 페어 생성** 클릭
5. `snowa-key.pem` 파일이 자동으로 다운로드된다
6. 로컬에서 키 파일 권한 설정:

```bash
mv ~/Downloads/snowa-key.pem ~/.ssh/snowa-key.pem
chmod 400 ~/.ssh/snowa-key.pem
```

### 2단계. 보안 그룹 생성

EC2에 접근할 수 있는 포트와 IP를 제한하는 방화벽이다.

1. AWS 콘솔 > **EC2** > 좌측 메뉴 **네트워크 및 보안** > **보안 그룹**
2. **보안 그룹 생성** 클릭
3. 기본 정보:
   - 보안 그룹 이름: `snowa-sg`
   - 설명: `Snowa Trading Bot`
   - VPC: 기본 VPC 선택
4. **인바운드 규칙** — "규칙 추가"를 눌러 아래 3개를 추가:

| 유형 | 포트 범위 | 소스 | 용도 |
|------|-----------|------|------|
| SSH | 22 | **내 IP** (드롭다운에서 선택) | SSH 접속 |
| 사용자 지정 TCP | 8000 | **내 IP** | 대시보드 접속 |
| HTTPS | 443 | **내 IP** | SSL 대시보드 (선택) |

> "소스" 드롭다운에서 **내 IP**를 선택하면 현재 IP가 자동으로 입력된다. **절대로** `0.0.0.0/0`(전체 공개)으로 설정하지 않는다.

5. **아웃바운드 규칙**: 기본값(모든 트래픽 허용) 그대로 둔다
6. **보안 그룹 생성** 클릭

### 3단계. EC2 인스턴스 생성

1. AWS 콘솔 > **EC2** > **인스턴스 시작** 클릭
2. 설정을 순서대로 입력:

**이름 및 태그:**
- 이름: `snowa-trading-bot`

**애플리케이션 및 OS 이미지 (AMI):**
- **Ubuntu** 탭 클릭
- `Ubuntu Server 24.04 LTS (HVM), SSD Volume Type` 선택 (Python 3.12 기본 포함)
- 아키텍처: 64비트 (x86)

**인스턴스 유형:**
- `t3.small` (vCPU 2, 메모리 2GB) 권장
- `t3.micro` (vCPU 2, 메모리 1GB)도 가능하지만 프론트엔드 빌드 시 메모리 부족할 수 있음

**키 페어:**
- 1단계에서 만든 `snowa-key` 선택

**네트워크 설정:**
- "편집" 클릭
- **기존 보안 그룹 선택** 라디오 버튼 클릭
- 2단계에서 만든 `snowa-sg` 선택

**스토리지 구성:**
- 크기: `20` GiB
- 볼륨 유형: `gp3`

**고급 세부 정보** (하단 펼치기):
- 종료 방지: **활성화** (실수로 인스턴스 삭제 방지)
- 중지 방지: **활성화** (실수로 인스턴스 중지 방지)
- 구매 옵션: **Spot 인스턴스 요청 체크 해제** 확인 (반드시 온디맨드)

> **Spot 인스턴스는 절대 사용하지 않는다.** AWS가 언제든 회수할 수 있어 봇이 예고 없이 종료된다.

3. **인스턴스 시작** 클릭
4. 인스턴스가 `실행 중` 상태가 될 때까지 30초~1분 대기

### 4단계. Elastic IP 할당 (필수)

EC2를 재부팅하면 퍼블릭 IP가 바뀐다. 24/7 운영에서는 고정 IP가 필수다.

1. AWS 콘솔 > **EC2** > 좌측 메뉴 **네트워크 및 보안** > **탄력적 IP**
2. **탄력적 IP 주소 할당** 클릭
3. 네트워크 경계 그룹: 기본값 그대로
4. **할당** 클릭
5. 할당된 IP 주소를 클릭하여 상세 페이지로 이동
6. **탄력적 IP 주소 연결** 클릭
7. 설정:
   - 리소스 유형: `인스턴스`
   - 인스턴스: 3단계에서 만든 `snowa-trading-bot` 선택
8. **연결** 클릭

이제부터 이 고정 IP로 대시보드에 접속한다. Elastic IP는 인스턴스에 연결된 상태에서는 무료다.

### 5단계. CloudWatch 자동 복구 설정 (필수)

EC2 하드웨어에 문제가 생기면 AWS가 자동으로 인스턴스를 새 하드웨어에서 재시작하도록 설정한다.

1. AWS 콘솔 > **CloudWatch** (상단 검색창에 "CloudWatch" 검색)
2. 좌측 메뉴 **경보** > **모든 경보**
3. **경보 생성** 클릭
4. **지표 선택** 클릭:
   - `EC2` > `인스턴스별 지표` 클릭
   - 검색창에 인스턴스 ID 입력
   - `StatusCheckFailed_System` 행을 찾아 체크
   - **지표 선택** 클릭
5. 조건 설정:
   - 통계: `최소`
   - 기간: `1분`
   - 조건: `보다 크거나 같음`, 임계값: `1`
6. **다음** 클릭
7. 작업 설정:
   - **EC2 작업 추가** 클릭
   - `이 인스턴스 복구` 선택
8. 알림 설정 (선택): SNS 토픽을 만들어 이메일 알림을 받을 수 있음
9. 경보 이름: `snowa-auto-recovery`
10. **경보 생성** 클릭

### 6단계. 서버 접속 & 기본 환경 설정

Elastic IP(4단계에서 할당한 고정 IP)로 접속한다.

```bash
ssh -i ~/.ssh/snowa-key.pem ubuntu@<Elastic-IP>
```

> `<Elastic-IP>` 부분에 4단계에서 할당받은 IP 주소를 넣는다.

접속 후 시스템을 업데이트하고 필요한 패키지를 설치한다.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget unzip build-essential sqlite3
```

시간대를 KST로 설정한다:

```bash
sudo timedatectl set-timezone Asia/Seoul
```

### 7단계. Python 3.11+ 확인

프로젝트는 Python 3.11 이상이 필요하다 (`pyproject.toml`의 `requires-python = ">=3.11"`).

```bash
python3 --version
```

**Ubuntu 24.04 (Noble)**: Python 3.12가 기본 설치되어 있으므로 추가 설치 불필요. 그대로 사용한다.

**Ubuntu 22.04 (Jammy)**: Python 3.10이 기본이므로 3.11을 별도 설치해야 한다:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

> **주의:** `update-alternatives`로 시스템 기본 `python3`를 변경하지 않는다. `apt_pkg` 등 시스템 모듈이 깨진다. 가상환경 생성 시 `python3.11 -m venv .venv`로 명시적으로 지정하면 된다.

### 8단계. Node.js 20+ 설치

프론트엔드 빌드에 필요하다.

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

node --version
npm --version
```

### 9단계. 프로젝트 배포 & 의존성 설치

GitHub 저장소에서 클론한다:

```bash
cd /home/ubuntu
git clone git@github.com:blood8879/snowa-tradingbot.git snowa_tradingbot
cd snowa_tradingbot
```

> SSH 키가 없다면 HTTPS로 클론할 수도 있다:
> ```bash
> git clone https://github.com/blood8879/snowa-tradingbot.git snowa_tradingbot
> ```

Python 가상환경 생성 및 의존성 설치:

```bash
cd /home/ubuntu/apps/snowa_tradingbot

# Ubuntu 24.04: python3 (3.12) 사용
python3 -m venv .venv

# Ubuntu 22.04: python3.11 명시
# python3.11 -m venv .venv

source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 10단계. 프론트엔드 빌드

```bash
cd /home/ubuntu/apps/snowa_tradingbot/web/frontend
npm ci
npm run build

ls dist/
```

`index.html`과 `assets/` 디렉토리가 보이면 성공이다. FastAPI가 이 디렉토리를 자동으로 감지해서 서빙한다.

빌드가 메모리 부족으로 실패하면 스왑 파일을 추가한다:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

npm run build

sudo swapoff /swapfile
sudo rm /swapfile
```

### 11단계. 환경변수 설정 (.env)

```bash
cd /home/ubuntu/apps/snowa_tradingbot
cp .env.example .env
nano .env
```

아래 값들을 채운다:

```env
TRADING_MODE=paper

KIS_PAPER_APP_KEY=발급받은_앱키
KIS_PAPER_APP_SECRET=발급받은_앱시크릿
KIS_PAPER_ACCOUNT_NO=계좌번호8자리-01

TELEGRAM_BOT_TOKEN=텔레그램_봇_토큰
TELEGRAM_CHAT_ID=텔레그램_채팅_ID

DB_PATH=data/snowa.db
LOG_LEVEL=INFO
LOG_FILE=logs/snowa_bot.log
```

파일 권한을 제한한다:

```bash
chmod 600 .env
mkdir -p data logs
```

### 12단계. 수동 실행 테스트

systemd에 등록하기 전에 수동으로 정상 동작을 확인한다.

```bash
cd /home/ubuntu/apps/snowa_tradingbot
source .venv/bin/activate

# 대시보드 테스트
uvicorn web.api.main:app --host 0.0.0.0 --port 8000
# 브라우저에서 http://<Elastic-IP>:8000 접속하여 대시보드 확인
# Ctrl+C로 중지

# 봇 테스트 (별도 터미널에서)
python -m scripts.run_bot
# 로그 출력 확인 후 Ctrl+C로 중지
```

### 13단계. systemd 서비스 등록

두 프로세스를 시스템 서비스로 등록하면 서버 재부팅 시에도 자동으로 시작되고, 크래시 시 즉시 재시작된다.

**봇 서비스:**

```bash
sudo nano /etc/systemd/system/snowa-bot.service
```

```ini
[Unit]
Description=Snowa Trading Bot
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
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=snowa-bot

[Install]
WantedBy=multi-user.target
```

**대시보드 서비스:**

```bash
sudo nano /etc/systemd/system/snowa-dashboard.service
```

```ini
[Unit]
Description=Snowa Trading Dashboard (FastAPI)
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
```

- `Restart=always`: 어떤 이유로든 프로세스가 종료되면 무조건 재시작
- `RestartSec`: 재시작까지 대기 시간 (대시보드는 5초, 봇은 10초)
- `StartLimitIntervalSec=300`, `StartLimitBurst=10`: 5분 내 10회 이상 재시작 실패 시 중단 (무한 루프 방지)

서비스 등록 및 시작:

```bash
sudo systemctl daemon-reload

sudo systemctl enable snowa-bot.service
sudo systemctl enable snowa-dashboard.service

sudo systemctl start snowa-bot.service
sudo systemctl start snowa-dashboard.service

sudo systemctl status snowa-bot.service
sudo systemctl status snowa-dashboard.service
```

두 서비스 모두 `active (running)` 상태이면 성공이다. 브라우저에서 `http://<Elastic-IP>:8000`으로 대시보드에 접속할 수 있다.

### 14단계. Nginx 리버스 프록시 (선택)

HTTPS를 적용하거나 80번 포트로 접속하고 싶다면 Nginx를 사용한다.

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/snowa
```

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/snowa /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

Nginx를 사용하면 보안 그룹에 80번 포트도 추가해야 한다:

1. AWS 콘솔 > **EC2** > **보안 그룹** > `snowa-sg` 클릭
2. **인바운드 규칙** 탭 > **인바운드 규칙 편집** 클릭
3. **규칙 추가**: 유형 `HTTP`, 포트 `80`, 소스 `내 IP`
4. **규칙 저장** 클릭

### 15단계. Let's Encrypt SSL (선택)

도메인이 있다면 무료 SSL 인증서를 적용할 수 있다.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 내도메인.com
sudo certbot renew --dry-run
```

보안 그룹에 443 포트도 추가한다 (14단계와 동일한 방법으로).

---

## 방법 2: Docker + EC2

Docker를 사용하면 Python, Node.js 버전 관리를 호스트에서 할 필요 없이 환경 구성이 깔끔해진다.

EC2 인스턴스 생성은 방법 1의 1~5단계와 동일하다 (키 페어, 보안 그룹, EC2 생성, Elastic IP, Auto Recovery).

### Dockerfile (멀티 스테이지 빌드)

프로젝트 루트에 `Dockerfile`을 생성한다:

```dockerfile
# Stage 1: 프론트엔드 빌드
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web/frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

# Stage 2: Python 런타임
FROM python:3.11-slim AS runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir .
COPY . .
COPY --from=frontend-builder /app/web/frontend/dist /app/web/frontend/dist
RUN mkdir -p data logs
EXPOSE 8000
CMD ["uvicorn", "web.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### .dockerignore

```
.venv/
__pycache__/
*.pyc
.env
.git/
node_modules/
web/frontend/dist/
web/frontend/node_modules/
*.egg-info/
.pytest_cache/
logs/*.log
```

### docker-compose.yml

```yaml
services:
  dashboard:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: snowa-dashboard
    restart: always
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    command: >
      uvicorn web.api.main:app
      --host 0.0.0.0
      --port 8000

  bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: snowa-bot
    restart: always
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    command: >
      python -m scripts.run_bot
    depends_on:
      - dashboard
```

`restart: always`로 설정하면 컨테이너가 어떤 이유로 종료되어도 자동 재시작된다.

### EC2에서 Docker로 실행

```bash
ssh -i ~/.ssh/snowa-key.pem ubuntu@<Elastic-IP>

sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu

exit
ssh -i ~/.ssh/snowa-key.pem ubuntu@<Elastic-IP>

cd /home/ubuntu/apps/snowa_tradingbot
cp .env.example .env
nano .env

docker compose up -d --build
docker compose ps
docker compose logs -f
```

### Docker 관리 명령어

```bash
docker compose down              # 전체 중지
docker compose restart bot       # 봇만 재시작
docker compose logs -f bot       # 봇 로그
docker compose logs -f dashboard # 대시보드 로그
docker compose exec bot bash     # 컨테이너 접속

# 코드 업데이트 후 재빌드
git pull origin main
docker compose up -d --build
```

---

## 운영 가이드

### 로그 확인

systemd(방법 1) 사용 시:

```bash
sudo journalctl -u snowa-bot.service -f          # 봇 로그 (실시간)
sudo journalctl -u snowa-dashboard.service -f     # 대시보드 로그 (실시간)
sudo journalctl -u snowa-bot.service -n 100       # 최근 100줄
sudo journalctl -u snowa-bot.service --since today # 오늘 로그만

tail -f /home/ubuntu/apps/snowa_tradingbot/logs/*.log  # 파일 로그
```

### 서비스 재시작

```bash
sudo systemctl restart snowa-bot.service
sudo systemctl restart snowa-dashboard.service
sudo systemctl status snowa-bot.service
```

### 코드 업데이트 & 재배포

```bash
cd /home/ubuntu/apps/snowa_tradingbot

git pull origin main

source .venv/bin/activate
pip install -e .

cd web/frontend
npm ci
npm run build
cd ../..

sudo systemctl restart snowa-bot.service snowa-dashboard.service
sudo systemctl status snowa-bot.service snowa-dashboard.service
```

GitHub에 push 후 EC2에서 pull하는 방식이 가장 깔끔하다. rsync로 직접 동기화할 수도 있다:

```bash
rsync -avz --exclude '.venv' --exclude 'node_modules' --exclude '.env' \
  --exclude 'data/' --exclude 'logs/' --exclude '__pycache__' \
  -e "ssh -i ~/.ssh/snowa-key.pem" \
  /Users/yunjihwan/Documents/project/snowa_tradingbot/ \
  ubuntu@<Elastic-IP>:/home/ubuntu/apps/snowa_tradingbot/
```

### SQLite DB 백업 (S3)

**S3 버킷 생성:**

1. AWS 콘솔 > **S3** (상단 검색)
2. **버킷 만들기** 클릭
3. 버킷 이름: `snowa-backups-본인아이디` (전세계 고유해야 함)
4. AWS 리전: `아시아 태평양 (서울)`
5. 나머지 기본값 > **버킷 만들기** 클릭

**EC2에 S3 접근 권한 부여 (IAM 역할):**

1. AWS 콘솔 > **IAM** (상단 검색)
2. 좌측 메뉴 **역할** > **역할 생성**
3. 신뢰할 수 있는 엔터티 유형: `AWS 서비스`
4. 사용 사례: `EC2` 선택 > **다음**
5. 권한 정책 검색: `AmazonS3FullAccess` 체크 > **다음**
6. 역할 이름: `snowa-ec2-s3-role` > **역할 생성**
7. AWS 콘솔 > **EC2** > **인스턴스** > `snowa-trading-bot` 선택
8. **작업** > **보안** > **IAM 역할 수정**
9. `snowa-ec2-s3-role` 선택 > **IAM 역할 업데이트**

**백업 스크립트 생성 (EC2에서):**

```bash
nano /home/ubuntu/backup_db.sh
```

```bash
#!/bin/bash
DB_PATH="/home/ubuntu/apps/snowa_tradingbot/data/snowa.db"
S3_BUCKET="snowa-backups-본인아이디"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="snowa_${TIMESTAMP}.db"

sqlite3 "$DB_PATH" ".backup /tmp/${BACKUP_NAME}"
aws s3 cp "/tmp/${BACKUP_NAME}" "s3://${S3_BUCKET}/db-backups/${BACKUP_NAME}"
rm -f "/tmp/${BACKUP_NAME}"
echo "Backup completed: ${BACKUP_NAME}"
```

```bash
chmod +x /home/ubuntu/backup_db.sh
```

cron 등록 (매일 KST 07:00):

```bash
crontab -e
```

```
0 7 * * * /home/ubuntu/backup_db.sh >> /home/ubuntu/apps/snowa_tradingbot/logs/backup.log 2>&1
```

### 헬스체크 & 자동 알림

대시보드가 살아있는지 5분마다 확인하고, 응답이 없으면 텔레그램으로 알리는 스크립트:

```bash
nano /home/ubuntu/healthcheck.sh
```

```bash
#!/bin/bash
DASHBOARD_URL="http://localhost:8000/api/health"
TELEGRAM_BOT_TOKEN="텔레그램_봇_토큰"
TELEGRAM_CHAT_ID="텔레그램_채팅_ID"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$DASHBOARD_URL")

if [ "$HTTP_CODE" != "200" ]; then
    MESSAGE="[ALERT] Snowa Dashboard 응답 없음 (HTTP ${HTTP_CODE}). 자동 재시작 시도 중."
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="${MESSAGE}"

    sudo systemctl restart snowa-dashboard.service
fi
```

```bash
chmod +x /home/ubuntu/healthcheck.sh

crontab -e
```

아래 줄 추가:

```
*/5 * * * * /home/ubuntu/healthcheck.sh >> /home/ubuntu/apps/snowa_tradingbot/logs/healthcheck.log 2>&1
```

---

## 24/7 무중단 운영 체크리스트

배포 완료 후 아래 항목을 모두 확인한다.

- [ ] **온디맨드 인스턴스**를 사용하고 있는가 (Spot 아님)
- [ ] **종료 보호 (Termination Protection)** 가 활성화되어 있는가
- [ ] **중지 보호 (Stop Protection)** 가 활성화되어 있는가
- [ ] **Elastic IP**가 할당되어 인스턴스에 연결되어 있는가
- [ ] systemd 서비스의 `Restart=always`가 설정되어 있는가
- [ ] systemd 서비스가 `enable` 상태인가 (`systemctl is-enabled snowa-bot snowa-dashboard`)
- [ ] **CloudWatch Auto Recovery** 경보가 설정되어 있는가
- [ ] 헬스체크 cron이 등록되어 있는가 (5분 간격)
- [ ] 헬스체크 실패 시 텔레그램 알림이 오는가
- [ ] DB 백업 cron이 등록되어 있는가
- [ ] 서버 시간대가 `Asia/Seoul`로 설정되어 있는가

---

## 보안 체크리스트

### 필수

- [ ] `.env` 파일 권한이 `600`인가 (`chmod 600 .env`)
- [ ] `.env` 파일이 `.gitignore`에 포함되어 있는가
- [ ] 보안 그룹 SSH(22번 포트)가 내 IP로만 제한되어 있는가
- [ ] 보안 그룹 대시보드 포트(8000 또는 80)가 내 IP로만 제한되어 있는가
- [ ] EC2 키 페어 파일(`.pem`) 권한이 `400`인가
- [ ] KIS API 키가 소스코드에 하드코딩되어 있지 않은가
- [ ] `root`가 아닌 `ubuntu` 사용자로 서비스가 실행되는가

### 권장

- [ ] SSH 비밀번호 인증 비활성화
- [ ] HTTPS 적용 (Nginx + Let's Encrypt)
- [ ] 자동 보안 업데이트 활성화

```bash
# SSH 비밀번호 인증 비활성화
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no (주석 해제 후 no로 변경)
sudo systemctl restart sshd

# 자동 보안 업데이트
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 비용 예상

ap-northeast-2(서울) 리전, 온디맨드 기준 월별 비용:

### 방법 1: EC2 단일 인스턴스

| 항목 | 사양 | 월 비용 (약) |
|------|------|-------------|
| EC2 t3.micro | 2 vCPU, 1GB RAM | $8.50 |
| EC2 t3.small | 2 vCPU, 2GB RAM | $17.00 |
| EBS (gp3, 20GB) | 범용 SSD | $1.60 |
| Elastic IP | 인스턴스 연결 시 | $0 |
| 데이터 전송 | 첫 100GB 무료 | $0 |
| **합계 (t3.micro)** | | **~$10/월** |
| **합계 (t3.small)** | | **~$19/월** |

**절약: 예약 인스턴스 (1년)**

24/7 운영이라면 예약 인스턴스가 가장 합리적이다. 온디맨드 대비 약 30~40% 할인.

1. AWS 콘솔 > **EC2** > 좌측 메뉴 **예약 인스턴스**
2. **예약 인스턴스 구매** 클릭
3. 인스턴스 유형 (`t3.small`), 기간 (1년), 결제 옵션 선택
4. **구매** 클릭

> **Spot 인스턴스: 절대 사용 금지.** AWS가 언제든 회수하며 봇이 예고 없이 종료된다.

### 방법 2: Docker + EC2

EC2 비용과 동일하다. Docker 자체는 추가 비용 없음.

---

## 부록: 자주 묻는 질문

**Q: 봇이 돌다가 죽으면?**

3단계 자동 복구가 작동한다:
1. **systemd `Restart=always`**: 프로세스 종료 시 즉시 재시작
2. **헬스체크 cron**: 5분마다 대시보드 응답을 확인, 실패 시 텔레그램 알림 + 자동 재시작
3. **CloudWatch Auto Recovery**: EC2 하드웨어 장애 시 새 하드웨어에서 자동 복구

**Q: EC2가 내 승인 없이 종료될 수 있나?**

종료 보호와 중지 보호를 설정하면 콘솔이나 API에서 실수로 삭제/중지할 수 없다. 의도적으로 종료하려면 보호를 먼저 해제해야 한다. AWS 하드웨어 장애 시에는 Auto Recovery가 작동하므로 사실상 중단 시간이 거의 없다.

**Q: SQLite로 충분한가?**

개인 봇 수준에서는 충분하다. 동시 쓰기가 봇과 대시보드 두 프로세스뿐이고, aiosqlite가 WAL 모드를 지원하므로 동시성 문제도 거의 없다.

**Q: 보안 그룹의 "내 IP"가 바뀌면?**

가정용 인터넷은 IP가 주기적으로 바뀐다. 대시보드에 접속이 안 되면:

1. AWS 콘솔 > **EC2** > **보안 그룹** > `snowa-sg` 클릭
2. **인바운드 규칙 편집**
3. 기존 IP 삭제 > **내 IP**로 다시 추가
4. **규칙 저장**

**Q: 종료/중지 보호 설정을 확인하려면?**

1. AWS 콘솔 > **EC2** > **인스턴스** > `snowa-trading-bot` 선택
2. 하단 **세부 정보** 탭
3. "종료 방지" 항목이 `활성화됨`인지 확인
4. "중지 방지" 항목이 `활성화됨`인지 확인

변경하려면: **작업** > **인스턴스 설정** > **종료 방지 변경** / **중지 방지 변경**
