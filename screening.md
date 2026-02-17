# CANSLIM 수급 분석 (S) - 정량적 기준값 상세 정의

> **목적**: 모호한 수급 분석 기준을 알고리즘 트레이딩에 사용할 수 있는 정확하고 측정 가능한 스크리닝 상수로 변환한다.
> **출처**: IBD/MarketSmith 방법론, William O'Neil 연구, 현대 시장 기준 (2026)

---

## 1. 발행 주식 수 및 시가총액

### 1.1 과거 IBD 연구 (O'Neil의 원본 데이터)

| 지표 | 값 | 비고 |
|------|-----|------|
| **발행 주식 수 최대값** | < 2,500만 주 | 대형 상승 종목의 95%가 이 범위에 해당 |
| **발행 주식 수 중앙값** | 460만 주 | 폭발적 성장의 최적 지점 |
| **보수적 상한선** | < 5,000만 주 | 일부 CANSLIM 실무자들이 사용 |

**근거**: 주식 수가 적을수록 공급이 제한된다. 수요가 증가하면 가격이 더 빠르게 움직인다.

### 1.2 현대 시가총액 분류 (2026년 기준)

| 분류 | 시가총액 범위 | 일반적인 발행 주식 수 범위 |
|------|-------------|--------------------------|
| **초소형주 (Micro-cap)** | < 3억 달러 | 100만 - 1,000만 주 (주가 $30 기준) |
| **소형주 (Small-cap)** | 3억 - 20억 달러 | 1,000만 - 6,700만 주 (주가 $30 기준) |
| **중형주 (Mid-cap)** | 20억 - 100억 달러 | 6,700만 - 3억 3,300만 주 (주가 $30 기준) |
| **대형주 (Large-cap)** | > 100억 달러 | > 3억 3,300만 주 |

**CANSLIM 집중 구간**: 소형주에서 중형주 하단 (시가총액 3억 - 50억 달러)

### 1.3 권장 스크리닝 기준값

```python
# 엄격 기준 (기존 O'Neil 방식)
SHARES_OUTSTANDING_MAX_STRICT = 25_000_000
SHARES_OUTSTANDING_MEDIAN_TARGET = 4_600_000

# 보통 기준 (현대 소형주)
SHARES_OUTSTANDING_MAX_MODERATE = 50_000_000

# 완화 기준 (중형주 상단)
SHARES_OUTSTANDING_MAX_LIBERAL = 100_000_000

# 시가총액 기준값
MARKET_CAP_MIN = 300_000_000  # 3억 달러
MARKET_CAP_MAX = 5_000_000_000  # 50억 달러
```

---

## 2. Float (유통주식수) 분석

### 2.1 Float 정의
**Float(유통주식수) = 총 발행 주식 수 - 유통 제한 주식 수**

유통 제한 주식에 포함되는 항목:
- 내부자(임원, 이사회 구성원, 창업자) 보유 주식
- 직원 스톡옵션 (미확정 분)
- 기관 보호예수 주식
- 밀접 보유 주식

### 2.2 Float 비율 기준값

| Float 분류 | 총 주식 대비 Float 비율 | 신호 | 적합한 경우 |
|-----------|----------------------|------|-----------|
| **매우 낮음** | < 20% | 높은 변동성 가능 | 폭발적 움직임 |
| **낮음** | 20% - 50% | 양호한 공급 제한 | CANSLIM 최적 구간 |
| **보통** | 50% - 70% | 균형 잡힘 | 허용 가능 |
| **높음** | 70% - 90% | 유동성 높고 변동성 낮음 | 덜 이상적 |
| **매우 높음** | > 90% | 약한 수급 역학 | 회피 |

### 2.3 내부자 지분율 목표

| 기업 규모 | 이상적인 내부자 지분율 | 비고 |
|----------|---------------------|------|
| 소형주 | 10% - 25% | 강한 이해관계 일치 |
| 중형주 | 5% - 15% | 양호한 이해관계 일치 |
| 대형주 | 2% - 10% | 허용 가능 |

