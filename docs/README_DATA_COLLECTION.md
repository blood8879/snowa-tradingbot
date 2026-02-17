# yfinance 데이터 수집 가이드

> CANSLIM x Turtle Trading Bot을 위한 8000종목 데이터 수집

---

## 📋 목차

1. [Quick Start](#quick-start)
2. [yfinance API 레퍼런스](#yfinance-api-레퍼런스)
3. [벌크 수집 패턴](#벌크-수집-패턴)
4. [Production 코드](#production-코드)
5. [데이터 구조](#데이터-구조)
6. [트러블슈팅](#트러블슈팅)

---

## Quick Start

### 1. 설치

```bash
pip install yfinance pandas numpy get-all-tickers
```

### 2. 간단한 예시

```python
import yfinance as yf

# 단일 종목
ticker = yf.Ticker("AAPL")
print(ticker.info['trailingEps'])  # EPS
print(ticker.quarterly_earnings)   # 분기별 실적

# 다중 종목 (가격 데이터)
data = yf.download(['AAPL', 'MSFT', 'GOOGL'], period='1y', threads=True)
```

### 3. 전체 파이프라인 실행

```bash
cd /Users/yunjihwan/Documents/project/snowa_tradingbot
python docs/yfinance_bulk_collection_examples.py
```

**예상 소요 시간:**
- 가격 데이터 (8000종목, 300일): **~30분**
- 재무 데이터 (8000종목): **~1-2시간**
- **총 초기 로드: 2-3시간**

---

## yfinance API 레퍼런스

### Ticker 객체 속성

| 속성 | 설명 | 반환 타입 |
|------|------|-----------|
| `ticker.info` | 모든 기본 정보 (dict) | `Dict` |
| `ticker.quarterly_income_stmt` | 분기별 손익계산서 | `DataFrame` |
| `ticker.quarterly_balance_sheet` | 분기별 재무상태표 | `DataFrame` |
| `ticker.quarterly_cashflow` | 분기별 현금흐름표 | `DataFrame` |
| `ticker.quarterly_earnings` | 분기별 실적 (간략) | `DataFrame` |
| `ticker.institutional_holders` | 기관투자자 정보 | `DataFrame` |
| `ticker.major_holders` | 주요 보유자 비율 | `DataFrame` |
| `ticker.history(period='1y')` | 가격 데이터 | `DataFrame` |

### info Dict - CANSLIM 핵심 키

#### E - Earnings (EPS)
```python
ticker.info['trailingEps']           # TTM EPS
ticker.info['forwardEps']            # Forward EPS  
ticker.info['earningsGrowth']        # YoY 성장률
ticker.info['earningsQuarterlyGrowth']  # QoQ 성장률
```

#### A - Annual Earnings (매출)
```python
ticker.info['revenueGrowth']         # 매출 성장률
ticker.info['totalRevenue']          # 총 매출
```

#### L - Leader (수익성)
```python
ticker.info['returnOnEquity']        # ROE
ticker.info['returnOnAssets']        # ROA
ticker.info['profitMargins']         # 순이익률
ticker.info['operatingMargins']      # 영업이익률
```

#### I - Institutional (기관)
```python
ticker.info['heldPercentInstitutions']  # 기관 보유 비율
ticker.info['heldPercentInsiders']      # 내부자 보유 비율
```

#### S/M - Supply & Market (시장)
```python
ticker.info['volume']                # 거래량
ticker.info['averageVolume']         # 평균 거래량
ticker.info['marketCap']             # 시가총액
ticker.info['floatShares']           # 유동주식수
```

> 📖 **전체 리스트:** [yfinance_reference.md](./yfinance_reference.md)

---

## 벌크 수집 패턴

### 패턴 1: 가격 데이터 (yf.download)

```python
import yfinance as yf
import time

tickers = ['AAPL', 'MSFT', ...]  # 8000개

# 배치 단위로 분할
BATCH_SIZE = 100
DELAY = 2.0

for i in range(0, len(tickers), BATCH_SIZE):
    batch = tickers[i:i+BATCH_SIZE]
    
    data = yf.download(
        tickers=batch,
        period="300d",
        interval="1d",
        group_by='ticker',
        auto_adjust=True,
        threads=True,      # 병렬 다운로드
        progress=False
    )
    
    # 데이터 저장
    # ...
    
    time.sleep(DELAY)  # Rate limiting
```

**핵심 포인트:**
- ✅ `threads=True`: yfinance 내장 멀티스레딩
- ✅ `group_by='ticker'`: 종목별로 컬럼 그룹화
- ✅ `auto_adjust=True`: 배당/분할 자동 조정
- ✅ 배치 크기 100, 딜레이 2초 (안전)

### 패턴 2: 재무 데이터 (개별 Ticker)

```python
import yfinance as yf
import time

results = {}

for symbol in tickers:
    ticker = yf.Ticker(symbol)
    
    try:
        results[symbol] = {
            'info': ticker.info,
            'quarterly_earnings': ticker.quarterly_earnings,
            'institutional_holders': ticker.institutional_holders,
        }
    except Exception as e:
        print(f"Failed: {symbol} - {e}")
    
    time.sleep(0.5)  # Rate limiting
```

**핵심 포인트:**
- ⚠️ 재무 데이터는 벌크 API 없음 → 개별 순회 필수
- ⏱️ 8000종목 * 0.5초 = **약 1시간 소요**
- 💾 체크포인트 저장 (500개마다) 권장

### 패턴 3: 에러 처리 & 재시도

```python
import requests.exceptions
import time

MAX_RETRIES = 3

for retry in range(MAX_RETRIES):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        break
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in [429, 403, 999]:
            # Rate limit - Exponential Backoff
            wait_time = 2 ** retry
            print(f"Rate limited. Waiting {wait_time}s...")
            time.sleep(wait_time)
        else:
            break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(1 * retry)
```

**핵심 포인트:**
- 🔁 Exponential backoff: 1s → 2s → 4s
- 🚦 HTTP 429/403/999: Rate limit 에러
- 🔄 최대 3회 재시도

---

## Production 코드

### 파일 구조

```
docs/
├── yfinance_reference.md                 # API 레퍼런스 (이 문서)
├── yfinance_bulk_collection_examples.py  # Production 코드
└── README_DATA_COLLECTION.md             # 이 가이드

data/cache/
├── price_data_300d.pkl                   # 가격 데이터
├── fundamental_data.pkl                  # 재무 데이터 (raw)
├── canslim_metrics.csv                   # CANSLIM 지표 (추출)
├── failed_tickers_price.txt              # 실패 종목 (가격)
└── failed_tickers_fundamental.txt        # 실패 종목 (재무)
```

### 주요 함수

#### 1. `get_ticker_list_nasdaq_ftp()`
- NASDAQ FTP에서 NYSE + NASDAQ 종목 리스트 다운로드
- 매일 업데이트되는 공식 데이터
- ~8000개 종목 반환

#### 2. `download_price_data_bulk()`
- 여러 종목의 가격 데이터 배치 다운로드
- 배치 크기: 100종목
- 딜레이: 2초
- 재시도: 3회

#### 3. `download_fundamental_data_bulk()`
- 개별 종목의 재무 데이터 순차 수집
- 딜레이: 0.5초/종목
- 체크포인트: 500개마다 저장
- 예상 시간: ~1-2시간 (8000종목)

#### 4. `extract_canslim_metrics()`
- 재무 데이터에서 CANSLIM 지표 추출
- 출력: DataFrame (CSV 저장)

### 실행 예시

```bash
# 전체 파이프라인 실행
python docs/yfinance_bulk_collection_examples.py

# 출력 예시:
# [Step 1/3] Fetching ticker list...
# Found 8234 valid tickers
#
# [Step 2/3] Downloading price data...
# Processing batch 1/83: 100 tickers
# Processing batch 2/83: 100 tickers
# ...
# Saved: data/cache/price_data_300d.pkl
#
# [Step 3/3] Downloading fundamental data...
# Progress: 100/8234 (1.2%) | ETA: 68.3min
# Progress: 200/8234 (2.4%) | ETA: 67.1min
# ...
# Saved: data/cache/fundamental_data.pkl
# Saved: data/cache/canslim_metrics.csv
```

---

## 데이터 구조

### price_data_300d.pkl

```python
import pandas as pd

df = pd.read_pickle("data/cache/price_data_300d.pkl")

# MultiIndex DataFrame
# Level 0 (columns): Open, High, Low, Close, Volume
# Level 1 (columns): Ticker symbols
# Index: Date

# 특정 종목 추출
aapl = df.xs('AAPL', level=1, axis=1)
#              Open    High     Low   Close     Volume
# 2024-01-01  180.0  185.0   179.0   184.5  50000000
# 2024-01-02  184.5  186.0   183.0   185.0  48000000
```

### fundamental_data.pkl

```python
import pickle

with open("data/cache/fundamental_data.pkl", "rb") as f:
    data = pickle.load(f)

# Dict[str, Dict]
# {
#   'AAPL': {
#     'info': {...},
#     'quarterly_earnings': DataFrame,
#     'quarterly_income_stmt': DataFrame,
#     'quarterly_balance_sheet': DataFrame,
#     'institutional_holders': DataFrame
#   },
#   'MSFT': {...},
#   ...
# }

# 사용 예시
aapl_eps = data['AAPL']['info'].get('trailingEps')
aapl_earnings = data['AAPL']['quarterly_earnings']
```

### canslim_metrics.csv

```python
import pandas as pd

df = pd.read_csv("data/cache/canslim_metrics.csv")

# Columns:
# - symbol
# - eps_ttm, eps_forward, eps_growth_yoy
# - revenue_growth, revenue
# - roe, profit_margin, operating_margin
# - institutional_ownership, num_institutions
# - market_cap, volume, float_shares
# - sector, industry, exchange

# CANSLIM 스크리닝
filtered = df[
    (df['eps_growth_yoy'] > 0.25) &  # E: 25% 이상 성장
    (df['revenue_growth'] > 0.25) &   # A: 매출 25% 이상
    (df['roe'] > 0.17) &              # L: ROE 17% 이상
    (df['institutional_ownership'] > 0.5)  # I: 기관 50% 이상
]
```

---

## 트러블슈팅

### ❌ HTTP 429/403/999 에러

**증상:**
```
requests.exceptions.HTTPError: 429 Client Error: Too Many Requests
```

**해결:**
1. 배치 크기 줄이기 (100 → 50)
2. 딜레이 늘리기 (2초 → 5초)
3. Exponential backoff 확인
4. IP 변경 (VPN, 다른 네트워크)

### ❌ Empty DataFrame

**증상:**
```python
data = yf.download(['AAPL'], period='1y')
# Empty DataFrame
```

**해결:**
1. 티커 심볼 확인 (대문자, 올바른 심볼)
2. period 변경 ('1y' → 'max')
3. yfinance 업데이트: `pip install --upgrade yfinance`
4. Yahoo Finance 웹사이트에서 티커 확인

### ❌ info dict가 비어있음

**증상:**
```python
ticker = yf.Ticker("NEWIPO")
print(ticker.info)  # {} 또는 minimal data
```

**해결:**
1. 신규 IPO는 데이터 부족 (정상)
2. `safe_get_info()` 함수 사용 (기본값 설정)
3. quarterly_earnings 확인 (None일 수 있음)

### ❌ MultiIndex 에러

**증상:**
```python
data['Close']  # KeyError
```

**해결:**
```python
# 방법 1: xs() 사용
close = data.xs('Close', level=0, axis=1)

# 방법 2: Flatten
data.columns = ['_'.join(col).strip() for col in data.columns.values]
close = data['Close_AAPL']
```

### ⚠️ Rate Limit 권장 수치

| 시나리오 | 배치 크기 | 딜레이 | 시간당 요청 |
|---------|-----------|--------|-------------|
| **안전 (권장)** | 100 | 2초 | ~1500 |
| 보통 | 200 | 1초 | ~2000 |
| 공격적 (위험) | 500 | 0.5초 | ~3600 |

> 💡 **권장:** 배치 100, 딜레이 2초 → **시간당 1500 요청** (안전)

---

## 다음 단계

### 1. 데이터 로더 구현

```python
# data/fundamental_data.py
import pickle

class FundamentalDataLoader:
    def __init__(self, data_path="data/cache/fundamental_data.pkl"):
        with open(data_path, "rb") as f:
            self.data = pickle.load(f)
    
    def get_canslim_scores(self, symbol: str) -> dict:
        """CANSLIM 점수 계산"""
        # TODO: 구현
        pass
```

### 2. 가격 캐시 구현

```python
# data/price_cache.py
import pandas as pd

class PriceCache:
    def __init__(self, data_path="data/cache/price_data_300d.pkl"):
        self.df = pd.read_pickle(data_path)
    
    def get_ohlcv(self, symbol: str, days: int = 300) -> pd.DataFrame:
        """특정 종목의 OHLCV 데이터 반환"""
        return self.df.xs(symbol, level=1, axis=1).tail(days)
    
    def calculate_turtle_channels(self, symbol: str, period: int = 20):
        """Turtle Trading 채널 계산"""
        # TODO: 구현
        pass
```

### 3. 스케줄링

```bash
# crontab -e (Linux/Mac)
# 매일 오전 6시 (시장 전) 실행
0 6 * * * cd /path/to/project && python scripts/update_data.py

# Windows Task Scheduler
# 작업 스케줄러 → 새 작업 → 트리거: 매일 오전 6시
```

---

## 참고 자료

- **yfinance GitHub:** https://github.com/ranaroussi/yfinance
- **yfinance 공식 문서:** https://ranaroussi.github.io/yfinance/
- **NASDAQ FTP:** ftp://ftp.nasdaqtrader.com/SymbolDirectory/
- **Yahoo Finance API 약관:** https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html

---

## 문의

- **프로젝트:** CANSLIM x Turtle Trading Bot
- **데이터 소스:** Yahoo! Finance (via yfinance)
- **라이선스:** Personal use only (Yahoo 약관 참조)
- **작성일:** 2026-02-14

---

**NOTE:** yfinance는 비공식 라이브러리입니다. Production 환경에서는 상용 API (Polygon, Finnhub, FMP 등) 사용을 권장합니다.
