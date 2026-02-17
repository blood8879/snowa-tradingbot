# yfinance Production Reference Guide

## 1. Ticker 객체 재무 데이터 속성

### 1.1 재무제표 (Financial Statements)
```python
import yfinance as yf

ticker = yf.Ticker("AAPL")

# Income Statement (손익계산서)
ticker.income_stmt           # Annual income statement
ticker.quarterly_income_stmt # Alias: quarterly_financials
ticker.quarterly_financials  # DEPRECATED alias

# Balance Sheet (재무상태표)
ticker.balance_sheet          # Annual balance sheet
ticker.quarterly_balance_sheet

# Cash Flow (현금흐름표)
ticker.cashflow               # Annual cash flow
ticker.quarterly_cashflow

# Earnings (분기별 실적)
ticker.quarterly_earnings     # Revenue, Earnings columns
```

### 1.2 기관투자자 정보
```python
# Institutional Holders
ticker.institutional_holders  
# Columns: Holder, Shares, Date Reported, % Out, Value

# Major Holders
ticker.major_holders
# % of Shares Held by All Insider
# % of Shares Held by Institutions
# % of Float Held by Institutions
# Number of Institutions Holding Shares
```

### 1.3 CANSLIM 핵심 데이터 - info Dict Keys

#### EPS & Earnings (E in CANSLIM)
```python
ticker.info['trailingEps']           # TTM EPS
ticker.info['forwardEps']            # Forward EPS
ticker.info['trailingPE']            # P/E ratio
ticker.info['forwardPE']             # Forward P/E
ticker.info['earningsGrowth']        # YoY earnings growth
ticker.info['earningsQuarterlyGrowth']  # QoQ growth
```

#### Revenue & Sales (A in CANSLIM - Annual Earnings Increase)
```python
ticker.info['revenueGrowth']         # Revenue growth rate
ticker.info['totalRevenue']          # Total revenue
ticker.info['revenuePerShare']       # Revenue per share
```

#### Profitability & ROE (L in CANSLIM - Leader in Industry)
```python
ticker.info['returnOnEquity']        # ROE
ticker.info['returnOnAssets']        # ROA
ticker.info['profitMargins']         # Net profit margin
ticker.info['operatingMargins']      # Operating margin
ticker.info['grossMargins']          # Gross margin
ticker.info['ebitdaMargins']         # EBITDA margin
```

#### Institutional Support (I in CANSLIM)
```python
ticker.info['heldPercentInstitutions']  # % held by institutions
ticker.info['heldPercentInsiders']      # % held by insiders
```

#### Market & Supply/Demand (M in CANSLIM)
```python
ticker.info['volume']                # Current volume
ticker.info['averageVolume']         # Average volume
ticker.info['averageVolume10days']   # 10-day avg volume
ticker.info['marketCap']             # Market capitalization
ticker.info['sharesOutstanding']     # Shares outstanding
ticker.info['floatShares']           # Float shares
```

#### Price & Valuation
```python
ticker.info['currentPrice']
ticker.info['previousClose']
ticker.info['fiftyTwoWeekLow']
ticker.info['fiftyTwoWeekHigh']
ticker.info['fiftyDayAverage']
ticker.info['twoHundredDayAverage']
ticker.info['priceToSalesTrailing12Months']
ticker.info['priceToBook']
ticker.info['bookValue']
```

#### Company Info
```python
ticker.info['sector']
ticker.info['industry']
ticker.info['fullTimeEmployees']
ticker.info['longBusinessSummary']
ticker.info['exchange']
ticker.info['quoteType']
```

### 1.4 Missing Data Handling
```python
# Many keys may not exist or be None
# Always use .get() with defaults
eps = ticker.info.get('trailingEps', None)
roe = ticker.info.get('returnOnEquity', None)

if eps is None or roe is None:
    # Handle missing data
    pass
```

---

## 2. 벌크 수집 패턴

### 2.1 yf.download() - 가격 데이터 벌크 다운로드