**경고**: 내부자 지분율 > 50% = 유동성 우려

### 2.4 권장 Float 스크리닝 상수

```python
# Float 비율 (Float / 총 발행 주식 수)
FLOAT_PERCENTAGE_MIN = 0.20  # 최소 20%
FLOAT_PERCENTAGE_MAX = 0.70  # 최대 70%
FLOAT_PERCENTAGE_IDEAL_MIN = 0.30  # 이상적 하한 30%
FLOAT_PERCENTAGE_IDEAL_MAX = 0.60  # 이상적 상한 60%

# 내부자 지분율
INSIDER_OWNERSHIP_MIN = 0.05  # 최소 5% (자신감 표시)
INSIDER_OWNERSHIP_MAX = 0.50  # 최대 50% (유동성 우려)
INSIDER_OWNERSHIP_IDEAL_MIN = 0.10  # 이상적 최소 10%
INSIDER_OWNERSHIP_IDEAL_MAX = 0.25  # 이상적 최대 25%
```

---

## 3. ADV (평균 일일 거래량) - 거래 가능성 기준값

### 3.1 유동성을 위한 최소 거래량

| 트레이딩 스타일 | 최소 ADV (주식 수) | 최소 ADV (달러 거래대금) |
|---------------|------------------|----------------------|
| **페니 주식** | 10만 주 | $50K 이상 |
| **스윙 트레이딩** | 50만 주 | $250K 이상 |
| **포지션 트레이딩** | 100만 주 | $500K 이상 |
| **IBD 권장** | 50만 주 | $400K 이상 |

**계산식**: 달러 거래대금 = 평균 일일 거래량 x 주가

### 3.2 포지션 크기 대비 ADV 규칙

**규칙**: 가격 영향을 피하기 위해 포지션 크기는 ADV의 5% 미만이어야 한다

예시:
- ADV = 100만 주인 경우
- 최대 포지션 = 5만 주 (ADV의 5%)
- $100K 상당 매수 시 주가는 $2/주 미만이어야 함

### 3.3 권장 거래량 스크리닝 상수

```python
# 평균 일일 거래량 (50일)
ADV_MIN_STRICT = 500_000  # 50만 주
ADV_MIN_MODERATE = 300_000  # 30만 주
ADV_MIN_LIBERAL = 100_000  # 10만 주

# 달러 거래대금 (주가 x 거래량)
DOLLAR_VOLUME_MIN = 400_000  # 일 $400K

# 포지션 크기 제한
MAX_POSITION_SIZE_PCT_OF_ADV = 0.05  # ADV의 5%
```

---

## 4. 돌파 시 거래량 급증

### 4.1 IBD 기준: 평균 대비 +50% 이상

**정의**: 돌파일에 거래량이 평균 일일 거래량보다 **최소 50% 이상** 높아야 한다.

**계산식**:
```python
# 50일 평균 일일 거래량
ADV_50 = sum(volume[-50:]) / 50

# 돌파 거래량 최소 요건
BREAKOUT_VOLUME_MIN = ADV_50 * 1.50  # 평균 대비 +50%

# 이상적인 돌파 거래량
BREAKOUT_VOLUME_IDEAL = ADV_50 * 2.00  # 평균 대비 +100%
BREAKOUT_VOLUME_STRONG = ADV_50 * 4.00  # +300% ~ +500%
```

### 4.2 거래량 급증 기준값

| 거래량 급증 수준 | 배수 | 신호 강도 | 활용 |
|---------------|------|---------|------|
| **최소 허용** | 1.40x - 1.50x | 약한 확인 | 위험 |
| **IBD 표준** | 1.50x - 2.00x | 유효한 돌파 | 필수 |
| **강함** | 2.00x - 4.00x | 높은 확신 | 이상적 |
| **폭발적** | > 4.00x | 기관 매수 쇄도 | 최상 |

### 4.3 "평균" 거래량의 산출 기간

