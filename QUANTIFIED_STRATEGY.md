# CANSLIM 트레이딩 봇 - 정량화된 전략 명세서

> **목적**: 기존 CANSLIM 전략의 모든 애매한(qualitative) 기준을 코드로 직접 구현 가능한 정량적(quantitative) 수치로 변환
> **출처**: William O'Neil "How to Make Money in Stocks", IBD Methodology, Gil Morales "Trade Like an O'Neil Disciple", Mark Minervini SEPA, MarketSmith 문서, 인터넷 검색 종합
> **작성일**: 2026-02-14

---

## 목차

1. [IBD 독자 평가 지표 계산 공식](#1-ibd-독자-평가-지표-계산-공식)
2. [종목 선정 필터 (CANSLIM 각 항목)](#2-종목-선정-필터)
3. [시장 방향 판단 알고리즘](#3-시장-방향-판단-알고리즘)
4. [차트 패턴 인식 수학적 기준](#4-차트-패턴-인식-수학적-기준)
5. [매수 규칙 정량화](#5-매수-규칙-정량화)
6. [매도 규칙 정량화 (공격적 + 방어적)](#6-매도-규칙-정량화)
7. [포지션 사이징 및 리스크 관리](#7-포지션-사이징-및-리스크-관리)
8. [업종 분석](#8-업종-분석)
9. [전체 상수 요약 (코드용)](#9-전체-상수-요약)

---

## 1. IBD 독자 평가 지표 계산 공식

### 1.1 RS Rating (Relative Strength Rating, 1-99)

IBD의 RS Rating은 주가의 상대적 가격 성과를 측정한다.

**공식:**
```
Raw_RS = 0.4 × (최근 3개월 수익률) 
       + 0.2 × (최근 6개월 수익률) 
       + 0.2 × (최근 9개월 수익률) 
       + 0.2 × (최근 12개월 수익률)
```

| 기간 | 거래일 수 | 가중치 |
|------|----------|--------|
| 3개월 | 63 거래일 | **40%** (2배 가중) |
| 6개월 | 126 거래일 | 20% |
| 9개월 | 189 거래일 | 20% |
| 12개월 | 252 거래일 | 20% |

**변환**: Raw_RS를 전체 주식 유니버스 대비 백분위(percentile)로 변환 → 1~99 스케일

**구현:**
```python
def calculate_rs_rating(stock_prices, universe_prices):
    ret_3m = (stock_prices[-1] / stock_prices[-63]) - 1
    ret_6m = (stock_prices[-1] / stock_prices[-126]) - 1
    ret_9m = (stock_prices[-1] / stock_prices[-189]) - 1
    ret_12m = (stock_prices[-1] / stock_prices[-252]) - 1
    
    raw_rs = 0.4 * ret_3m + 0.2 * ret_6m + 0.2 * ret_9m + 0.2 * ret_12m
    
    # 전체 유니버스 대비 백분위 계산
    all_raw_rs = [calc_raw_rs(s) for s in universe_prices]
    percentile = percentileofscore(all_raw_rs, raw_rs)
    return round(percentile)  # 1-99
```

### 1.2 RS Line (상대강도선)

```
RS_Line = 주가 / S&P 500 지수 값
```

**핵심 신호 감지:**
- RS Line이 주가보다 먼저 52주 신고가 → **강력한 매수 신호**
- RS Line 하락 추세 전환 → **매도 경고**

### 1.3 EPS Rating (1-99)

| 구성 요소 | 추정 가중치 |
|-----------|------------|
| 최근 2분기 EPS 증가율 (YoY) | ~50-60% |
| 3-5년 연간 EPS CAGR | ~30-40% |
| 성장 안정성 (표준편차) | ~10-20% |

**구현 근사치:**
```python
def calculate_eps_rating(quarterly_eps, annual_eps_5yr):
    # 최근 2분기 평균 YoY 성장률
    q_growth = mean([
        (quarterly_eps[-1] - quarterly_eps[-5]) / abs(quarterly_eps[-5]),  # 최신 분기
        (quarterly_eps[-2] - quarterly_eps[-6]) / abs(quarterly_eps[-6])   # 직전 분기
    ])
    
    # 5년 연간 CAGR
    annual_cagr = (annual_eps_5yr[-1] / annual_eps_5yr[0]) ** (1/5) - 1
    
    # 안정성 (변동계수의 역수)
    stability = 1 / (std(annual_eps_5yr) / mean(annual_eps_5yr) + 0.01)
    
    raw_eps = 0.55 * q_growth + 0.35 * annual_cagr + 0.10 * normalize(stability)
    return percentile_rank(raw_eps, universe)  # 1-99
```

### 1.4 SMR Rating (Sales + Margins + ROE, A~E)

| 등급 | 백분위 |
|------|--------|
| **A** | 상위 20% (80~100th) |
| **B** | 60~80th |
| **C** | 40~60th |
| **D** | 20~40th |
| **E** | 하위 20% (0~20th) |

**구성 요소**: 3분기 매출 성장률, 세전이익률, 세후이익률, ROE

### 1.5 Accumulation/Distribution Rating (A~E)

| 파라미터 | 값 |
|---------|-----|
| 조회 기간 | **13주 (65 거래일)** |
| Money Flow Multiplier | `((종가 - 저가) - (고가 - 종가)) / (고가 - 저가)` |
| Money Flow Volume | `MF_Multiplier × 거래량` |
| 최종 값 | 65일간 Money Flow Volume 누적 합 |
| 등급 | SMR과 동일한 A~E 백분위 적용 |

### 1.6 Composite Rating (1-99)

| 구성 요소 | 추정 가중치 |
|-----------|------------|
| EPS Rating | ~33% |
| RS Rating | ~33% |
| SMR Rating | ~17% |
| Acc/Dist Rating | ~12% |
| 52주 고가 대비 % | ~5% |

---

## 2. 종목 선정 필터

### 2.1 C = Current Quarterly EPS

| 파라미터 | 값 |
|---------|-----|
| 최소 분기 EPS 증가율 (YoY) | **+25%** |
| 이상적 EPS 증가율 | **+50% ~ +100%** |
| 역사적 대형 승자 평균 | **+70%** |
| 최소 허용 EPS 증가율 | **+18%** (PDF 기준) |
| 필터 제외 조건 | EPS 증가율 ≤ 0% (flat 또는 감소) |
| 기저 효과 제외 | 전년 동기 EPS < $0.10이면 제외 |

**추가 검증:**
- 매출 증가율도 함께 증가 중이어야 함 (이익률 악화 방지)
- 분기별 데이터로 추세 확인 (6개월/9개월 누적 데이터 사용 금지)

### 2.2 A = Annual Earnings

| 파라미터 | 값 |
|---------|-----|
| 연간 EPS 성장률 (5년) | **+25% CAGR 이상** |
| 이상적 수준 | **+25% ~ +50% CAGR** |
| 성장 안정성 지표 | **1 ~ 25** (낮을수록 안정적) |
| 허용 예외 | 1-2년 하락 후 반등 시 → 사상 최고치 근접 필요 |

### 2.3 N = New (신제품/신고가)

| 파라미터 | 값 |
|---------|-----|
| 52주 신고가 필요 여부 | **Yes** (적절한 베이스에서 돌파 시) |
| 신고가 추격 매수 한도 | 피벗 포인트 대비 **+5% 이내** |

### 2.4 S = Supply and Demand (수급)

#### 발행주식 수 / 시가총액

| 파라미터 | O'Neil 원전 값 | 현대 조정 값 |
|---------|---------------|-------------|
| 발행주식 수 (최대) | < 25M주 (역사적 승자 95%) | < 50M주 (보수적), < 100M주 (자유) |
| 발행주식 수 중간값 | 4.6M주 | - |
| 시가총액 선호 범위 | 소형~중형 | $300M ~ $5B |

#### 유동주식 비율 (Float)

| 파라미터 | 값 |
|---------|-----|
| 이상적 유동비율 | **30% ~ 60%** |
| 허용 범위 | 20% ~ 70% |
| 내부자 보유 이상 | 10% ~ 25% |
| 경고 수준 | 내부자 > 50% (유동성 문제) |

#### 최소 거래량 (유동성)

| 파라미터 | 값 |
|---------|-----|
| 최소 일평균 거래량 | **500,000주/일** (IBD 권장) |
| 최소 달러 거래량 | **$400,000/일** |
| 포지션 사이징 제한 | ADV의 5% 미만 |

#### 거래량 분석

| 파라미터 | 값 |
|---------|-----|
| 거래량 평균 산출 기간 | **50일 SMA** (IBD 표준) |
| 돌파 시 최소 거래량 | **ADV 50일 × 1.50** (+50% 이상) |
| 이상적 돌파 거래량 | **ADV × 2.0** (+100%) |
| 강력한 돌파 거래량 | **ADV × 3.0 ~ 5.0** (+200%~+400%) |
| 거래량 감소(dry-up) 정의 | **ADV의 50% 미만** (핸들/베이스 저점) |
| 강한 dry-up | **ADV의 30~40% 미만** |

#### Up/Down Volume Ratio

| 파라미터 | 값 |
|---------|-----|
| 산출 기간 | **50일** |
| 공식 | `상승일 총 거래량 / 하락일 총 거래량` |
| 축적(Accumulation) 신호 | **비율 ≥ 1.5** |
| 강한 축적 | **비율 ≥ 2.0** |
| 분배(Distribution) 신호 | **비율 < 0.7** |
| 중립 | 0.9 ~ 1.2 |

### 2.5 L = Leader or Laggard

| 파라미터 | 값 |
|---------|-----|
| RS Rating 최소 | **80** (1~99 스케일) |
| 역사적 대형 승자 평균 RS | **87** |
| 이상적 RS | **90+** |
| 매도 고려 RS | **< 70** |
| 매수 금지 RS | **< 70** |

### 2.6 I = Institutional Sponsorship

| 파라미터 | 값 |
|---------|-----|
| 최소 기관 보유자 수 | **5개 이상** |
| 품질 기관 최소 AUM | **$100M** (SEC 13F 기준) |
| 품질 기관 선호 AUM | **$1B+** |
| IBD Sponsorship Rating | **B+ 이상** (A+ ~ E 스케일) |
| 기관 보유 비율 이상 범위 | **10% ~ 60%** |
| 과매수 경고 | **> 80%** |
| QoQ 보유자 수 증가 (의미 있는) | **+10% 이상** |
| QoQ 보유 주식 수 증가 (의미 있는) | **+10% 이상** |
| 확인 기간 | **2분기 연속 증가** |
| 신규 vs 청산 비율 (Bullish) | **≥ 1.5:1** |
| 강한 Bullish | **≥ 2.0:1** |
| Acc/Dist Rating | **A 또는 B** |

#### 경영진 보유 (Insider Ownership)

| 회사 규모 | 최소 | 이상적 | 경고 |
|-----------|------|--------|------|
| 소형주 | 5% | 10~25% | > 35% |
| 중형주 | 2% | 5~10% | > 35% |
| 대형주 | 1% | 2~5% | > 35% |

#### 자사주 매입

| 파라미터 | 값 |
|---------|-----|
| 의미 있는 수준 | **연 5%+ 자사주 매입** |
| 강한 신호 | **연 10%+** |

#### 부채비율 (D/E Ratio)

| 파라미터 | 값 |
|---------|-----|
| CANSLIM 최대 | **2.0 이하** |
| 이상적 | **1.0 이하** |
| 최적 | **0.1 ~ 0.5** |

### 2.7 M = Market Direction

→ 섹션 3에서 상세 정량화

---

## 3. 시장 방향 판단 알고리즘

### 3.1 Market Status 상태 머신

```
[확인된 상승추세] ←→ [압력받는 상승추세] ←→ [시장 조정] → [반등 시도] → [확인된 상승추세]
```

| 시장 상태 | 트리거 | 투자 비중 |
|-----------|--------|----------|
| **Confirmed Uptrend** | FTD 확인 | 75~100% 투자 |
| **Uptrend Under Pressure** | Distribution Day 3~4개 | 50~75% 투자 |
| **Uptrend in Trouble** | Distribution Day 5~6개 | 25~50% 투자 |
| **Market in Correction** | Distribution Day 7+개 / FTD 실패 | 0~25% 투자 |
| **Rally Attempt** | Day 1 감지 (조정 중 첫 상승 마감) | 0~25% 투자 |

### 3.2 Distribution Day (분배일) 감지

| 파라미터 | 정확한 값 |
|---------|----------|
| 가격 하락 임계값 | **-0.2% 이상** (반올림 없이) |
| 거래량 비교 대상 | **전일 거래량** (50일 평균 아님) |
| 거래량 조건 | **> 전일 거래량** |
| 적용 대상 | S&P 500, Nasdaq Composite |

#### Distribution Day 카운팅

| Distribution Day 수 | 기간 내 | 시장 상태 |
|---------------------|---------|----------|
| 3~4개 | 4~5주 내 | **Uptrend Under Pressure** |
| 5~6개 | 4~5주 내 | **Uptrend in Trouble** |
| 7+개 | - | **Market in Correction** |

#### Distribution Day 만료 조건

| 조건 | 임계값 |
|------|--------|
| 시간 기반 만료 | **25 거래일** 경과 |
| 가격 기반 만료 | 해당 분배일 종가 대비 지수 **+5%** 상승 |
| 적용 | 둘 중 하나라도 충족 시 제거 |

#### Stalling Day (정체일) — Distribution으로 카운트

| 파라미터 | 정확한 값 |
|---------|----------|
| 가격 변동 | **+0% ~ +0.4%** (소폭 상승) |
| 종가 위치 | **일간 레인지의 하단 50%** |
| 거래량 | **전일 대비 95% 이상** |
| 컨텍스트 | 신고가 부근 또는 확립된 상승추세 중 |

### 3.3 Follow-Through Day (추세 확인일) 감지

#### Day 1 정의

| 파라미터 | 값 |
|---------|-----|
| 정의 | 하락/조정 후 **첫 양봉 마감** |
| 기준점 | 해당일 저가가 rally attempt의 기준 저점(reference low) |
| 무효화 | 이후 종가가 Day 1 저가 이하로 하락 시 리셋 |

#### FTD 파라미터

| 파라미터 | 표준 값 | 강한 신호 | 허용 범위 |
|---------|---------|----------|----------|
| 최소 발생일 | **Day 4** | Day 4~5 | Day 3 |
| 최적 발생일 범위 | Day 4~7 | Day 4~5 | Day 3~10 |
| 최대 유효 발생일 | **Day 10** | Day 7 | 없음 (약해짐) |
| 최소 상승률 | **+1.25%** | **+1.7%** | +1.0% |
| 이상적 상승률 | **+2.0%+** | +2.0%+ | +1.25%+ |
| 거래량 조건 | **전일 대비 증가** | 전일 대비 + 50일 평균 대비 증가 | 전일 대비 증가 |

#### FTD 실패 확률

| FTD 이후 일수 | Distribution Day 발생 시 실패 확률 |
|--------------|----------------------------------|
| Day 1~2 | **95%** |
| Day 3 | **70%** |
| Day 4~5 | **30%** |
| Day 6+ | 정상 수준 |

#### FTD 무효화 조건

| 조건 | 실패 확률 |
|------|----------|
| 지수가 FTD 당일 저가 이하로 마감 | **90%+** |
| 지수가 Day 1 저가 이하로 마감 | **Rally Attempt 자체 무효** |
| FTD 후 1~2일 내 Distribution Day | **95%** |

#### FTD 역사적 성공률

| 결과 유형 | 비율 |
|-----------|------|
| 수익 창출 랠리 (Money Maker) | **33%** |
| 안전 이탈 가능 (SLOG) | **41%** |
| 경고 없이 손실 | **26%** |

### 3.4 Power Trend (강력 추세)

IBD Power Trend는 4가지 조건이 동시에 충족될 때 시작된다:

| 조건 | 정확한 기준 |
|------|-----------|
| 1. 지수 10일 저가 > 21일 EMA | **10 연속 거래일** 이상 |
| 2. 21일 EMA > 50일 SMA | **5 연속 거래일** 이상 |
| 3. 50일 SMA 상승 중 | **1일 이상** 상승 방향 |
| 4. 지수 양봉 마감 | 전일 대비 상승 마감 |

**Power Trend 종료 조건:**
- 21일 EMA가 50일 SMA 아래로 교차
- **Circuit Breaker**: 지수가 50일선 아래 + 최근 고점 대비 -10% 이상 하락
- **FTD 실패**: 지수가 FTD 저가 아래로 마감

---

## 4. 차트 패턴 인식 수학적 기준

### 4.1 Cup with Handle

#### Cup 부분

| 파라미터 | 정확한 값 |
|---------|----------|
| 최소 깊이 | 왼쪽 림 고가 대비 **-12%** |
| 최대 깊이 (정상 시장) | **-33%** |
| 최대 깊이 (변동성 시장) | **-50%** |
| 절대 최대 깊이 | **-67%** (2/3 되돌림) |
| 최소 기간 | **35 거래일** (7주) |
| 일반 기간 | 63~126 거래일 (3~6개월) |
| 최대 기간 | **325 거래일** (65주) |

**깊이 공식:**
```python
cup_depth_pct = ((left_rim_high - cup_low) / left_rim_high) * 100
valid = 12.0 <= cup_depth_pct <= 33.0  # 정상 시장
valid_volatile = 12.0 <= cup_depth_pct <= 50.0  # 변동성 시장
```

#### U자 vs V자 판별

```python
# 바닥 영역 = 컵 깊이의 하위 20%
bottom_zone = cup_low + (left_rim_high - cup_low) * 0.20

# 바닥 영역에서의 체류 일수
days_at_bottom = count_days_below(bottom_zone)

# U자형: 바닥 영역에서 최소 10 거래일(2주) 체류
is_U_shape = days_at_bottom >= 10

# V자형 거부: 하강/상승 비율이 대칭적이면서 바닥 체류 부족
descent_days = days_from_left_rim_to_bottom
ascent_days = days_from_bottom_to_right_rim
ratio = descent_days / ascent_days
is_V_shape = (0.8 <= ratio <= 1.2) and (days_at_bottom < 10)

valid_shape = is_U_shape and not is_V_shape
```

#### Handle 부분

| 파라미터 | 정확한 값 |
|---------|----------|
| 최소 기간 | **5 거래일** (1주) |
| 일반 기간 | 5~20 거래일 (1~4주) |
| 최대 깊이 (보수적) | 핸들 고가 대비 **-12%** |
| 최대 깊이 (Cup advance 대비) | Cup advance의 **-33%** |
| 위치 | **Cup 상단 50%** (midpoint 이상) |
| 200일 MA 대비 | **200일 MA 위**에 있어야 함 |
| 드리프트 방향 | **약간 하향** 또는 횡보 (선형 회귀 기울기 -15도 ~ +1도) |
| 이상적 드리프트 | 기울기 -8도 ~ 0도 |
| 상향 웨지 (실패 패턴) | 기울기 > +5도 → **거부** |

**Handle 위치 검증:**
```python
cup_midpoint = (cup_high + cup_low) / 2
valid_handle_position = handle_low >= cup_midpoint  # 핸들 전체가 상단 50%
```

**Handle 거래량 감소:**
```python
handle_avg_volume = mean(volume[handle_start:handle_end])
avg_volume_50d = mean(volume[-50:])
volume_reduction_pct = ((avg_volume_50d - handle_avg_volume) / avg_volume_50d) * 100

valid_dryup = volume_reduction_pct >= 40  # ADV 대비 40% 이상 감소
ideal_dryup = volume_reduction_pct >= 50  # 50% 이상 감소
```

#### Pivot Point (매수점) 계산

```python
pivot_point = handle_high + 0.10  # 핸들 고가 + $0.10
buy_zone_max = pivot_point * 1.05  # 피벗에서 +5%까지가 매수 구간
```

#### Breakout 확인

| 파라미터 | 정확한 값 |
|---------|----------|
| 돌파 거래량 | **ADV 50일 × 1.40** (최소 +40%) |
| 이상적 돌파 거래량 | **ADV × 1.50** (+50%) |
| 매수 유효 범위 | Pivot ~ **Pivot + 5%** |
| 추격 매수 금지 | **Pivot + 5% 초과** |

### 4.2 Double Bottom (이중 바닥)

| 파라미터 | 정확한 값 |
|---------|----------|
| 형태 | W자형 |
| 두 번째 바닥 조건 | **첫 번째 바닥보다 낮아야 함** (undercut) |
| Undercut 허용 범위 | **0.5% ~ 10%** (너무 깊으면 거부) |
| 중간 봉우리(middle peak) | **베이스 상단 50% 이상**에 위치 |
| 중간 봉우리 최소 상승 | 바닥 대비 **+12%** 이상 |
| 최소 기간 | **35 거래일** (7주) |
| 일반 깊이 | **-20% ~ -40%** |
| 매수점 (Pivot) | **중간 봉우리 고가 + $0.10** |
| 돌파 거래량 | ADV 대비 **+30% ~ +40%** 이상 |

```python
# 이중 바닥 검증
valid_undercut = second_bottom < first_bottom  # 필수
valid_undercut_depth = second_bottom >= first_bottom * 0.90  # 10% 이내

base_midpoint = (base_high + min(first_bottom, second_bottom)) / 2
valid_middle_peak = middle_peak >= base_midpoint  # 상단 50%에 위치
```

### 4.3 Flat Base (평탄 베이스)

| 파라미터 | 정확한 값 |
|---------|----------|
| 최대 가격 진폭 | **15%** (고가 대비) |
| 이상적 진폭 | **12% 이내** |
| 최소 기간 | **25 거래일** (5주) |
| 최대 기간 | 325 거래일 (65주) |
| 선행 조건 | **직전 30%+ 상승** 이후 형성 |
| 매수점 (Pivot) | **Flat base 고가 + $0.10** |
| 돌파 거래량 | ADV 대비 **+40% ~ +50%** 이상 |

```python
flat_high = max(prices[base_start:base_end])
flat_low = min(prices[base_start:base_end])
oscillation_pct = ((flat_high - flat_low) / flat_high) * 100
valid_flat_base = oscillation_pct <= 15.0
```

### 4.4 High Tight Flag (고점 밀착 깃발)

| 파라미터 | 정확한 값 |
|---------|----------|
| 선행 상승 | **+100% ~ +120%** |
| 선행 상승 기간 | **4~8주** (20~40 거래일) |
| 조정 기간 | **3~5주** (15~25 거래일) |
| 조정 깊이 | **-10% ~ -20%** |
| 돌파 후 잠재력 | +200% 이상 |
| 발생 빈도 | 연 1~2회 (매우 희귀) |

### 4.5 Base Stage Counting (베이스 단계 카운팅)

| 규칙 | 값 |
|------|-----|
| 1차 베이스 조건 | 직전 **30%+ 상승** 후 첫 번째 베이스 |
| 단계 상승 조건 | 이전 피벗에서 **+20%** 상승 후 다음 베이스 형성 |
| Base-on-Base | 피벗에서 **+20% 미달** → 동일 단계 (1A, 1B 표기) |
| 단계 리셋 → 1단계 | 현재 베이스 저점이 이전 베이스 저점을 **하향 돌파** |
| 약세장 리셋 → 1단계 | 주요 지수 **-20%+** 하락 (약세장) 시 전체 리셋 |
| 3차/4차 베이스 | **실패 확률 매우 높음** — 매수 회피 권장 |
| 최소 가격 | **$10 이상**인 종목만 베이스 카운팅 |

### 4.6 공통 패턴 요구사항

| 요구사항 | 값 |
|---------|-----|
| 직전 상승추세 | **최소 +30%** |
| 최소 베이스 기간 | 7주 (Flat Base는 5주) |
| 최대 베이스 깊이 | -40% (초과 시 실패율 급증) |
| 돌파 거래량 | ADV 50일 대비 **+40%~+50%** |
| 매수 구간 | Pivot ~ Pivot +5% |
| 거래량 감소 (바닥) | 일반적으로 감소 추세 |
| Handle/조정 | 베이스 상단 50%에 위치 |

### 4.7 실패(Faulty) 패턴 거부 조건

다음 중 **하나라도** 해당 시 매수 금지:

| # | 거부 조건 | 정량 기준 |
|---|---------|----------|
| 1 | 넓고 느슨한 패턴 | 주간 변동폭 > 15% |
| 2 | 3차 이상 베이스 | Stage ≥ 3 |
| 3 | Handle이 베이스 하단 50%에 위치 | handle_low < cup_midpoint |
| 4 | Handle이 200일 MA 아래 | handle_low < MA200 |
| 5 | Handle 상향 웨지 | 선형 회귀 기울기 > +5도 |
| 6 | Handle 깊이 과다 | > -15% (강세장) |
| 7 | V자 급등 후 핸들 없이 돌파 | days_at_bottom < 10 and no_handle |
| 8 | RS 하락 추세 | RS Line 52주 신고가 미갱신 |
| 9 | 비정상 거래량 | 하락일 거래량 > 상승일 거래량 (U/D ratio < 1.0) |
| 10 | 베이스 형성 < 6주 | duration < 30 거래일 |

---

## 5. 매수 규칙 정량화

### 5.1 진입 조건 체크리스트

| # | 조건 | 정량 기준 | 필수 여부 |
|---|------|----------|----------|
| 1 | 시장 상태 | Confirmed Uptrend 또는 Power Trend 활성 | **필수** |
| 2 | RS Rating | **≥ 80** | **필수** |
| 3 | EPS Rating | **≥ 80** | **필수** |
| 4 | 분기 EPS 증가율 | **≥ +25%** (YoY) | **필수** |
| 5 | 연간 EPS CAGR | **≥ +25%** (5년) | **필수** |
| 6 | 적절한 베이스 패턴 | Cup/Double Bottom/Flat Base 1~2차 | **필수** |
| 7 | 돌파 거래량 | **≥ ADV × 1.50** | **필수** |
| 8 | 매수 구간 | **Pivot ~ Pivot +5%** | **필수** |
| 9 | 기관 보유 증가 | QoQ +10% 이상 | 권장 |
| 10 | 업종 상대강도 | 상위 40위 이내 | 권장 |
| 11 | Acc/Dist Rating | A 또는 B | 권장 |
| 12 | 부채비율 | ≤ 1.0 | 권장 |

### 5.2 Pyramiding (추가 매수) 규칙

| 매수 차수 | 트리거 | 수량 | 최대 매수가 |
|-----------|--------|------|-----------|
| **1차 (초기)** | Pivot Point 돌파 | 포지션의 **50%** | Pivot +5% 이내 |
| **2차** | 초기 매수가 대비 **+2.0% ~ +2.5%** | 초기의 **30%** | Pivot +5% 이내 |
| **3차** | 초기 매수가 대비 **+4.0% ~ +5.0%** | 초기의 **20%** | Pivot +5% 이내 |

**추가 매수 불가 조건:**
- 가격이 Pivot +5% 초과
- 시장 상태가 Under Pressure 이상
- 첫 매수에서 손실 발생 중

### 5.3 8주 보유 규칙

| 파라미터 | 값 |
|---------|-----|
| 트리거 조건 | 돌파 후 **3주 이내**에 **+20% 이상** 상승 |
| 보유 기간 | 최소 **8주** (돌파일 = Week 1) |
| 스톱 조정 | +20% 달성 시 → 스톱을 **매수가 (손익분기)**로 올림 |
| 8주 후 | 차트 상태, 펀더멘털, 시장 재평가 후 지속 보유 결정 |
| 선행 조건 | CANSLIM 기준 충족 + 적절한 매수점에서 진입 |

### 5.4 Minervini Trend Template (보조 필터)

추가적 종목 품질 확인을 위한 Mark Minervini의 SEPA Trend Template:

| # | 조건 | 기준 |
|---|------|------|
| 1 | 현재가 > 50일 SMA | **필수** |
| 2 | 현재가 > 150일 SMA | **필수** |
| 3 | 현재가 > 200일 SMA | **필수** |
| 4 | 50일 SMA > 150일 SMA | **필수** |
| 5 | 150일 SMA > 200일 SMA | **필수** |
| 6 | 200일 SMA 상승 추세 (최소 1개월) | **필수** |
| 7 | 52주 고가 대비 | **-25% 이내** |
| 8 | 52주 저가 대비 | **+30% 이상** |
| 9 | RS Rating | **≥ 70** (이상적 ≥ 90) |

---

## 6. 매도 규칙 정량화

### 6.1 방어적 매도 (손절)

#### A. 절대 손절

| 파라미터 | 정확한 값 |
|---------|----------|
| **최대 손실 한도** | 매수가 대비 **-8.0%** |
| 실행 | 기계적, 예외 없음 |
| 대안 (분할 손절) | -5%에서 50% 매도, -10%에서 나머지 매도 |

```python
HARD_STOP_LOSS = -0.08  # -8%
# 매수 즉시 설정, 절대 해제하지 않음
```

#### B. 트레일링 스톱 (이익 보호)

| 수익률 달성 | 스톱 조정 |
|-----------|----------|
| +15% | 매수가 **-5%**로 올림 |
| +20% | **매수가 (손익분기)**로 올림. 절대 손실 전환 금지 |
| +25% | 고점 대비 **-10% ~ -12%** 트레일링 |

```python
def calculate_trailing_stop(buy_price, max_price_since_buy, current_price):
    max_gain = (max_price_since_buy - buy_price) / buy_price
    
    if max_gain >= 0.20:
        return buy_price  # 절대 손실 전환 금지
    elif max_gain >= 0.15:
        return buy_price * 0.95  # 매수가 -5%
    else:
        return buy_price * 0.92  # 기본 -8% 손절
```

#### C. 펀더멘털 매도 신호

| 신호 | 정량 기준 |
|------|----------|
| EPS 감속 | **2분기 연속** YoY 성장률 둔화 (예: +50% → +30% → +20%) |
| EPS 감소 | 임의 분기 EPS 성장률 **마이너스** → 즉시 매도 |
| RS Rating 하락 | **< 70** |

#### D. 기술적 매도 신호

| 신호 | 정량 기준 |
|------|----------|
| 50일 MA 하향 이탈 | 종가 < 50일 MA, 거래량 ≥ ADV × 1.5 |
| 10주 MA 하향 이탈 | 주간 종가 < 10주 MA + 거래량 ≥ 주간 ADV × 1.5 |
| 10주 MA 결정적 이탈 | 주간 종가가 10주 MA 대비 **-2%** 이하 |
| 200일 MA 하향 전환 | 200일 MA 기울기가 음수로 전환 |

### 6.2 공격적 매도 (이익 실현)

#### A. Climax Top (급등 천장) 감지

| 파라미터 | 정확한 값 |
|---------|----------|
| 기간 | **8~12 거래일** (2~3주) |
| 최소 상승률 | 해당 기간 내 **+25%** |
| 상승일 패턴 | **7/10일** 또는 **8/10일** 상승 |
| 선행 조건 | 돌파 후 **최소 18주** 경과 |
| 200일 MA 이격 | **+70% ~ +100%** 이상 |

```python
def detect_climax_top(prices, buy_date, ma200):
    lookback = 10  # 거래일
    recent_gain = (prices[-1] - prices[-lookback]) / prices[-lookback]
    up_days = sum(1 for i in range(-lookback, 0) if prices[i] > prices[i-1])
    weeks_since_buy = (today - buy_date).days / 7
    extension_from_200ma = (prices[-1] - ma200) / ma200
    
    is_climax = (
        recent_gain >= 0.25 and          # +25% in 10 days
        up_days >= 7 and                  # 7/10 up days
        weeks_since_buy >= 18 and         # 18+ weeks from breakout
        extension_from_200ma >= 0.70      # 70%+ above 200MA
    )
    return is_climax
```

#### B. 최대 일일 상승폭 (Exhaustion Signal)

```python
# 매수일 이후 모든 일일 상승폭과 비교
daily_gain = close_today - close_yesterday
max_daily_gain_since_buy = max(all_daily_gains_since_buy)

if daily_gain > max_daily_gain_since_buy:
    signal = "SELL - 소진 신호 (역사적 최대 일일 상승)"
```

#### C. 최대 거래량일 (Volume Exhaustion)

```python
if today_volume > max(all_volumes_since_buy):
    signal = "SELL - 거래량 소진 (매수 후 최대 거래량)"
```

#### D. 신고가 + 거래량 감소

```python
if price == new_52week_high and volume < avg_volume_50day:
    signal = "SELL - 수요 부족 (신고가인데 거래량 평균 미달)"
```

#### E. 연속 저가 마감 (Closing at Lows)

```python
daily_range = high - low
close_position = (close - low) / daily_range if daily_range > 0 else 0.5

if close_position <= 0.25:  # 하단 25%
    consecutive_low_closes += 1
    if consecutive_low_closes >= 2:  # 2일 연속
        signal = "SELL - 연속 저가 마감"
```

#### F. 200일 MA 과이격

```python
extension = (price - ma200) / ma200
if extension >= 0.70:
    signal = "SELL WARNING - 200MA 대비 +70% 이격"
if extension >= 1.00:
    signal = "SELL - 200MA 대비 +100% 이격 (극단적)"
```

#### G. Keltner Channel 이탈

```python
middle = EMA(close, 20)
upper = middle + 2 * ATR(10)

days_above_upper = consecutive_days_above(price, upper)
if days_above_upper >= 6:
    signal = "SELL - Channel 상단 6일+ 이탈 (소진)"
```

#### H. 주식 분할 급등

```python
if stock_split_announced:
    gain_since_announcement = (price - price_at_announcement) / price_at_announcement
    days_since = trading_days_since(announcement_date)
    
    if gain_since_announcement >= 0.25 and days_since <= 10:
        signal = "SELL - 주식분할 급등 (+25%+ in 1-2주)"
```

#### I. 3차/4차 베이스 신고가

```python
if base_stage >= 3 and price == new_high:
    signal = "SELL - 3차+ 베이스에서 신고가 (실패 확률 높음)"
```

### 6.3 보유 지속 조건

| 조건 | 정량 기준 |
|------|----------|
| 8주 보유 규칙 | 3주 내 +20% → 최소 8주 보유 |
| 10주 MA 위 유지 | 주간 종가가 10주 MA 위 + 거래량 정상 |
| 13주 무반응 매도 | 매수 후 **13주**간 의미 있는 움직임 없음 → 매도 고려 |
| 강세장 초기 장기 보유 | 강세장 첫 **1~2년**은 장기 보유 최적기 |

### 6.4 매도 규칙 우선순위 (봇 구현용)

| Tier | 규칙 | 우선순위 |
|------|------|---------|
| **1 (필수)** | -8% 절대 손절 | 최우선 실행 |
| **1** | +20% 손익분기 보호 | 최우선 실행 |
| **1** | 50일 MA 이탈 + heavy volume | 최우선 실행 |
| **1** | RS < 70 | 최우선 실행 |
| **2 (중요)** | Climax top (10일, +25%, 7/10 상승) | 높은 우선순위 |
| **2** | 200MA 대비 +70%~+100% 이격 | 높은 우선순위 |
| **2** | 매수 후 최대 거래량일 | 높은 우선순위 |
| **2** | +15% 트레일링 스톱 | 높은 우선순위 |
| **3 (고급)** | Keltner channel 6일+ 이탈 | 선택적 |
| **3** | EPS 2분기 감속 | 선택적 |
| **3** | 10주 MA 이탈 (1.5x 거래량) | 선택적 |
| **3** | 연속 저가 마감 2일+ | 선택적 |

---

## 7. 포지션 사이징 및 리스크 관리

### 7.1 포트폴리오 구성

| 투자금 규모 | 최대 종목 수 | 종목당 비중 |
|-----------|------------|-----------|
| < $5,000 | 2 | 50% |
| $5,000 ~ $20,000 | 3 | 33% |
| $20,000 ~ $100,000 | 4~5 | 20~25% |
| $100,000 ~ $1,000,000 | 6~7 | 14~17% |

### 7.2 포지션 사이징 공식

#### 방법 1: 동일 비중법 (O'Neil 기본)

```python
position_size = portfolio_value / max_positions
# 예: $100,000 / 5 = $20,000 per position (20%)
```

#### 방법 2: 리스크 기반 사이징 (Minervini)

```python
max_risk_per_trade = 0.01  # 포트폴리오의 1%
stop_loss_pct = 0.08  # 8%

position_size = (portfolio_value * max_risk_per_trade) / stop_loss_pct
# 예: ($100,000 × 0.01) / 0.08 = $12,500 (12.5%)
```

#### 방법 3: 변동성 조정 사이징

```python
atr_20 = ATR(20)
risk_per_share = atr_20 * 2  # 2 ATR 스톱
max_dollar_risk = portfolio_value * 0.01  # 포트폴리오 1%

shares = max_dollar_risk / risk_per_share
position_size = shares * current_price
```

### 7.3 Pyramiding (추가 매수) 상세

```python
# 전체 포지션 배분: 50% → 30% → 20%
PYRAMID_SCHEDULE = [
    {'trigger': 0.00, 'size_pct': 0.50},   # 1차: 피벗에서 50%
    {'trigger': 0.025, 'size_pct': 0.30},   # 2차: +2.5%에서 30%
    {'trigger': 0.05, 'size_pct': 0.20},    # 3차: +5.0%에서 20%
]

# 예시: $20,000 전체 포지션
# 1차: $10,000 at Pivot
# 2차: $6,000 at Pivot +2.5%
# 3차: $4,000 at Pivot +5.0%
# 총합: $20,000, 평균 단가 = Pivot +1.75%
```

### 7.4 포트폴리오 Heat (총 리스크)

```python
# 각 포지션의 포트폴리오 리스크 기여도
position_risk = position_size_pct * stop_loss_pct
# 예: 20% × 8% = 1.6% per position

# 총 포트폴리오 리스크
total_heat = sum(position_risks)
# 예: 5 positions × 1.6% = 8.0% total portfolio risk

# 최대 허용 포트폴리오 heat
MAX_PORTFOLIO_HEAT_CONSERVATIVE = 0.08  # 8%
MAX_PORTFOLIO_HEAT_MODERATE = 0.10      # 10%
MAX_PORTFOLIO_HEAT_AGGRESSIVE = 0.12    # 12%
```

### 7.5 시장 상태별 투자 비중 모델

| 시장 상태 | Distribution Days | 투자 비중 | 현금 비중 |
|-----------|------------------|----------|----------|
| **Confirmed Uptrend + Power Trend** | 0~2 | **80~100%** | 0~20% |
| **Confirmed Uptrend** | 0~3 | **75~100%** | 0~25% |
| **Uptrend Under Pressure** | 3~4 | **50~75%** | 25~50% |
| **Uptrend in Trouble** | 5~6 | **25~50%** | 50~75% |
| **Market in Correction** | 7+ | **0~25%** | 75~100% |
| **Rally Attempt** | - | **0~25%** | 75~100% |

**Exposure Step-Down 모델:**
```
100% → 75% (DD=4) → 50% (DD=5) → 25% (DD=6) → 0% (DD=7+)
```

### 7.6 승률 및 손익비

| 파라미터 | 값 |
|---------|-----|
| 기대 승률 | **30~50%** (O'Neil: "300 타율로도 충분") |
| 평균 수익 (winner) | **+20% ~ +30%** |
| 평균 손실 (loser) | **-7% ~ -8%** |
| 손익비 (R:R) | **2.5:1 ~ 4:1** |
| 손익분기 승률 (3:1 기준) | **25%** |

**손익분기 분석:**
```
필요 승률 = 1 / (1 + 손익비)
3:1 비율 → 1 / (1+3) = 25%
2.5:1 비율 → 1 / (1+2.5) = 28.6%
2:1 비율 → 1 / (1+2) = 33.3%
```

### 7.7 일반 리스크 규칙

| 규칙 | 기준 |
|------|------|
| 물타기 절대 금지 | 하락 종목에 추가 매수 금지 |
| 마진콜 대응 | 추가 입금 금지, 매도로 대응 |
| 마진 사용 | 강세장 초기 1~2년만, 약세장 즉시 해제 |
| 데이 트레이딩 | 금지 |
| 6개월+ 손실 보유 | 포트폴리오에 존재해서는 안 됨 |
| 옵션 비중 | 전체 자금의 **10~15% 이내** |

---

## 8. 업종 분석

### 8.1 IBD Industry Group Ranking

| 파라미터 | 값 |
|---------|-----|
| 총 업종 수 | **197개 그룹** |
| 측정 기간 | **6개월** 가격 성과 |
| 가중 방식 | 6개월 내 서로 다른 기간에 **별도 가중치** (최근에 더 비중) |
| 등급 | **A+ ~ E** (13개 등급) 또는 **1~99** 백분위 |

### 8.2 종목 선택 기준

| 기준 | 값 |
|------|-----|
| 업종 순위 | **상위 40위 이내** (197개 중) |
| 동반 상승 확인 | 같은 업종 내 **2~3개** 종목 동시 강세 |
| 방어적 업종 경고 | 금, 은, 유틸리티, 식품주 강세 → **시장 천장 경고** |

### 8.3 업종 상대강도 근사 계산

```python
def calculate_group_rs(group_stocks, lookback_days=126):
    """6개월(126 거래일) 업종 성과 계산"""
    group_returns = []
    for stock in group_stocks:
        ret = (stock.price[-1] / stock.price[-lookback_days]) - 1
        group_returns.append(ret)
    
    # 가중 평균 (시가총액 가중 또는 동일 가중)
    group_return = mean(group_returns)
    
    # 전체 197개 업종 대비 백분위
    return percentile_rank(group_return, all_group_returns)
```

---

## 9. 전체 상수 요약 (코드용)

```python
# ============================================================
# CANSLIM TRADING BOT - 정량화된 상수 전체
# ============================================================

# ---- 종목 선정 필터 ----
MIN_QUARTERLY_EPS_GROWTH = 0.25       # +25% YoY
IDEAL_QUARTERLY_EPS_GROWTH = 0.50     # +50% YoY
MIN_ANNUAL_EPS_CAGR = 0.25            # +25% (5년)
MIN_RS_RATING = 80                     # 1-99 스케일
SELL_RS_THRESHOLD = 70                 # RS < 70이면 매도
MIN_EPS_RATING = 80                    # 1-99 스케일
MIN_COMPOSITE_RATING = 90              # 1-99 스케일
MIN_INSTITUTIONAL_HOLDERS = 5          # 최소 기관 수
INSTITUTIONAL_OWNERSHIP_MIN = 0.10     # 10%
INSTITUTIONAL_OWNERSHIP_MAX = 0.60     # 60%
INST_QOQ_GROWTH_MIN = 0.10            # +10% QoQ
MAX_DEBT_TO_EQUITY = 2.0              # D/E 비율
IDEAL_DEBT_TO_EQUITY = 1.0            # 이상적 D/E
MIN_PRICE = 10.0                       # 최소 주가 $10
SPONSORSHIP_RATING_MIN = 'B'           # B+ 이상

# ---- 수급 (Supply/Demand) ----
MAX_SHARES_OUTSTANDING = 50_000_000    # 5천만주 (현대 보수적)
MIN_AVG_DAILY_VOLUME = 500_000         # 50만주/일
MIN_DOLLAR_VOLUME = 400_000            # $40만/일
VOLUME_AVG_PERIOD = 50                 # 50일 SMA
BREAKOUT_VOLUME_MULTIPLIER = 1.50      # +50% ADV
IDEAL_BREAKOUT_VOLUME = 2.00           # +100% ADV
VOLUME_DRYUP_THRESHOLD = 0.50          # ADV의 50% 미만
UP_DOWN_VOLUME_ACCUMULATION = 1.5      # U/D 비율 ≥ 1.5
UP_DOWN_VOLUME_DISTRIBUTION = 0.7      # U/D 비율 < 0.7

# ---- RS Rating 계산 ----
RS_WEIGHT_3M = 0.40                    # 3개월 40%
RS_WEIGHT_6M = 0.20                    # 6개월 20%
RS_WEIGHT_9M = 0.20                    # 9개월 20%
RS_WEIGHT_12M = 0.20                   # 12개월 20%
RS_TRADING_DAYS_3M = 63
RS_TRADING_DAYS_6M = 126
RS_TRADING_DAYS_9M = 189
RS_TRADING_DAYS_12M = 252

# ---- 시장 방향 (Market Direction) ----
# Distribution Day
DIST_DAY_DECLINE_PCT = -0.002          # -0.2%
DIST_DAY_VOLUME_VS = "PREVIOUS_DAY"    # 전일 대비
DIST_DAY_EXPIRY_DAYS = 25              # 25 거래일 후 만료
DIST_DAY_RALLY_REMOVAL = 0.05          # +5% 상승 시 제거
DIST_DAYS_WARNING = 3                   # 경고
DIST_DAYS_PRESSURE = 5                  # 압력
DIST_DAYS_TROUBLE = 6                   # 문제
DIST_DAYS_CORRECTION = 7               # 조정

# Stalling Day
STALLING_MAX_GAIN = 0.004              # +0.4%
STALLING_CLOSE_POSITION = "LOWER_HALF"  # 하단 50%
STALLING_MIN_VOLUME_PCT = 0.95          # 전일의 95%

# Follow-Through Day
FTD_MIN_DAY = 4                         # 최소 Day 4
FTD_OPTIMAL_MAX_DAY = 7                 # 최적 최대 Day 7
FTD_ABSOLUTE_MAX_DAY = 10               # 절대 최대 Day 10
FTD_MIN_GAIN = 0.0125                   # +1.25%
FTD_STRONG_GAIN = 0.017                 # +1.7%
FTD_IDEAL_GAIN = 0.02                   # +2.0%
FTD_VOLUME_VS = "PREVIOUS_DAY"          # 전일 대비

# Power Trend
PT_LOW_ABOVE_21EMA_DAYS = 10            # 10 연속 거래일
PT_21EMA_ABOVE_50SMA_DAYS = 5           # 5 연속 거래일
PT_CIRCUIT_BREAKER_PCT = -0.10          # -10%

# ---- 차트 패턴 ----
# Cup with Handle
CUP_MIN_DEPTH_PCT = 12.0               # -12%
CUP_MAX_DEPTH_NORMAL = 33.0            # -33%
CUP_MAX_DEPTH_VOLATILE = 50.0          # -50%
CUP_MIN_DURATION_DAYS = 35             # 7주
CUP_MAX_DURATION_DAYS = 325            # 65주
CUP_BOTTOM_ZONE_PCT = 0.20             # 하위 20%
CUP_MIN_DAYS_AT_BOTTOM = 10            # U자 판별: 최소 10일
HANDLE_MIN_DURATION_DAYS = 5            # 1주
HANDLE_MAX_DEPTH_PCT = 12.0             # -12%
HANDLE_MAX_RETRACEMENT_PCT = 33.0       # Cup advance의 33%
HANDLE_DRIFT_MIN_ANGLE = -15.0          # -15도
HANDLE_DRIFT_MAX_ANGLE = 1.0            # +1도
HANDLE_IDEAL_DRIFT_MIN = -8.0           # -8도
HANDLE_IDEAL_DRIFT_MAX = 0.0            # 0도
HANDLE_WEDGE_REJECT_ANGLE = 5.0         # +5도 이상 → 거부
PIVOT_OFFSET = 0.10                     # $0.10
BUY_ZONE_MAX_PCT = 0.05                 # +5%

# Double Bottom
DB_MIN_DURATION_DAYS = 35               # 7주
DB_MAX_DEPTH_PCT = 40.0                 # -40%
DB_MIDDLE_PEAK_MIN_RISE = 0.12          # 바닥 대비 +12%
DB_UNDERCUT_MAX_PCT = 0.10              # 10% 이내

# Flat Base
FLAT_BASE_MAX_OSCILLATION = 15.0        # 15%
FLAT_BASE_IDEAL_OSCILLATION = 12.0      # 12%
FLAT_BASE_MIN_DURATION_DAYS = 25        # 5주
FLAT_BASE_PRIOR_ADVANCE_MIN = 0.30      # +30%

# High Tight Flag
HTF_PRIOR_ADVANCE_MIN = 1.00            # +100%
HTF_PRIOR_ADVANCE_MAX = 1.20            # +120%
HTF_PRIOR_DURATION_DAYS = (20, 40)      # 4~8주
HTF_CORRECTION_DURATION = (15, 25)      # 3~5주
HTF_CORRECTION_DEPTH_MAX = 0.20         # -20%

# Base Stage
BASE_STAGE_ADVANCE_FOR_NEW = 0.20       # +20%면 새 단계
BASE_PRIOR_ADVANCE_MIN = 0.30           # +30% 사전 상승 필요
BASE_STAGE_MAX_SAFE = 2                 # 1~2차만 안전
BEAR_MARKET_DECLINE = -0.20             # -20% = 약세장 리셋

# ---- 매수 ----
BUY_ZONE_MAX = 0.05                     # Pivot +5% 이내
PYRAMID_ADD_1_TRIGGER = 0.025           # +2.5%
PYRAMID_ADD_2_TRIGGER = 0.05            # +5.0%
PYRAMID_SIZE_1 = 0.50                   # 50%
PYRAMID_SIZE_2 = 0.30                   # 30%
PYRAMID_SIZE_3 = 0.20                   # 20%

# 8주 보유 규칙
EIGHT_WEEK_RULE_GAIN = 0.20             # +20%
EIGHT_WEEK_RULE_WEEKS = 3               # 3주 이내 달성
EIGHT_WEEK_HOLD_WEEKS = 8               # 최소 8주 보유

# ---- 매도 (방어적) ----
STOP_LOSS_PCT = -0.08                   # -8%
SPLIT_STOP_HALF = -0.05                 # -5%에서 50% 매도
SPLIT_STOP_FULL = -0.10                 # -10%에서 나머지 매도
TRAILING_STOP_15_LEVEL = -0.05          # +15% 이후 → 매수가 -5%
PROFIT_PROTECTION_20 = 0.00             # +20% 이후 → 매수가 (손익분기)
EPS_DECEL_QUARTERS = 2                  # 2분기 연속 감속

# ---- 매도 (공격적) ----
CLIMAX_LOOKBACK_DAYS = 10               # 2~3주
CLIMAX_MIN_GAIN = 0.25                  # +25%
CLIMAX_MIN_UP_DAYS = 7                  # 10일 중 7일
CLIMAX_MIN_WEEKS_FROM_BUY = 18          # 최소 18주 경과
EXTENDED_FROM_200MA_WARN = 0.70         # +70%
EXTENDED_FROM_200MA_EXTREME = 1.00      # +100%
EXTENDED_FROM_50MA = 0.15               # +15%
NEW_HIGH_LOW_VOLUME_SIGNAL = True       # 신고가 + ADV 미달
CLOSE_AT_LOW_THRESHOLD = 0.25           # 하단 25%
CLOSE_AT_LOW_CONSECUTIVE = 2            # 2일 연속
KELTNER_EMA = 20                        # Keltner EMA 기간
KELTNER_ATR = 10                        # Keltner ATR 기간
KELTNER_MULTIPLIER = 2                  # ATR 배수
KELTNER_EXHAUSTION_DAYS = 6             # 6일 이상 이탈
STOCK_SPLIT_GAIN = 0.25                 # +25%
STOCK_SPLIT_DAYS = 10                   # 1~2주
NO_MOVEMENT_WEEKS = 13                  # 13주 무반응 → 매도
HEAVY_VOLUME_MULTIPLIER = 1.50          # 50% 이상
MA_10W_BREAKDOWN_VOLUME = 1.50          # 50% 이상
MA_10W_DECISIVE_BREAK = -0.02           # -2% 결정적 이탈

# ---- 포트폴리오 / 리스크 ----
MAX_POSITIONS = {
    5000: 2,      # <$5K → 2종목
    20000: 3,     # $5-20K → 3종목
    100000: 5,    # $20-100K → 4-5종목
    1000000: 7,   # $100K-1M → 6-7종목
}
MAX_RISK_PER_TRADE = 0.01               # 포트폴리오의 1%
MAX_PORTFOLIO_HEAT = 0.08               # 총 리스크 8%
EXPECTED_WIN_RATE = 0.35                # 35%
AVG_WINNER = 0.25                       # +25%
AVG_LOSER = -0.08                       # -8%
REWARD_RISK_RATIO = 3.0                 # 3:1

# 시장 상태별 투자 비중
EXPOSURE_MODEL = {
    'confirmed_uptrend_power': (0.80, 1.00),   # 80-100%
    'confirmed_uptrend': (0.75, 1.00),          # 75-100%
    'uptrend_under_pressure': (0.50, 0.75),     # 50-75%
    'uptrend_in_trouble': (0.25, 0.50),         # 25-50%
    'market_correction': (0.00, 0.25),           # 0-25%
    'rally_attempt': (0.00, 0.25),               # 0-25%
}

# ---- 업종 ----
INDUSTRY_GROUPS_TOTAL = 197             # IBD 업종 수
INDUSTRY_RS_LOOKBACK = 126              # 6개월
INDUSTRY_RANK_MAX = 40                  # 상위 40위 이내

# ---- 옵션 (참고) ----
OPTIONS_MAX_PORTFOLIO_PCT = 0.15        # 15%
OPTIONS_MIN_EXPIRY_MONTHS = 6           # 6개월+
OPTIONS_STOP_LOSS = -0.25               # -25%
OPTIONS_TAKE_PROFIT = 0.50              # +50%~+75%
```

---

## 부록 A: FTD 실패 확률 테이블

| FTD 후 일수 | Distribution 발생 시 실패 확률 |
|------------|-------------------------------|
| 1~2일 | 95% |
| 3일 | 70% |
| 4~5일 | 30% |
| 6~10일 | 정상 |
| FTD 저가 하회 | 90%+ |

## 부록 B: 손익분기 분석

| 승률 | 필요 손익비 | 예상 연간 수익 (100회 거래 기준) |
|------|-----------|-------------------------------|
| 25% | 3:1 이상 | 25 × 24% - 75 × 8% = 0% (손익분기) |
| 30% | 2.67:1 | 30 × 24% - 70 × 8% = +1.6% |
| 35% | 2.29:1 | 35 × 24% - 65 × 8% = +3.2% |
| 40% | 2:1 | 40 × 24% - 60 × 8% = +4.8% |
| 50% | 1:1 | 50 × 24% - 50 × 8% = +8.0% |

## 부록 C: 정량화 불가 항목 (정성적 판단 필요)

다음 항목은 완전한 정량화가 불가능하며 정성적 판단 또는 근사치를 사용해야 한다:

| 항목 | 이유 | 근사 접근법 |
|------|------|-----------|
| "혁신적 신제품" (N) | 주관적 판단 | 뉴스 센티먼트 분석 또는 수동 입력 |
| "새 경영진" (N) | 정성적 | SEC 8-K 파일링 감지 |
| "기관의 질" | IBD 독자 등급 의존 | IBD Sponsorship Rating API 필요 |
| "넓고 느슨한 패턴" | 시각적 판단 | 주간 변동폭 > 15% 기준 근사 |
| "기관이 사랑하는 종목" | 주관적 | 신규/청산 비율 + AUM 가중 |
| "시장 심리" (13번 매도 규칙) | 완전 정성적 | VIX, Put/Call ratio, AAII 센티먼트 근사 |
| "업종 방어적 전환" | 복합 판단 | 금/유틸리티 업종 RS 순위 급등 감지 |

---

*이 문서는 CANSLIM 트레이딩 봇의 모든 파라미터를 코드 구현 가능한 수준으로 정량화한 것입니다.*
*O'Neil 원전, IBD 공식 문서, Gil Morales/Chris Kacher 연구, Mark Minervini SEPA, 인터넷 검색을 종합하여 작성되었습니다.*