```python
import yfinance as yf
import pandas as pd
import time
from typing import List, Optional

def download_price_data_bulk(
    tickers: List[str],
    period: str = "1y",
    interval: str = "1d",
    batch_size: int = 100,
    delay_between_batches: float = 2.0,
    max_retries: int = 3
) -> pd.DataFrame:
    """
    벌크로 여러 종목의 가격 데이터를 다운로드
    
    Args:
        tickers: 종목 리스트 (최대 8000개)
        period: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
        interval: "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
        batch_size: 한 번에 요청할 종목 수 (권장: 50-200)
        delay_between_batches: 배치 간 대기 시간 (초)
        max_retries: 재시도 횟수
    
    Returns:
        MultiIndex DataFrame (Date, Ticker)
    """
    all_data = []
    failed_tickers = []
    
    # 배치 단위로 분할
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"Processing batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1}: {len(batch)} tickers")
        
        retries = 0
        while retries < max_retries:
            try:
                # threads=True로 병렬 다운로드 (yfinance 내장 기능)
                data = yf.download(
                    tickers=batch,
                    period=period,
                    interval=interval,
                    group_by='ticker',  # 종목별로 그룹화
                    auto_adjust=True,   # Adjust OHLC automatically
                    threads=True,       # 멀티스레딩 활성화
                    progress=False      # 진행바 비활성화
                )
                
                if not data.empty:
                    all_data.append(data)
                    break
                else:
                    print(f"  Empty data for batch, retrying...")
                    retries += 1
                    
            except Exception as e:
                print(f"  Error downloading batch: {e}")
                retries += 1
                time.sleep(delay_between_batches * retries)  # Exponential backoff
                
        if retries >= max_retries:
            print(f"  Failed to download batch after {max_retries} retries")
            failed_tickers.extend(batch)
        
        # Rate limiting - 배치 간 대기
        if i + batch_size < len(tickers):
            time.sleep(delay_between_batches)
    
    # 결과 병합
    if all_data:
        result = pd.concat(all_data, axis=1)
        print(f"\nSuccessfully downloaded {len(tickers) - len(failed_tickers)}/{len(tickers)} tickers")
        if failed_tickers:
            print(f"Failed tickers: {failed_tickers}")
        return result
    else:
        raise ValueError("No data downloaded")
```

### 2.2 재무 데이터 벌크 수집

```python
import yfinance as yf
import pandas as pd
import time
from typing import Dict, List, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_fundamental_data_bulk(
    tickers: List[str],
    delay_per_ticker: float = 0.5,
    max_retries: int = 3
) -> Dict[str, Dict]:
    """
    8000종목의 재무 데이터를 개별적으로 수집 (yfinance는 재무 데이터 벌크 API 미제공)
    
    WARNING: 8000종목 x 0.5초 = 약 1시간 소요
    
    Returns:
        {ticker: {info: {...}, quarterly_earnings: DataFrame, ...}}
    """
    results = {}
    failed_tickers = []
    
    for idx, symbol in enumerate(tickers):
        if idx % 100 == 0:
            logger.info(f"Progress: {idx}/{len(tickers)} ({idx/len(tickers)*100:.1f}%)")
        
        retries = 0
        while retries < max_retries:
            try:
                ticker = yf.Ticker(symbol)
                
                # 필수 데이터만 수집 (속도 최적화)
                data = {
                    'info': ticker.info,
                    'quarterly_earnings': ticker.quarterly_earnings,
                    'quarterly_income_stmt': ticker.quarterly_income_stmt,
                    'institutional_holders': ticker.institutional_holders,
                }
                
                # 데이터 유효성 검증
                if data['info'] and len(data['info']) > 5:
                    results[symbol] = data
                    break
                else:
                    logger.warning(f"  {symbol}: Empty or invalid data")
                    retries += 1
                    
            except Exception as e:
                logger.error(f"  {symbol}: Error - {e}")
                retries += 1
                time.sleep(delay_per_ticker * retries)  # Exponential backoff
        
        if retries >= max_retries:
            failed_tickers.append(symbol)
        
        # Rate limiting
        time.sleep(delay_per_ticker)
    
    logger.info(f"\nCompleted: {len(results)}/{len(tickers)} tickers")
    if failed_tickers:
        logger.warning(f"Failed tickers ({len(failed_tickers)}): {failed_tickers[:10]}...")
    
    return results
```

### 2.3 에러 처리 & 재시도 패턴