| 산출 기간 | 활용 | IBD 기준 |
|----------|------|---------|
| **50일 SMA** | 표준 계산 | 주요 기준 |
| **20일 SMA** | 단기 비교 | 보조 기준 |
| **10주 SMA** | 주봉 차트 분석 | 주봉 돌파 |

### 4.4 권장 상수

```python
# 평균 거래량 산출 기간
VOLUME_LOOKBACK_DAYS = 50

# 돌파 거래량 배수
BREAKOUT_VOLUME_MIN_MULTIPLIER = 1.50  # +50%
BREAKOUT_VOLUME_IDEAL_MULTIPLIER = 2.00  # +100%
BREAKOUT_VOLUME_STRONG_MULTIPLIER = 4.00  # +300-500%

# 대안: 돌파일 절대 최소 거래량
BREAKOUT_VOLUME_ABSOLUTE_MIN = 1_000_000  # 최소 100만 주
```

---

## 5. 상승/하락 거래량 비율

### 5.1 IBD 방법론

**공식**:
```
Up/Down Volume Ratio = 상승일 총 거래량 / 하락일 총 거래량
```

**조건**:
- **상승일**: 종가 > 전일 종가
- **하락일**: 종가 < 전일 종가
- **보합일**: 계산에서 제외

**산출 기간**: **50 거래일** (IBD 기준)

### 5.2 계산 예시

```python
def calculate_up_down_ratio(prices, volumes, lookback=50):
    """
    IBD 방식의 상승/하락 거래량 비율 계산
    
    인자:
        prices: 종가 배열 (길이 >= lookback+1)
        volumes: 일별 거래량 배열 (길이 >= lookback+1)
        lookback: 과거 참조 일수 (기본값 50)
    
    반환값:
        float: 상승/하락 거래량 비율
    """
    up_volume = 0
    down_volume = 0
    
    for i in range(-lookback, 0):
        if prices[i] > prices[i-1]:
            up_volume += volumes[i]
        elif prices[i] < prices[i-1]:
            down_volume += volumes[i]
        # 보합인 경우 건너뜀
    
    if down_volume == 0:
        return float('inf')  # 모두 상승일
    
    return up_volume / down_volume
```

### 5.3 비율 해석 기준값

| 비율 값 | 신호 | 해석 | 대응 |
|---------|------|------|------|
| **> 1.5** | 강한 매집 | 강한 매수 압력 | 강세 |
| **1.2 - 1.5** | 보통 매집 | 긍정적 편향 | 강세 |
| **0.9 - 1.2** | 중립 | 균형 | 관망 |
| **0.7 - 0.9** | 보통 분산 | 매도 압력 | 주의 |
| **< 0.7** | 강한 분산 | 강한 매도 | 약세 |

### 5.4 권장 상수

```python
# 상승/하락 거래량 비율
UPDOWN_RATIO_LOOKBACK = 50  # 일
UPDOWN_RATIO_MIN_BULLISH = 1.20  # 매집 최소 기준
UPDOWN_RATIO_STRONG_BULLISH = 1.50  # 강한 매집
UPDOWN_RATIO_NEUTRAL_LOW = 0.90
UPDOWN_RATIO_NEUTRAL_HIGH = 1.20
UPDOWN_RATIO_MAX_BEARISH = 0.70  # 이 이하 = 분산
```

---

## 6. 거래량 고갈 정의

### 6.1 "거래량 고갈"이란?

**정의**: 베이스 형성 기간 (특히 컵-위드-핸들 패턴의 핸들 구간) 동안 거래량이 평균보다 **현저히 감소**해야 하며, 이는 매도 소진을 나타낸다.

### 6.2 거래량 고갈 기준값

| 위치 | 거래량 수준 | 평균 대비 비율 | 신호 |
|------|-----------|--------------|------|
| **베이스 저점 (컵 저점)** | 매우 낮음 | ADV의 50% 미만 | 매도 소진 |
| **핸들 형성** | 매우 낮음 | ADV의 40% 미만 | 강한 고갈 |
| **이상적인 핸들 저점** | 극히 낮음 | ADV의 30% 미만 | 완벽한 설정 |

