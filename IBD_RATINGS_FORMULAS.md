# IBD 독점 평가 지표: 정밀 수학 공식

> **출처**: IBD 방법론 역공학, William J. O'Neil 저 "How to Make Money in Stocks", 커뮤니티 구현 사례, 공식 IBD 문서 기반
> 
> **목적**: CANSLIM 트레이딩 봇 스코어링 함수 구현 가이드
> 
> **최종 업데이트**: 2026-02-14

---

## 목차
1. [RS Rating (상대 강도 등급)](#1-rs-rating-상대-강도-등급)
2. [RS Line (상대 강도선)](#2-rs-line-상대-강도선)
3. [EPS Rating (주당순이익 등급)](#3-eps-rating-주당순이익-등급)
4. [Composite Rating (종합 등급)](#4-composite-rating-종합-등급)
5. [SMR Rating (매출+마진+ROE 등급)](#5-smr-rating-매출마진roe-등급)
6. [Accumulation/Distribution Rating (수급 등급)](#6-accumulationdistribution-rating-수급-등급)
7. [Python 구현 예제](#7-python-구현-예제)

---

## 1. RS Rating (상대 강도 등급)

### 개요
RS Rating은 과거 12개월간 해당 종목의 주가 성과를 시장 내 모든 다른 종목과 비교하여 측정한 지표이다. 척도: **1-99** (99 = 전체 종목의 99%를 상회한 성과).

### 1단계: 원시 상대 강도 점수 계산

**공식 (가장 일반적인 구현):**
```
Raw RS Score = (2 × (Close / Close_63_days_ago)) 
               + (Close / Close_126_days_ago)
               + (Close / Close_189_days_ago)
               + (Close / Close_252_days_ago)
```

**대안 공식 (백분율 기반, 명시적 가중치):**
```
Raw RS Score = 0.4 × ((Close - Close_63) / Close_63) × 100
             + 0.2 × ((Close - Close_126) / Close_126) × 100
             + 0.2 × ((Close - Close_189) / Close_189) × 100
             + 0.2 × ((Close - Close_252) / Close_252) × 100
```

**기간 및 가중치:**
| 기간 | 거래일 수 | 가중치 | 근거 |
|------|----------|--------|------|
| 3개월 | ~63일 | **40% (2배 가중)** | 가장 최근 성과가 가장 중요 |
| 6개월 | ~126일 | 20% | 최근 추세 확인 |
| 9개월 | ~189일 | 20% | 중기 일관성 |
| 12개월 | ~252일 | 20% | 장기 강도 |

**참고**: 가장 최근 분기(63일)는 다른 기간(각 20%)에 비해 2배(40%) 가중된다.

### 2단계: 백분위 순위 변환 (1-99)

**알고리즘:**
1. 유니버스 내 모든 종목에 대해 원시 RS 점수를 계산한다
2. 모든 종목을 원시 RS 점수 기준으로 정렬한다 (내림차순)
3. 정렬된 배열에서의 위치를 기반으로 백분위 순위를 부여한다
4. 1-99 척도로 매핑한다 (0-100이 아님)

**Python 구현 (scipy 사용):**
```python
from scipy import stats

def calculate_rs_rating(stock_raw_rs_score, all_universe_raw_rs_scores):
    """
    원시 RS 점수를 IBD 방식의 1-99 백분위 등급으로 변환
    """
    # 'weak' 방식 사용: 주어진 점수 이하인 값의 백분율
    percentile = stats.percentileofscore(
        all_universe_raw_rs_scores, 
        stock_raw_rs_score, 
        kind='weak'
    )
    
    # 0-100 백분위를 1-99 등급으로 변환
    rs_rating = int(round(percentile))
    rs_rating = max(1, min(99, rs_rating))
    
    return rs_rating
```

### 주요 구현 참고 사항:
- **비교 유니버스**: IBD 데이터베이스 내 모든 종목 (일반적으로 NYSE, NASDAQ, AMEX)
- S&P 500 대비가 **아님** -- 모든 개별 종목 대비 비교
- RS Rating 80 이상인 종목은 강한 성과를 보이는 종목으로 간주
- 최상위 시장 선도주는 일반적으로 RS Rating 90 이상
- 63일 기간은 더 긴 기간 계산에도 포함되기 때문에 "실질적으로 2배 가중"된 효과를 가짐

---

## 2. RS Line (상대 강도선)

### 개요
RS Line은 벤치마크 지수(일반적으로 S&P 500) 대비 종목의 성과를 보여주는 **연속적인 차트선**이다. RS Rating과 달리 1-99 점수가 아니라 시간에 따라 차트로 표시할 수 있는 비율값이다.

### 공식

```
RS Line = Stock Price / S&P 500 Index Value
```

**예시:**
- 주가: $150
- S&P 500 (SPY): $450
- RS Line = 150 / 450 = 0.333

### 해석

| RS Line 추세 | 의미 |
|-------------|------|
| **상승 기울기** | 종목이 S&P 500을 상회하는 성과 |
| **하락 기울기** | 종목이 S&P 500을 하회하는 성과 |
| **신고가** | 종목이 탁월한 상대 강도를 보임 |
| **횡보** | 종목이 시장과 동일한 움직임 |

### "RS Line이 주가보다 먼저 신고가를 기록하는 경우" 감지

**이것은 IBD 방법론에서 강력한 매수 신호이다.**

**알고리즘:**
```python
def detect_rs_line_new_high_signal(stock_data, sp500_data, lookback_period=252):
    """
    RS Line이 신고가를 기록하면서 주가는 아직 신고가에 도달하지 않은 경우를 감지
    이 패턴은 종종 주요 가격 돌파에 선행한다
    """
    # 각 거래일의 RS Line 계산
    rs_line = stock_data['Close'] / sp500_data['Close']
    
    # 조회 기간 내 RS Line 최고값 찾기
    rs_line_max = rs_line.rolling(window=lookback_period).max()
    
    # 조회 기간 내 주가 최고값 찾기
    price_max = stock_data['Close'].rolling(window=lookback_period).max()
    
    # 신호: RS Line이 신고가이지만 주가는 신고가가 아닌 경우
    rs_at_new_high = rs_line >= rs_line_max * 0.99  # 최고값의 1% 이내
    price_not_at_new_high = stock_data['Close'] < price_max * 0.95  # 최고값 대비 5% 이상 하락

    buy_signal = rs_at_new_high & price_not_at_new_high
    
    return buy_signal
```

**시각적 확인:**
- RS Line과 주가를 별도의 차트에 표시
- RS Line이 상승 추세이며 새로운 고점을 형성해야 함
- RS Line이 주가 돌파 전에 신고가를 기록하면 = 강세 다이버전스

---

## 3. EPS Rating (주당순이익 등급)

### 개요
EPS Rating은 기업의 수익 성과(최근 분기 실적 및 장기 연간 성장률 모두)를 모든 상장 기업과 비교하여 측정한 지표이다. 척도: **1-99** (99 = 최고 수익 성과).

### 구성 요소

**IBD가 공식적으로 명시한 구성 요소이며, 정확한 가중치는 독점 정보이다:**

| 구성 요소 | 가중치 | 설명 |
|----------|--------|------|
| **최근 2분기 EPS 성장률** | ~50-60% (추정) | 전년 동기 대비 변화율 |
| **3-5년 연간 EPS 성장률** | ~30-40% (추정) | 장기 수익 추세 |
| **연간 수익 성장의 안정성** | ~10-20% (추정) | 성장의 일관성 (변동성이 낮을수록 우수) |

### 근사 공식 (역공학 기반)

**1단계: 분기 EPS 성장률 계산**
```python
# 가장 최근 분기 vs 전년 동기
Q1_growth = (Q1_current_year - Q1_last_year) / abs(Q1_last_year) * 100

# 두 번째 최근 분기 vs 전년 동기
Q2_growth = (Q2_current_year - Q2_last_year) / abs(Q2_last_year) * 100

# 최근 분기 평균 성장률
avg_quarterly_growth = (Q1_growth + Q2_growth) / 2
```

**2단계: 3-5년 연간 EPS 성장률(CAGR) 계산**
```python
annual_eps_cagr = ((EPS_current_year / EPS_5_years_ago) ** (1/5) - 1) * 100
```

**3단계: 안정성 계산 (변동계수)**
```python
import numpy as np

# 최근 5년간 연간 EPS 사용
eps_values = [year1_eps, year2_eps, year3_eps, year4_eps, year5_eps]
std_dev = np.std(eps_values)
mean_eps = np.mean(eps_values)

# 안정성 점수 (낮을수록 안정적 = 우수)
stability_score = (std_dev / mean_eps) * 100  # 변동계수
```

**4단계: 구성 요소 결합 (추정 가중치)**
```python
# 먼저 모든 구성 요소를 0-100 척도로 정규화
# 그런 다음 추정 가중치로 결합:
raw_eps_score = (0.55 * normalized_quarterly_growth 
               + 0.35 * normalized_annual_cagr
               - 0.10 * normalized_stability_score)  # 참고: 안정성은 차감
```

**5단계: 백분위 변환 (1-99)**
- RS Rating과 동일한 과정
- 모든 종목에 대해 raw_eps_score를 계산
- 순위를 매기고 1-99 백분위를 부여

### 중요 참고 사항:
- **정규화된 EPS**: IBD는 "프로포마(pro forma)" 수익을 사용한다 (일회성 비용, 특별 항목 제거)
- **비교 유니버스**: 모든 거래소의 모든 상장 기업
- **업종 무관**: 기술주도 유틸리티, 금융 등과 비교됨
- CANSLIM 방법론에서는 EPS Rating 80 이상이 선호됨

### IBD 연구에서 확인된 임계값:
- 돌파 전 최고 성과 종목: 평균 EPS Rating = **86**
- 최소 권장치: **80**
- 최우수 종목: **90+**

---

## 4. Composite Rating (종합 등급)

### 개요
Composite Rating은 여러 IBD 등급을 하나의 1-99 점수로 결합하여 종목의 전반적인 강도를 평가한다.

### 구성 요소

**IBD 공식 입장:**
> "EPS와 RS Rating에 더 높은 가중치가 부여된다"

| 구성 요소 | 추정 가중치 |
|----------|------------|
| **EPS Rating** | ~30-35% |
| **RS Rating** | ~30-35% |
| **SMR Rating** | ~15-20% |
| **Accumulation/Distribution Rating (수급 등급)** | ~10-15% |
| **주가 움직임 (52주 최고가 대비 %)** | ~5-10% |

### 근사 공식 (역공학 기반)

```python
def calculate_composite_rating(eps_rating, rs_rating, smr_grade, 
                               acc_dist_grade, price, high_52week):
    """
    IBD Composite Rating 근사 계산
    """
    # 문자 등급을 숫자로 변환 (A=100, B=80, C=60, D=40, E=20)
    smr_score = {'A': 100, 'B': 80, 'C': 60, 'D': 40, 'E': 20}[smr_grade]
    acc_dist_score = {'A': 100, 'B': 80, 'C': 60, 'D': 40, 'E': 20}[acc_dist_grade]
    
    # 52주 최고가 대비 하락률 계산 (최고가에 가까울수록 우수)
    pct_off_high = ((high_52week - price) / high_52week) * 100
    price_action_score = max(0, 100 - pct_off_high)  # 반전하여 높을수록 우수하게
    
    # 가중 결합
    raw_composite = (0.33 * eps_rating +
                     0.33 * rs_rating +
                     0.17 * smr_score +
                     0.12 * acc_dist_score +
                     0.05 * price_action_score)
    
    # 모든 종목 대비 백분위 순위를 통해 1-99 척도로 변환
    # (RS Rating과 동일한 과정)
    composite_rating = convert_to_percentile(raw_composite, all_stocks_raw_scores)
    
    return int(max(1, min(99, composite_rating)))
```

### 주가 움직임 구성 요소: "52주 최고가 대비 하락률"

**공식:**
```
52주 최고가 대비 하락률 = ((52주 최고가 - 현재가) / 52주 최고가) x 100
```

**예시:**
- 52주 최고가: $100
- 현재가: $92
- 하락률 = ((100 - 92) / 100) x 100 = **8%**

**이상적 범위**: 52주 최고가 대비 **0-15%** 이내의 종목이 선호됨

---

## 5. SMR Rating (매출+마진+ROE 등급)

### 개요
SMR Rating은 기본적인 매출 및 수익성 지표를 평가한다. 척도: **A, B, C, D, E** (A = 최우수).

### 구성 요소

| 구성 요소 | 데이터 출처 | 설명 |
|----------|-----------|------|
| **매출 성장률** | 최근 3분기 | 분기별 매출 성장 |
| **세전 이익률** | 연간 | 영업이익률 추세 |
| **세후 이익률** | 분기 | 순이익률 추세 |
| **자기자본이익률 (ROE)** | 연간 | 자기자본 활용 효율성 |

**모든 요소에 "가속도" 분석이 포함됨 (증가 속도가 중요)**

### 등급 기준

| 등급 | 백분위 | 의미 |
|------|--------|------|
| **A** | 상위 20% | 전체 종목의 80% 이상 상회 |
| **B** | 다음 20% | 전체 종목의 60-80% 상회 |
| **C** | 중간 20% | 전체 종목의 40-60% 상회 |
| **D** | 다음 20% | 전체 종목의 20-40% 상회 |
| **E** | 하위 20% | 전체 종목의 80% 이상에 의해 상회됨 |

### 계산 알고리즘

**1단계: 각 구성 요소의 원시 점수 계산**

```python
# 1. 매출 성장률 (최근 3분기 평균)
q1_sales_growth = (Q1_sales_current - Q1_sales_lastyear) / Q1_sales_lastyear * 100
q2_sales_growth = (Q2_sales_current - Q2_sales_lastyear) / Q2_sales_lastyear * 100
q3_sales_growth = (Q3_sales_current - Q3_sales_lastyear) / Q3_sales_lastyear * 100
avg_sales_growth = (q1_sales_growth + q2_sales_growth + q3_sales_growth) / 3

# 2. 세전 이익률 (연간, 최근 연도)
pretax_margin = (operating_income / revenue) * 100

# 3. 세후 이익률 (분기, 가장 최근)
aftertax_margin = (net_income / revenue) * 100

# 4. 자기자본이익률 (연간)
roe = (net_income / shareholders_equity) * 100
```

**2단계: 가속도 확인 (가산점)**
```python
# 매출 가속도
sales_accelerating = q3_sales_growth > q2_sales_growth > q1_sales_growth

# 이익률 개선
margin_improving = current_margin > prior_quarter_margin

# ROE 개선
roe_improving = current_roe > prior_year_roe
```

**3단계: 단일 점수로 결합**
```python
# 동일 가중치 (추정)
raw_smr_score = (0.25 * sales_growth_percentile +
                 0.25 * pretax_margin_percentile +
                 0.25 * aftertax_margin_percentile +
                 0.25 * roe_percentile)

# 가속도에 대한 가산점 (5-10점 추가)
if sales_accelerating or margin_improving or roe_improving:
    raw_smr_score += 5
```

**4단계: 문자 등급 부여**
```python
def assign_smr_grade(raw_smr_score, all_scores):
    percentile = calculate_percentile(raw_smr_score, all_scores)
    
    if percentile >= 80:
        return 'A'
    elif percentile >= 60:
        return 'B'
    elif percentile >= 40:
        return 'C'
    elif percentile >= 20:
        return 'D'
    else:
        return 'E'
```

### IBD 권장 임계값

| 지표 | 최소치 | 이상적 수준 |
|------|--------|-----------|
| **분기 매출 성장률** | +25% | 가속도와 함께 +50% 이상 |
| **세후 이익률** | 개선 추세 | 업종 내 최고 수준 근접 |
| **ROE** | +17% | +20-30% 또는 그 이상 |
| **SMR 등급** | B 이상 | A |

---

## 6. Accumulation/Distribution Rating (수급 등급)

### 개요
Accumulation/Distribution (매집/분산) 등급은 기관 투자자의 매수 대 매도 압력을 측정한다. 척도: **A, B, C, D, E** (A = 강한 매집, E = 강한 분산).

### 산정 기간
**13주 (65 거래일)** 조회 기간

### 핵심 개념
- **매집 (A/B)**: 주가 상승 + 거래량 증가 = 기관 매수 중
- **분산 (D/E)**: 주가 하락 + 거래량 증가 = 기관 매도 중
- **중립 (C)**: 매수와 매도가 대략 동등

### 계산 방법

**1단계: 일일 자금 흐름 승수**
```python
def calculate_money_flow_multiplier(high, low, close):
    """
    당일 거래 범위 내에서 매수 vs 매도 압력을 결정
    +1 = 종가가 고가에 위치 (강세)
    -1 = 종가가 저가에 위치 (약세)
    0 = 종가가 중간점에 위치 (중립)
    """
    if high == low:  # 0으로 나누기 방지
        return 0
    
    mf_multiplier = ((close - low) - (high - close)) / (high - low)
    return mf_multiplier  # 범위: -1 ~ +1
```

**2단계: 일일 자금 흐름 거래량**
```python
money_flow_volume = mf_multiplier * volume
```

**3단계: 누적 자금 흐름 (13주)**
```python
import pandas as pd

def calculate_accumulation_distribution(df, period=65):
    """
    13주 이동 기간에 대한 누적 매집/분산 계산
    """
    # 각 거래일의 자금 흐름 승수 계산
    df['MF_Multiplier'] = ((df['Close'] - df['Low']) - 
                           (df['High'] - df['Close'])) / (df['High'] - df['Low'])
    
    # 자금 흐름 거래량 계산
    df['MF_Volume'] = df['MF_Multiplier'] * df['Volume']
    
    # 기간에 걸친 누적 합계
    df['Acc_Dist'] = df['MF_Volume'].rolling(window=period).sum()
    
    return df['Acc_Dist']
```

**4단계: IBD 조정**

IBD는 독점적인 조정을 적용한다:
1. **종목의 거래 범위로 정규화**: 변동성 조정
2. **거래량 급등 제거**: 비정상적 이벤트 필터링 (IPO, 유상증자, 자사주 매입 등)
3. **데이터 평활화**: 이동평균으로 잡음 감소

**근사 정규화 점수:**
```python
def normalize_acc_dist(acc_dist_value, price_range, avg_volume):
    """
    종목 간 비교가 가능하도록 매집/분산 정규화
    """
    # 종목의 일반적인 가격 범위로 조정
    range_factor = price_range / 100  # 백분율로 스케일링
    
    # 종목의 일반적인 거래량으로 조정
    volume_factor = avg_volume / 1000000  # 백만 단위로 스케일링
    
    normalized_score = acc_dist_value / (range_factor * volume_factor)
    
    return normalized_score
```

**5단계: 문자 등급 부여**

등급은 시장 내 모든 종목 대비 상대적으로 부여된다:

```python
def assign_acc_dist_grade(normalized_score, all_scores):
    percentile = calculate_percentile(normalized_score, all_scores)
    
    if percentile >= 80:
        return 'A'  # 강한 매집
    elif percentile >= 60:
        return 'B'  # 보통 매집
    elif percentile >= 40:
        return 'C'  # 중립
    elif percentile >= 20:
        return 'D'  # 보통 분산
    else:
        return 'E'  # 강한 분산
```

### 등급 기준 해석

| 등급 | 백분위 | 거래량 패턴 | 기관 활동 |
|------|--------|-----------|----------|
| **A** | 상위 20% | 상승일에 대규모 거래량 | 강한 매수 |
| **A-** | 75-80% | 상승일에 양호한 거래량 | 매집 |
| **B+** | 70-75% | 평균 이상 매집 | 보통 매수 |
| **B** | 60-70% | 소폭 매집 | 일부 매수 |
| **B-** | 55-60% | 미미한 매집 | 약한 매수 |
| **C+** | 50-55% | 균형 | 중립 |
| **C** | 40-50% | 균형 | 중립 |
| **C-** | 35-40% | 소폭 분산 | 약한 매도 |
| **D+** | 30-35% | 미미한 분산 | 일부 매도 |
| **D** | 20-30% | 평균 이상 분산 | 보통 매도 |
| **D-** | 15-20% | 대규모 분산 | 매도 압력 |
| **E** | 하위 20% | 하락일에 대규모 거래량 | 강한 매도 |

### 구현 참고 사항

**거래량 급등 필터링:**
```python
def filter_unusual_volume_spikes(df, threshold=3.0):
    """
    거래량이 평균 거래량의 threshold배를 초과하는 거래일 제거
    IPO, 유상증자 등일 수 있음
    """
    avg_volume = df['Volume'].rolling(window=50).mean()
    volume_ratio = df['Volume'] / avg_volume
    
    # 극단적 급등 제한
    df.loc[volume_ratio > threshold, 'Volume'] = avg_volume * threshold
    
    return df
```

**당일 거래 범위 조정:**
```python
# IBD는 범위 대비 변동률을 기반으로 일일 A/D 등급을 조정한다
if close > open:  # 상승일
    price_change_pct = (close - open) / (high - low) * 100
else:  # 하락일
    price_change_pct = (open - close) / (high - low) * -100
```

---

## 7. Python 구현 예제

### 완전한 RS Rating 계산기

```python
import pandas as pd
import numpy as np
from scipy import stats
import yfinance as yf

def calculate_ibd_rs_rating(ticker, universe_tickers, period='1y'):
    """
    종목에 대한 IBD 방식 RS Rating 계산
    
    매개변수:
        ticker: 평가할 종목 티커
        universe_tickers: 비교 대상이 되는 모든 티커 목록
        period: 데이터 기간 (기본값: 1년)
    
    반환값:
        RS Rating (1-99)
    """
    # 1단계: 대상 종목의 데이터 다운로드
    stock = yf.download(ticker, period=period, progress=False)
    
    if len(stock) < 252:
        return None  # 데이터 부족
    
    # 주요 구간별 가격 추출
    current_price = stock['Close'].iloc[-1]
    price_63d = stock['Close'].iloc[-63] if len(stock) >= 63 else stock['Close'].iloc[0]
    price_126d = stock['Close'].iloc[-126] if len(stock) >= 126 else stock['Close'].iloc[0]
    price_189d = stock['Close'].iloc[-189] if len(stock) >= 189 else stock['Close'].iloc[0]
    price_252d = stock['Close'].iloc[-252] if len(stock) >= 252 else stock['Close'].iloc[0]
    
    # 원시 RS 점수 계산 (가중 방식)
    raw_rs = (0.4 * ((current_price - price_63d) / price_63d) * 100 +
              0.2 * ((current_price - price_126d) / price_126d) * 100 +
              0.2 * ((current_price - price_189d) / price_189d) * 100 +
              0.2 * ((current_price - price_252d) / price_252d) * 100)
    
    # 2단계: 유니버스 내 모든 종목의 원시 RS 계산
    universe_scores = []
    for uni_ticker in universe_tickers:
        try:
            uni_stock = yf.download(uni_ticker, period=period, progress=False)
            if len(uni_stock) < 252:
                continue
                
            uni_current = uni_stock['Close'].iloc[-1]
            uni_63d = uni_stock['Close'].iloc[-63]
            uni_126d = uni_stock['Close'].iloc[-126]
            uni_189d = uni_stock['Close'].iloc[-189]
            uni_252d = uni_stock['Close'].iloc[-252]
            
            uni_raw_rs = (0.4 * ((uni_current - uni_63d) / uni_63d) * 100 +
                         0.2 * ((uni_current - uni_126d) / uni_126d) * 100 +
                         0.2 * ((uni_current - uni_189d) / uni_189d) * 100 +
                         0.2 * ((uni_current - uni_252d) / uni_252d) * 100)
            
            universe_scores.append(uni_raw_rs)
        except:
            continue
    
    # 3단계: 백분위로 변환 (1-99)
    percentile = stats.percentileofscore(universe_scores, raw_rs, kind='weak')
    rs_rating = int(round(percentile))
    rs_rating = max(1, min(99, rs_rating))
    
    return rs_rating


# 사용 예시
sp500_tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', ...]  # 전체 S&P 500 종목 목록
apple_rs_rating = calculate_ibd_rs_rating('AAPL', sp500_tickers)
print(f"AAPL RS Rating: {apple_rs_rating}")
```

### RS Line 신고가 감지

```python
def calculate_rs_line_with_signals(stock_ticker, benchmark='SPY', period='1y'):
    """
    RS Line 계산 및 신고가 신호 감지
    """
    # 데이터 다운로드
    stock = yf.download(stock_ticker, period=period, progress=False)
    benchmark = yf.download(benchmark, period=period, progress=False)
    
    # RS Line 계산
    rs_line = stock['Close'] / benchmark['Close']
    
    # RS Line의 신고가 감지
    rs_line_max = rs_line.rolling(window=252).max()
    rs_at_new_high = rs_line >= rs_line_max * 0.99
    
    # 주가가 신고가가 아닌지 확인
    price_max = stock['Close'].rolling(window=252).max()
    price_not_at_high = stock['Close'] < price_max * 0.95
    
    # 매수 신호: RS Line은 신고가이지만 주가는 뒤처지는 경우
    buy_signal = rs_at_new_high & price_not_at_high
    
    # 결과 DataFrame 생성
    result = pd.DataFrame({
        'Close': stock['Close'],
        'RS_Line': rs_line,
        'RS_Line_Max': rs_line_max,
        'RS_New_High': rs_at_new_high,
        'Buy_Signal': buy_signal
    })
    
    return result
```

### 매집/분산 등급 계산기

```python
def calculate_acc_dist_rating(ticker, period_days=65):
    """
    IBD 방식 매집/분산 등급 계산
    """
    # 데이터 다운로드
    df = yf.download(ticker, period='6mo', progress=False)
    
    # 1단계: 자금 흐름 승수
    df['MF_Multiplier'] = ((df['Close'] - df['Low']) - 
                           (df['High'] - df['Close'])) / (df['High'] - df['Low'])
    df['MF_Multiplier'].fillna(0, inplace=True)
    
    # 2단계: 자금 흐름 거래량
    df['MF_Volume'] = df['MF_Multiplier'] * df['Volume']
    
    # 3단계: 누적 매집/분산
    df['Acc_Dist'] = df['MF_Volume'].rolling(window=period_days).sum()
    
    # 4단계: 정규화
    avg_volume = df['Volume'].mean()
    price_range = df['High'].rolling(window=period_days).max() - df['Low'].rolling(window=period_days).min()
    df['Normalized_AD'] = df['Acc_Dist'] / (price_range * avg_volume)
    
    # 최신 값 추출
    latest_ad = df['Normalized_AD'].iloc[-1]
    
    return latest_ad

# 등급 부여 (유니버스 대비 비교 필요)
def assign_ad_grade(ad_value, universe_ad_values):
    percentile = stats.percentileofscore(universe_ad_values, ad_value, kind='weak')
    
    if percentile >= 80:
        return 'A'
    elif percentile >= 60:
        return 'B'
    elif percentile >= 40:
        return 'C'
    elif percentile >= 20:
        return 'D'
    else:
        return 'E'
```

---

## 구현 체크리스트

### RS Rating:
- [ ] 대상 종목의 252일 이상 가격 데이터 수집
- [ ] 비교 유니버스 내 모든 종목의 동일 데이터 수집 (S&P 500, Russell 2000 등)
- [ ] 가중 가격 성과 계산 (40/20/20/20 공식)
- [ ] 모든 종목을 원시 RS 점수 기준으로 순위 매기기
- [ ] 1-99 백분위 순위 부여
- [ ] RS Rating 80 이상 필터링 (이상적으로 90 이상)

### RS Line:
- [ ] 종목 및 S&P 500 데이터 다운로드
- [ ] 일일 비율 계산: 종목가 / SPY
- [ ] 주가 차트와 함께 RS Line 표시
- [ ] RS Line의 52주 신고가 감지
- [ ] 주가가 RS Line보다 뒤처지는지 확인 = 매수 신호

### EPS Rating:
- [ ] 최근 8분기 분기 EPS 수집
- [ ] 최근 5년 연간 EPS 수집
- [ ] 전년 동기 대비 분기별 성장률 계산
- [ ] 5년 EPS CAGR 계산
- [ ] 안정성 계산 (변동계수)
- [ ] 추정 가중치로 결합
- [ ] 모든 종목 대비 1-99 순위 매기기

### SMR Rating:
- [ ] 최근 3분기 매출 데이터 수집
- [ ] 연간 이익률 (세전 및 세후) 수집
- [ ] 연간 ROE 수집
- [ ] 각 지표의 가속도 확인
- [ ] 각 구성 요소를 유니버스 대비 순위 매기기
- [ ] 결합하여 A-E 등급 부여
- [ ] 목표: A 또는 B 등급

### 매집/분산 등급:
- [ ] 6개월간의 OHLCV 데이터 다운로드
- [ ] 일일 자금 흐름 승수 계산
- [ ] 자금 흐름 거래량 계산
- [ ] 13주 이동 구간에 대해 합산
- [ ] 가격 범위 및 거래량으로 정규화
- [ ] 유니버스 대비 순위 매기기
- [ ] A-E 등급 부여
- [ ] 목표: A 또는 B 등급

### Composite Rating:
- [ ] 위의 모든 개별 등급 계산
- [ ] 문자 등급을 숫자로 변환 (A=100, B=80 등)
- [ ] 52주 최고가 대비 하락률 계산
- [ ] 추정 가중치로 결합 (EPS 33%, RS 33%, SMR 17%, 수급 12%, 주가 5%)
- [ ] 유니버스 대비 종합 점수 1-99 순위 매기기
- [ ] 목표: Composite Rating 90 이상

---

## 주요 참고 문헌

### 주요 출처:
1. **"How to Make Money in Stocks"** William J. O'Neil 저 (2판, 1995)
2. **Investor's Business Daily** (investors.com) - 공식 IBD 방법론 페이지
3. **IBD SmartSelect Ratings** 문서

### 구현 참고 자료:
- **GitHub: skyte/relative-strength** - Python으로 구현된 RS Rating
- **DataDrivenInvestor**: "Calculating the IBD RS Rating with Python" Shashank Vemuri 저
- **Portfolio123**: IBD 방식 순위 공식
- **TC2005**: IBD RS Rating 근사 공식

### 연구 논문:
- William O'Neil + Co. 연구: "The Greatest Stock Market Superstars" (1985-2019년 연구)
- 돌파 전 최고 성과 종목의 평균 RS Rating: **87**
- 최고 성과 종목의 평균 EPS Rating: **86**

---

## 중요 면책 조항

1. **독점 공식**: IBD의 정확한 공식은 독점 정보이다. 여기에 제시된 것은 공개 문서와 커뮤니티 구현을 기반으로 한 역공학 근사치이다.

2. **데이터 정규화**: IBD는 GAAP과 다를 수 있는 "정규화" 또는 "프로포마" 수익을 사용한다. 이 조정을 재현해야 한다.

3. **유니버스 정의**: IBD는 NYSE, NASDAQ, AMEX 전반에 걸쳐 종목을 비교한다. 정확한 백분위 순위를 위해 유니버스가 포괄적이어야 한다.

4. **업데이트 빈도**: IBD는 장 마감 후 매일 등급을 업데이트한다. 실시간 계산에는 현재 데이터 피드가 필요하다.

5. **정확도**: 이 공식들은 공식 IBD 등급과 높은 상관관계를 가진 결과를 산출하지만, 독점적 조정으로 인해 정확히 일치하지 않을 수 있다.

---

## 다음 단계

1. **과거 데이터 다운로드**: S&P 500 종목 (또는 더 넓은 유니버스)
2. **RS Rating 계산기 먼저 구현**: 가장 직관적이므로
3. **검증**: 일부 종목에 대해 IBD 공식 등급과 비교
4. **반복 개선**: 큰 차이가 있으면 공식 조정
5. **나머지 등급 구현**: EPS, SMR, 매집/분산
6. **Composite Rating으로 통합**
7. **스크리닝 함수 생성**: 아래 조건으로 종목 필터링:
   - RS Rating >= 90
   - EPS Rating >= 80
   - SMR Rating = A 또는 B
   - 매집/분산 등급 = A 또는 B
   - Composite Rating >= 90

**CANSLIM 경험 법칙:**
**모든** 등급이 동시에 강한 종목에 집중하라. 높은 RS + 높은 EPS + 강한 펀더멘털(SMR) + 기관 매수(매집/분산)의 교집합 = 가장 높은 확률의 매매 기회.

---

*기술 문서 끝*