```python
import yfinance as yf
import time
from typing import Optional
import requests.exceptions

def safe_download_with_retry(
    ticker: str,
    max_retries: int = 3,
    backoff_factor: float = 2.0
) -> Optional[yf.Ticker]:
    """
    안전한 티커 다운로드 with exponential backoff
    """
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            _ = t.info  # Trigger data fetch
            return t
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [429, 403, 999]:  # Rate limit
                wait_time = backoff_factor ** attempt
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"HTTP Error {e.response.status_code}: {e}")
                break
                
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            time.sleep(backoff_factor ** attempt)
            
        except Exception as e:
            print(f"Unknown error: {e}")
            break
    
    return None

# 사용 예시
ticker = safe_download_with_retry("AAPL", max_retries=3)
if ticker:
    print(ticker.info['longName'])
```

### 2.4 실패한 티커 추적

```python
import yfinance as yf

def download_with_error_tracking(tickers: List[str]) -> tuple:
    """
    yfinance.shared._ERRORS를 사용한 에러 추적
    """
    # Download data
    data = yf.download(tickers, period="5d", threads=True, progress=False)
    
    # Check for errors (yfinance 0.2.0+)
    if hasattr(yf.shared, '_ERRORS'):
        errors = yf.shared._ERRORS
        if errors:
            print(f"Failed tickers: {list(errors.keys())}")
            for ticker, error_msg in errors.items():
                print(f"  {ticker}: {error_msg}")
    
    return data, errors if hasattr(yf.shared, '_ERRORS') else {}
```

---

## 3. NYSE + NASDAQ 종목 리스트 가져오기

### 3.1 방법 1: get-all-tickers (가장 간단)

```python
# pip install get-all-tickers

from get_all_tickers import get_tickers

# NYSE + NASDAQ 전체
tickers = get_tickers(NYSE=True, NASDAQ=True)
print(f"Total tickers: {len(tickers)}")  # ~8000개

# 필터링 옵션
tickers_large_cap = get_tickers(NYSE=True, NASDAQ=True, market_cap='large')
tickers_tech = get_tickers(NASDAQ=True, sector='technology')
```

### 3.2 방법 2: NASDAQ FTP 서버 (가장 정확, 매일 업데이트)

```python
import ftplib
import pandas as pd
import io

def download_nasdaq_listed() -> pd.DataFrame:
    """NASDAQ 상장 종목 다운로드"""
    ftp = ftplib.FTP("ftp.nasdaqtrader.com")
    ftp.login()  # Anonymous login
    ftp.cwd("SymbolDirectory")
    
    r = io.BytesIO()
    ftp.retrbinary("RETR nasdaqlisted.txt", r.write)
    ftp.quit()
    r.seek(0)
    
    df = pd.read_csv(r, sep='|')
    df = df[df['Test Issue'] == 'N']  # 테스트 종목 제외
    return df[['Symbol', 'Security Name', 'Market Category', 'Financial Status']]

def download_other_listed() -> pd.DataFrame:
    """NYSE, AMEX 등 기타 거래소 종목 다운로드"""
    ftp = ftplib.FTP("ftp.nasdaqtrader.com")
    ftp.login()
    ftp.cwd("SymbolDirectory")
    
    r = io.BytesIO()
    ftp.retrbinary("RETR otherlisted.txt", r.write)
    ftp.quit()
    r.seek(0)
    
    df = pd.read_csv(r, sep='|')
    df = df[df['Test Issue'] == 'N']
    return df[['ACT Symbol', 'Security Name', 'Exchange']]

# 사용 예시
nasdaq_df = download_nasdaq_listed()
other_df = download_other_listed()

# NYSE만 필터링
nyse_df = other_df[other_df['Exchange'] == 'N']

# 전체 티커 리스트
all_tickers = list(nasdaq_df['Symbol']) + list(other_df['ACT Symbol'])
print(f"Total: {len(all_tickers)} tickers")
```

### 3.3 방법 3: pandas_datareader (NASDAQ만)

```python
from pandas_datareader.nasdaq_trader import get_nasdaq_symbols

nasdaq_symbols = get_nasdaq_symbols()
# Index: Symbol, Columns: Security Name, Market Category, etc.

tickers = nasdaq_symbols.index.tolist()
print(f"NASDAQ tickers: {len(tickers)}")
```

---

## 4. yfinance 제약사항 & Workarounds

### 4.1 Rate Limiting

**실제 제한:**
- **~2000-2500 requests/hour/IP** (비공식, 경험적 수치)
- **너무 빠른 연속 요청** → HTTP 429/403/999 에러
- **1분 데이터는 최대 7일치만** 제공