**참고**: IBD에서 공식적으로 발표된 "40%" 또는 "50%"과 같은 기준값은 없다 - 이는 차트 분석에서 도출된 경험적 관찰 결과이다.

### 6.3 IBD 관점: 정성적 평가

IBD 방법론이 강조하는 사항:
1. **상대적 비교**: 거래량이 최근 평균보다 눈에 띄게 낮아야 함
2. **시각적 검토**: 차트에서 "축소된" 거래량 막대가 나타남
3. **맥락**: 거래량 고갈은 가격 횡보 구간에서 발생해야 하며, 상승 구간에서는 해당하지 않음

### 6.4 권장 상수

```python
# 거래량 고갈 기준값 (50일 ADV 대비 비율)
VOLUME_DRYUP_BASE_LOW = 0.50  # 평균의 50% 이하
VOLUME_DRYUP_HANDLE_LOW = 0.40  # 평균의 40% 이하
VOLUME_DRYUP_IDEAL = 0.30  # 평균의 30% 이하

# 계산
def is_volume_dried_up(current_volume, adv_50, threshold=0.40):
    """
    거래량 고갈 여부 확인
    
    인자:
        current_volume: 당일 거래량
        adv_50: 50일 평균 일일 거래량
        threshold: "고갈"로 간주하는 ADV 대비 비율 (기본값 40%)
    
    반환값:
        bool: 거래량이 고갈되었으면 True
    """
    return current_volume <= (adv_50 * threshold)
```

---

## 7. OBV (거래량 균형 지표)

### 7.1 OBV 계산

**공식** (Joe Granville 개발):
```
OBV[t] = OBV[t-1] + sign(Close[t] - Close[t-1]) x Volume[t]

조건:
- Close[t] > Close[t-1]인 경우: Volume[t] 더함
- Close[t] < Close[t-1]인 경우: Volume[t] 뺌
- Close[t] = Close[t-1]인 경우: OBV 변동 없음
```

### 7.2 IBD에서의 OBV 활용

**핵심 포인트**: IBD는 특정 OBV 수치 기준값을 사용하지 **않는다**. 대신 IBD는 다음에 집중한다:

1. **OBV 방향**: OBV 상승 = 매집, OBV 하락 = 분산
2. **OBV 다이버전스**: 
   - **강세 다이버전스**: 가격은 저점을 낮추는데, OBV는 저점을 높이는 경우
   - **약세 다이버전스**: 가격은 고점을 높이는데, OBV는 고점을 낮추는 경우
3. **확인**: OBV는 돌파 시 가격 움직임을 확인해야 함

### 7.3 OBV 추세 분석

| OBV 패턴 | 가격 패턴 | 신호 | 해석 |
|----------|---------|------|------|
| **상승** | 상승 | 확인 | 강한 상승 추세 |
| **상승** | 횡보/하락 | 강세 다이버전스 | 매집 중 |
| **횡보** | 상승 | 경고 | 약한 매수 지지 |
| **하락** | 상승 | 약세 다이버전스 | 분산 중 |
| **하락** | 하락 | 확인 | 하락 추세 |

### 7.4 OBV 기울기 계산 (정량적 접근)

```python
def calculate_obv_slope(obv_values, lookback=20):
    """
    OBV 기울기를 계산하여 추세 강도를 정량화
    
    인자:
        obv_values: OBV 값 배열
        lookback: 선형 회귀 기간 (기본값 20일)
    
    반환값:
        float: OBV 기울기 (양수 = 매집, 음수 = 분산)
    """
    import numpy as np
    x = np.arange(lookback)
    y = obv_values[-lookback:]
    slope, intercept = np.polyfit(x, y, 1)
    return slope
```

### 7.5 권장 OBV 분석 상수

```python
# OBV 추세 분석
OBV_LOOKBACK_SHORT = 20  # 일
OBV_LOOKBACK_MEDIUM = 50  # 일
OBV_LOOKBACK_LONG = 200  # 일

# OBV 기울기 기준값 (평균 거래량으로 정규화)
# 참고: 이 값들은 경험적 수치이며, IBD에서 정의한 것이 아님
OBV_SLOPE_STRONG_ACCUMULATION = 1.0  # 강한 양의 기울기
OBV_SLOPE_WEAK_ACCUMULATION = 0.3
OBV_SLOPE_NEUTRAL_MIN = -0.3
OBV_SLOPE_NEUTRAL_MAX = 0.3
OBV_SLOPE_WEAK_DISTRIBUTION = -0.3
OBV_SLOPE_STRONG_DISTRIBUTION = -1.0  # 강한 음의 기울기

# 다이버전스 탐지 기간
OBV_DIVERGENCE_LOOKBACK = 50  # 일
```

---

## 8. 매집/분산일 (A/D Days)

### 8.1 분산일 정의 (IBD)

**분산일(Distribution Day)**은 다음 조건이 충족될 때 발생한다:
1. 주요 지수 (S&P 500, NASDAQ)가 **0.2% 초과 하락** 마감
2. 거래량이 전일보다 **높음**

**의미**: 기관 매도를 나타냄

### 8.2 분산일 집계 규칙

| 분산일 수 (25일 이동 집계) | 시장 상태 | 대응 |
|--------------------------|---------|------|
| **0-1** | 건강 | 상승 추세 확인 |
| **2-3** | 주의 | 추가 신호 주시 |
| **4-5** | 압박 | 투자 비중 축소 |
| **6+** | 분산 | 보유 매도, 현금 전환 |

**초기화 규칙**:
- **25 거래일** 경과 후 해당 분산일은 제거됨
- 해당일 이후 지수가 **+5%** 상승하면 분산일이 제거됨

### 8.3 매집일 정의

**매집일(Accumulation Day)**(IBD에서 덜 공식적)은 다음 조건이 충족될 때 발생한다:
1. 주요 지수가 **유의미하게 상승** 마감 (> 0.5%)
2. 거래량이 전일보다 **높음**
3. 지수가 일봉 범위의 **상위 50%**에서 마감

### 8.4 FTD (후속 확인일)

**정의**: **FTD(Follow-Through Day)**는 새로운 상승 추세를 신호한다:
1. 반등 시도의 **3~10일차**에 발생
2. 지수가 **+1.0% 이상** 상승 마감
3. 거래량이 전일보다 **높음**
4. 결정적이고 강력한 움직임 (미미한 수준이 아님)

**참고**: 10일차 이후의 FTD = 신뢰도 낮음

### 8.5 권장 상수

```python
# 분산일
DISTRIBUTION_DAY_MIN_DECLINE = -0.002  # 최소 -0.2% 하락
DISTRIBUTION_DAY_VOLUME_REQ = "higher_than_previous"
DISTRIBUTION_DAY_COUNT_WINDOW = 25  # 일
DISTRIBUTION_DAY_RESET_GAIN = 0.05  # +5% 상승 시 카운트 초기화
DISTRIBUTION_DAY_WARNING_THRESHOLD = 4  # 4일 이상 = 주의
DISTRIBUTION_DAY_DANGER_THRESHOLD = 6  # 6일 이상 = 시장 고점

# 매집일
ACCUMULATION_DAY_MIN_GAIN = 0.005  # 최소 +0.5% 상승
ACCUMULATION_DAY_VOLUME_REQ = "higher_than_previous"
ACCUMULATION_DAY_CLOSE_RANGE = 0.50  # 일봉 범위의 상위 50%

# FTD (후속 확인일)
FTD_MIN_DAY = 3  # 반등 시도 3일차
FTD_MAX_DAY = 10  # 반등 시도 10일차
FTD_MIN_GAIN = 0.010  # 최소 +1.0% 상승
FTD_VOLUME_REQ = "higher_than_previous"
```

---

## 9. 전체 스크리닝 필터 상수 (Python 참조)