**대응책:**
```python
# 1. 배치 크기 제한
BATCH_SIZE = 100  # 한 번에 100개 종목만

# 2. 딜레이 설정
DELAY_BETWEEN_REQUESTS = 0.5  # 0.5초 대기
DELAY_BETWEEN_BATCHES = 2.0   # 배치 간 2초 대기

# 3. Exponential Backoff
for retry in range(max_retries):
    try:
        data = yf.download(...)
        break
    except HTTPError as e:
        if e.status_code == 429:
            time.sleep(2 ** retry)  # 1s, 2s, 4s, 8s...
```

### 4.2 데이터 누락/불일치

**흔한 케이스:**
```python
# 1. info dict가 비어있거나 불완전
ticker = yf.Ticker("INVALID")
print(ticker.info)  # {} 또는 minimal data

# 2. quarterly_earnings가 None
ticker = yf.Ticker("NEWIPO")
print(ticker.quarterly_earnings)  # None

# 3. 재무제표 컬럼명 불일치 (회사마다 다름)
# 해결: 표준화된 키로 접근
income_stmt = ticker.quarterly_income_stmt
if 'Total Revenue' in income_stmt.index:
    revenue = income_stmt.loc['Total Revenue']
elif 'TotalRevenue' in income_stmt.index:
    revenue = income_stmt.loc['TotalRevenue']
```

**Workaround:**
```python
def safe_get_info(ticker: yf.Ticker, key: str, default=None):
    """안전한 info 접근"""
    try:
        value = ticker.info.get(key, default)
        # Check for common invalid values
        if value in [None, 'None', '', 'N/A', 0]:
            return default
        return value
    except:
        return default

# 사용
eps = safe_get_info(ticker, 'trailingEps', default=0.0)
```

### 4.3 Quarterly vs Annual 데이터

```python
ticker = yf.Ticker("AAPL")

# Quarterly (분기별) - CANSLIM에 필수
ticker.quarterly_income_stmt      # 최근 4분기 데이터
ticker.quarterly_balance_sheet
ticker.quarterly_cashflow
ticker.quarterly_earnings         # Revenue, Earnings 컬럼만

# Annual (연간)
ticker.income_stmt                # 최근 3-4년 데이터
ticker.balance_sheet
ticker.cashflow

# 주의: quarterly_earnings vs quarterly_income_stmt
# - quarterly_earnings: 간단한 2개 컬럼 (Revenue, Earnings)
# - quarterly_income_stmt: 전체 손익계산서 (50+ rows)
```

### 4.4 Multi-Index DataFrame 처리

```python
# yf.download()는 MultiIndex 반환
data = yf.download(['AAPL', 'MSFT'], period='5d')

# Level 0: OHLCV columns
# Level 1: Ticker symbols

# 단일 종목 추출
aapl = data.xs('AAPL', level=1, axis=1)

# 또는 flatten
data.columns = ['_'.join(col).strip() for col in data.columns.values]
```

### 4.5 알려진 버그 & 대응

```python
# 1. Timezone 이슈 (ignore_tz 옵션)
data = yf.download('AAPL', period='5d', ignore_tz=True)

# 2. Auto-adjust 옵션 (권장: True)
data = yf.download('AAPL', period='1y', auto_adjust=True)

# 3. Prepost (시간외 거래 데이터)
data = ticker.history(period='1d', prepost=True)

# 4. Actions (배당/분할 이벤트)
actions = ticker.actions  # Dividends, Stock Splits
```

---

## 5. Production 코드 예시

### 5.1 초기 데이터 로드 스크립트

```python
#!/usr/bin/env python3
"""
scripts/initial_data_load.py
8000종목의 초기 데이터 수집
"""
import yfinance as yf
import pandas as pd
import pickle
import time
from pathlib import Path
from get_all_tickers import get_tickers
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = Path("data/cache")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def main():
    # 1. 종목 리스트 가져오기
    logger.info("Fetching ticker list...")
    tickers = get_tickers(NYSE=True, NASDAQ=True)
    logger.info(f"Found {len(tickers)} tickers")
    
    # 2. 가격 데이터 벌크 다운로드 (300일)
    logger.info("Downloading price data (300 days)...")
    price_data = download_price_data_bulk(
        tickers=tickers,
        period="300d",
        batch_size=100,
        delay_between_batches=2.0
    )
    price_data.to_pickle(DATA_DIR / "price_data_300d.pkl")
    logger.info(f"Saved price data: {price_data.shape}")
    
    # 3. 재무 데이터 수집 (시간 소요 큼)
    logger.info("Downloading fundamental data...")
    logger.info("WARNING: This will take ~1-2 hours for 8000 tickers")
    
    fundamental_data = download_fundamental_data_bulk(
        tickers=tickers,
        delay_per_ticker=0.5
    )
    
    with open(DATA_DIR / "fundamental_data.pkl", "wb") as f:
        pickle.dump(fundamental_data, f)
    logger.info(f"Saved fundamental data for {len(fundamental_data)} tickers")
    
    # 4. 실패한 티커 로깅
    failed = set(tickers) - set(fundamental_data.keys())
    if failed:
        with open(DATA_DIR / "failed_tickers.txt", "w") as f:
            f.write("\n".join(sorted(failed)))
        logger.warning(f"Failed to fetch {len(failed)} tickers (see failed_tickers.txt)")
    
    logger.info("Initial data load completed!")

if __name__ == "__main__":
    main()
```

### 5.2 증분 업데이트 스크립트

```python
#!/usr/bin/env python3
"""
scripts/update_data.py
매일 실행 - 기존 데이터 업데이트
"""
import yfinance as yf
import pandas as pd
import pickle
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path("data/cache")

def update_price_data():
    """최근 2일치 가격 데이터만 업데이트"""
    # 기존 데이터 로드
    df = pd.read_pickle(DATA_DIR / "price_data_300d.pkl")
    tickers = df.columns.get_level_values(1).unique().tolist()
    
    # 최근 2일치만 다운로드
    new_data = yf.download(
        tickers=tickers,
        period="2d",
        threads=True,
        progress=False
    )
    
    # 기존 데이터와 병합
    df = pd.concat([df, new_data]).drop_duplicates()
    df = df.sort_index()
    
    # 300일 이전 데이터 제거
    cutoff_date = datetime.now() - timedelta(days=300)
    df = df[df.index >= cutoff_date]
    
    # 저장
    df.to_pickle(DATA_DIR / "price_data_300d.pkl")
    print(f"Updated price data: {df.shape}")

if __name__ == "__main__":
    update_price_data()
```

---

## 6. 성능 최적화 팁

```python
# 1. 필요한 데이터만 수집
ticker = yf.Ticker("AAPL")
info = ticker.info  # 한 번만 호출하고 캐시

# 2. fast_info 사용 (경량화된 데이터)
ticker.fast_info['lastPrice']
ticker.fast_info['marketCap']
ticker.fast_info['yearHigh']
ticker.fast_info['yearLow']

# 3. 세션 재사용
import requests
session = requests.Session()
ticker = yf.Ticker("AAPL", session=session)

# 4. 멀티스레딩 활성화
data = yf.download(tickers, period="1y", threads=True)

# 5. 로컬 캐싱
import pickle
cache = {}
if Path("cache.pkl").exists():
    with open("cache.pkl", "rb") as f:
        cache = pickle.load(f)
```

---

## 7. 종합 체크리스트

**8000종목 수집 시나리오:**

- [ ] 종목 리스트: NASDAQ FTP 또는 get-all-tickers
- [ ] 가격 데이터: `yf.download()` 배치 처리 (100종목씩, 2초 간격)
- [ ] 재무 데이터: 개별 Ticker 순회 (0.5초 간격, ~1-2시간 소요)
- [ ] 에러 처리: `try-except` + exponential backoff
- [ ] Rate limiting: 배치 크기 제한, 딜레이 설정
- [ ] 실패 추적: `yfinance.shared._ERRORS` 또는 로깅
- [ ] 데이터 검증: `info` dict 크기, DataFrame 비어있는지 체크
- [ ] 캐싱: Pickle로 저장, 증분 업데이트
- [ ] 스케줄링: 매일 오전 시장 전 실행 (cron/Task Scheduler)

**예상 소요 시간:**
- 가격 데이터 (8000종목, 300일): ~30분
- 재무 데이터 (8000종목): ~1-2시간
- **총 초기 로드: 2-3시간**
- 일일 업데이트: ~5분

**Rate Limit 안전 수치:**
- 배치 크기: 100종목
- 배치 간 딜레이: 2초
- 개별 요청 딜레이: 0.5초
- **시간당 요청 수: ~1500-2000 (안전권)**