```python
# ============================================================================
# CANSLIM 수급 분석 (S) - 스크리닝 상수
# ============================================================================

# 1. 발행 주식 수 및 시가총액
SHARES_OUTSTANDING_MAX_STRICT = 25_000_000      # O'Neil의 95% 기준값
SHARES_OUTSTANDING_MAX_MODERATE = 50_000_000    # 보수적 상한선
SHARES_OUTSTANDING_MAX_LIBERAL = 100_000_000    # 완화 상한선
MARKET_CAP_MIN = 300_000_000                    # 3억 달러 (소형주 최소)
MARKET_CAP_MAX = 5_000_000_000                  # 50억 달러 (중형주 상단)

# 2. FLOAT 분석
FLOAT_PERCENTAGE_MIN = 0.20                     # 최소 유통 비율 20%
FLOAT_PERCENTAGE_MAX = 0.70                     # 최대 유통 비율 70%
FLOAT_PERCENTAGE_IDEAL_MIN = 0.30               # 이상적 최소 30%
FLOAT_PERCENTAGE_IDEAL_MAX = 0.60               # 이상적 최대 60%
INSIDER_OWNERSHIP_MIN = 0.05                    # 최소 내부자 지분율 5%
INSIDER_OWNERSHIP_MAX = 0.50                    # 최대 50% (유동성 우려)
INSIDER_OWNERSHIP_IDEAL_MIN = 0.10              # 이상적 최소 10%
INSIDER_OWNERSHIP_IDEAL_MAX = 0.25              # 이상적 최대 25%

# 3. 평균 일일 거래량 (ADV)
ADV_LOOKBACK_DAYS = 50                          # 50일 평균
ADV_MIN_STRICT = 500_000                        # 최소 50만 주
ADV_MIN_MODERATE = 300_000                      # 보통 30만 주
ADV_MIN_LIBERAL = 100_000                       # 완화 10만 주
DOLLAR_VOLUME_MIN = 400_000                     # 최소 달러 거래대금 $400K
MAX_POSITION_SIZE_PCT_OF_ADV = 0.05             # ADV 대비 최대 포지션 5%

# 4. 돌파 시 거래량 급증
BREAKOUT_VOLUME_MIN_MULTIPLIER = 1.50           # 50일 ADV 대비 +50% (IBD 최소)
BREAKOUT_VOLUME_IDEAL_MULTIPLIER = 2.00         # ADV 대비 +100% (이상적)
BREAKOUT_VOLUME_STRONG_MULTIPLIER = 4.00        # ADV 대비 +300-500% (강함)
BREAKOUT_VOLUME_ABSOLUTE_MIN = 1_000_000        # 절대 최소 100만 주

# 5. 상승/하락 거래량 비율
UPDOWN_RATIO_LOOKBACK = 50                      # 50일 (IBD 기준)
UPDOWN_RATIO_STRONG_BULLISH = 1.50              # 강한 매집
UPDOWN_RATIO_MIN_BULLISH = 1.20                 # 최소 매집 기준
UPDOWN_RATIO_NEUTRAL_LOW = 0.90                 # 중립 하한
UPDOWN_RATIO_NEUTRAL_HIGH = 1.20                # 중립 상한
UPDOWN_RATIO_MAX_BEARISH = 0.70                 # 최대 약세 (분산)

# 6. 거래량 고갈
VOLUME_DRYUP_BASE_LOW = 0.50                    # ADV의 50% 이하 (베이스 저점)
VOLUME_DRYUP_HANDLE_LOW = 0.40                  # ADV의 40% 이하 (핸들)
VOLUME_DRYUP_IDEAL = 0.30                       # ADV의 30% 이하 (이상적)

# 7. OBV (거래량 균형 지표)
OBV_LOOKBACK_SHORT = 20                         # 20일
OBV_LOOKBACK_MEDIUM = 50                        # 50일
OBV_LOOKBACK_LONG = 200                         # 200일
OBV_DIVERGENCE_LOOKBACK = 50                    # 다이버전스 탐지용 50일

# 8. 매집/분산일
DISTRIBUTION_DAY_MIN_DECLINE = -0.002           # 최소 -0.2% 하락
DISTRIBUTION_DAY_COUNT_WINDOW = 25              # 25일 이동 집계
DISTRIBUTION_DAY_RESET_GAIN = 0.05              # +5% 상승 시 카운트 초기화
DISTRIBUTION_DAY_WARNING_THRESHOLD = 4          # 4일 이상 = 주의
DISTRIBUTION_DAY_DANGER_THRESHOLD = 6           # 6일 이상 = 시장 고점
ACCUMULATION_DAY_MIN_GAIN = 0.005               # 최소 +0.5% 상승
FTD_MIN_DAY = 3                                 # 반등 시도 3일차
FTD_MAX_DAY = 10                                # 반등 시도 10일차
FTD_MIN_GAIN = 0.010                            # 최소 +1.0% 상승
```

---

## 10. 요약: 권장 스크리닝 등급

### 등급 1: 엄격 (기존 O'Neil 방식)
```
- 발행 주식 수 < 2,500만 주
- Float 비율 = 20-60%
- 내부자 지분율 = 10-25%
- ADV >= 50만 주
- 달러 거래대금 >= 일 $400K
- 돌파 거래량 >= ADV(50일)의 1.5배
- 상승/하락 비율 >= 1.5
```

### 등급 2: 보통 (현대 소형주)
```
- 발행 주식 수 < 5,000만 주
- Float 비율 = 20-70%
- 내부자 지분율 = 5-30%
- ADV >= 30만 주
- 달러 거래대금 >= 일 $250K
- 돌파 거래량 >= ADV(50일)의 1.5배
- 상승/하락 비율 >= 1.2
```

### 등급 3: 완화 (중형주 상단)
```
- 발행 주식 수 < 1억 주
- 시가총액 = 3억 - 100억 달러
- Float 비율 = 20-80%
- ADV >= 10만 주
- 달러 거래대금 >= 일 $100K
- 돌파 거래량 >= ADV(50일)의 1.4배
- 상승/하락 비율 >= 1.0
```

---

## 11. 주요 공식 참조

### 평균 일일 거래량 (50일)
```
ADV_50 = Sum(Volume[i] for i in last 50 days) / 50
```

### Float 비율
```
Float % = (총 발행 주식 수 - 유통 제한 주식 수) / 총 발행 주식 수
```

### 달러 거래대금
```
달러 거래대금 = 주가 x 평균 일일 거래량
```

### 상승/하락 거래량 비율
```
상승/하락 비율 = Sum(상승일 거래량) / Sum(하락일 거래량)
                 최근 50일 기준
```

### 돌파 거래량 검증
```
유효한 돌파 = (돌파일 거래량 >= ADV_50 x 1.50)
```

### 거래량 고갈 검증
```
고갈 여부 = (당일 거래량 <= ADV_50 x 0.40)
```

### OBV (거래량 균형 지표)
```
OBV[t] = OBV[t-1] + sign(Close[t] - Close[t-1]) x Volume[t]
```

---

## 12. 데이터 소스 및 API

### 필요한 데이터 항목
1. **발행 주식 수**: SEC 공시, 금융 API (Alpha Vantage, Polygon.io)
2. **Float**: FinViz, Yahoo Finance, MarketSmith
3. **내부자 지분율**: SEC Form 4, 내부자 거래 API
4. **일별 거래량**: 표준 시장 데이터 (모든 제공업체)
5. **과거 가격**: 비율 계산용 OHLC 데이터

### API 권장사항
- **Polygon.io**: 실시간 거래량, 발행 주식 수
- **Alpha Vantage**: 무료 기본적 분석 데이터
- **FinViz API**: Float 데이터, 내부자 지분율
- **SEC EDGAR**: 검증용 공식 공시 자료

---

**문서 끝**

---

**버전**: 1.0  
**최종 수정일**: 2026-02-14  
**작성**: CANSLIM 트레이딩 봇 프로젝트  
**참고문헌**: 
- William J. O'Neil 저, "How to Make Money in Stocks" (제2판, 1995)
- IBD MarketSmith 방법론
- Investor's Business Daily (IBD) 기술적 분석 가이드라인
