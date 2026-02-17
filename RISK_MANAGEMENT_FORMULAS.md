# CANSLIM 리스크 관리 및 포지션 사이징 공식

> **참고 자료 종합**: William J. O'Neil (주식으로 돈 버는 법), Gil Morales & Chris Kacher (O'Neil 제자처럼 매매하라), Mark Minervini (SEPA/모멘텀 마스터즈), IBD 포트폴리오 관리 가이드라인

---

## 1. 초기 포지션 크기

### 1.1 포트폴리오 가치별 기본 포지션 크기

| 포트폴리오 규모 | 최대 종목 수 | 종목당 포지션 크기 |
|----------------|-----------------|-------------------------|
| < $3,000 | 2 종목 | 각 50% |
| $5,000 - $20,000 | 3 종목 | 각 33.3% |
| $20,000 - $100,000 | 4-5 종목 | 각 20-25% |
| $100,000 - $1,000,000 | 6-7 종목 | 각 14.3-16.7% |
| > $1,000,000 | 7-10 종목 | 각 10-14.3% |

**공식:**
```
Initial_Position_Size = Total_Portfolio_Value / Max_Positions
```

**예시 (포트폴리오 $100,000, 5개 포지션 기준):**
```
Initial_Position_Size = $100,000 / 5 = $20,000 (포트폴리오의 20%)
```

### 1.2 집중 투자 vs 분산 투자 철학

**O'Neil/IBD 접근법:**
- **집중 포트폴리오가 더 좋은 성과를 냄**: 4-7개 포지션이 이상적
- **최소 유효 포지션**: 포트폴리오의 20% (미수 거래 미사용 계좌 기준)
- **최대 단일 포지션**: 25-30% (미수 거래 없이)

**Morales/Kacher 공격적 접근법:**
- 최소 포지션 크기: **자본금의 30%**
- 동시 최대 3개 포지션
- 2:1 신용 거래 시: 포지션당 **총 자산의 최대 100%** (2개 종목 각각 100%)
- 역사적으로 레버리지를 활용하여 거래 자본의 15-25%를 포지션당 사용

**Minervini 보수적 접근법:**
- **거래당 최대 1% 위험** (위험 = 진입가에서 손절가까지의 거리)
- 2:1 보상/위험 비율 + 50% 승률 시 최적 포지션 크기: **포트폴리오의 25%**
- **최대 단일 포지션: 포트폴리오의 50%**
- **4-5개 종목에 각 5%씩** 분산 투자 또는 전액 신용 거래 시 8-10개 종목

---

## 2. Pyramiding(피라미딩) 규칙 - 수익 종목 추가 매수

### 2.1 포지션 추가 매수 시점

**1차 추가 매수 (2단계):**
```
조건: 최초 매수 지점 대비 +2.0% ~ +2.5% 상승
포지션 증가량: 초기 포지션 크기의 50%
새로운 합계: 원래 포지션의 150%
```

**2차 추가 매수 (3단계):**
```
조건: 최초 매수 지점 대비 +4.0% ~ +5.0% 상승
포지션 증가량: 2단계 추가분의 50% (원래의 25%)
새로운 합계: 원래 포지션의 175%
```

**예시:**
- 최초 매수: $20,000을 $50.00에 (400주)
- 1차 추가 $51.00 (+2%): $10,000을 $51.00에 (196주) → 합계: 596주, $30,000 투자
- 2차 추가 $52.50 (+5%): $5,000을 $52.50에 (95주) → 합계: 691주, $35,000 투자

### 2.2 피라미딩 제약 조건

**최대 매수 횟수:**
- **O'Neil**: 총 최대 3회 매수 (최초 + 추가 2회)
- **Morales**: 주가가 새로운 피벗을 형성하고 더 높은 가격에서 돌파할 때 추가 매수
- **Minervini**: 2R 수익 시에만 추가 매수 (초기 위험의 2배 수익이 발생했을 때)

**포지션 크기 감소 규칙:**
```
Add_Size = Previous_Add_Size × 0.5

또는 (점진적 감소):
최초: 100%
1차 추가: 최초의 75%
2차 추가: 최초의 50%
3차 추가: 최초의 25%
```

**피라미딩 후 최대 총 포지션:**
- **신용 거래 없이**: 전체 포트폴리오의 30-35%
- **2:1 신용 거래 시**: 총 자산의 최대 50%

### 2.3 피라미딩 매수 구간

**피벗 포인트(돌파 지점)에서 +5% 이상 추격 매수 절대 금지**

```python
# 피라미딩 매수 구간 유효성 검증
def is_valid_pyramid_add(current_price, initial_pivot, initial_entry):
    distance_from_pivot = (current_price - initial_pivot) / initial_pivot
    distance_from_entry = (current_price - initial_entry) / initial_entry
    
    # 수익 상태여야 함
    if distance_from_entry < 0.02:  # +2% 미만
        return False
    
    # 과도하게 올라가면 안 됨
    if distance_from_pivot > 0.05:  # 피벗 대비 +5% 초과
        return False
        
    return True
```

---

## 3. 리스크 관리: 포트폴리오 열 지수

### 3.1 포지션별 위험

**O'Neil 기준:**
```
Max_Loss_Per_Position = Entry_Price × 0.07 ~ 0.08
Position_Risk = Position_Size × 0.08
```

**예시 (20% 포지션, -8% 손절):**
```
포트폴리오 가치: $100,000
포지션 크기: $20,000 (20%)
최대 손실: $20,000 × 0.08 = $1,600 (전체 포트폴리오의 1.6%)
```

**Minervini 기준:**
```
Risk_Per_Share = Entry_Price - Stop_Loss_Price
Max_Risk_Dollar = Portfolio_Value × 0.01  # 최대 위험 1%
Position_Size = Max_Risk_Dollar / Risk_Per_Share
```

**예시 (Minervini 1% 위험 방법):**
```
포트폴리오: $100,000
최대 위험: $100,000 × 0.01 = $1,000
진입가: $50.00
손절가: $46.00
주당 위험: $4.00
포지션 크기 = $1,000 / $4.00 = 250주 ($12,500 포지션 = 포트폴리오의 12.5%)
```

### 3.2 총 포트폴리오 열 지수 (최대 동시 위험)

**공식:**
```
Total_Portfolio_Heat = Sum(Position_Risk_i) (모든 오픈 포지션에 대해)
Max_Portfolio_Heat = Portfolio_Value × Max_Heat_Percentage
```

**O'Neil/IBD 접근법:**
- **5개 포지션**을 각 20%씩, 포지션당 -8% 위험 시:
  ```
  Total Heat = 5 × (0.20 × 0.08) = 5 × 0.016 = 0.08 (포트폴리오 위험 8%)
  ```

- **4개 포지션**을 각 25%씩, 포지션당 -7% 위험 시:
  ```
  Total Heat = 4 × (0.25 × 0.07) = 4 × 0.0175 = 0.07 (포트폴리오 위험 7%)
  ```

**Minervini 접근법:**
- 5개 포지션에 **포지션당 1% 위험**:
  ```
  Total Heat = 5 × 0.01 = 0.05 (포트폴리오 위험 5%)
  ```

**권장 최대 포트폴리오 열 지수:**
- **보수적**: 전체 포트폴리오의 5-7%
- **보통**: 전체 포트폴리오의 8-10%
- **공격적**: 전체 포트폴리오의 12-15% (신용 거래 포함)

---

## 4. 시장 상황별 현금 배분

### 4.1 시장 상태 정의

| 시장 상태 | 정의 | 현금 비중 | 주식 비중 |
|--------------|------------|--------|----------|
| **확인된 상승 추세** | 랠리 시도 3-10일 차에 FTD(Follow-Through Day, 추세 확인일) 발생; 주도주 돌파 중; 매도 집중일 수 < 4 | 0-25% | 75-100% |
| **압박받는 상승 추세** | 25일 내 4-5개의 매도 집중일; 주도주가 저항선에서 실패; 불안정한 움직임 | 25-50% | 50-75% |
| **위기의 상승 추세** | 6개 이상의 매도 집중일; 대량 거래량과 함께 강한 매도; 주도주 붕괴 | 50-75% | 25-50% |
| **시장 조정** | 주요 지수가 대량 거래량과 함께 50일 이동평균 하회; 아직 FTD 미발생; 광범위한 하락 | 75-100% | 0-25% |
| **약세장** | 지속적인 하락 추세; 지수가 200일 이동평균 하회; 매도 집중일 압도적 | 100% | 0% |

### 4.2 정밀 시장 상태 트리거

**확인된 상승 추세 진입:**
```python
def is_confirmed_uptrend(rally_day, current_day, volume_ratio, price_gain_pct):
    days_since_rally = current_day - rally_day
    
    # FTD는 3-10일 차에 발생해야 함
    if days_since_rally < 3 or days_since_rally > 10:
        return False
    
    # 거래량이 증가해야 함
    if volume_ratio < 1.0:
        return False
    
    # 가격 상승이 +1.0% 이상이어야 함 (결정적 상승)
    if price_gain_pct < 1.0:
        return False
        
    return True
```

**Distribution Day(매도 집중일) 감지:**
```python
def is_distribution_day(price_change_pct, volume_ratio):
    # 가격: 하락 또는 상승했지만 정체
    price_down = price_change_pct < 0
    price_stalling = 0 < price_change_pct < 0.2  # 상승했지만 미미한 상승폭
    
    # 거래량이 전일보다 높아야 함
    volume_up = volume_ratio > 1.0
    
    if volume_up and (price_down or price_stalling):
        return True
    return False

def count_distribution_days(last_25_days):
    # 최근 25거래일 내의 매도 집중일만 집계
    # 해당일 종가 대비 지수가 +6% 이상 상승하면 매도 집중일 무효화
    active_dist_days = 0
    for day in last_25_days:
        if day.is_distribution:
            if not day.invalidated_by_rally:
                active_dist_days += 1
    return active_dist_days
```

### 4.3 노출도 단계적 축소 모델

**공격적 스케일 (Morales/Kacher):**
```
확인된 상승 추세: 100% 투자 (신용 거래 시: 최대 200%)
매도 집중일 4일: 75% 투자
매도 집중일 5일: 50% 투자
매도 집중일 6일 이상: 25% 투자 또는 0% (전액 현금)
```

**보수적 스케일 (Minervini/O'Neil):**
```
확인된 상승 추세 + 강한 주도주: 100% 투자
상승 추세 + 불안정한 움직임: 75% 투자
혼합 신호 (매도 집중일 4-5일): 50% 투자
대량 매도 (매도 집중일 6일 이상): 25% 투자
조정 확인: 0% 투자 (전액 현금)
```

**단계적 축소 트리거:**
```python
def calculate_market_exposure(dist_day_count, ftd_confirmed, leading_stocks_count):
    if not ftd_confirmed:
        return 0.0  # 0% - 현금 보유 유지
    
    if dist_day_count >= 6:
        return 0.25  # 25% 이하
    elif dist_day_count >= 5:
        return 0.50  # 50%
    elif dist_day_count >= 4:
        return 0.75  # 75%
    else:
        # 주도주 확인
        if leading_stocks_count >= 3:
            return 1.0  # 100%
        else:
            return 0.75  # 75%
```

---

## 5. 피라미딩 크기 축소 공식

### 5.1 점진적 축소 방법

**방법 A: 일정 비율 50% 축소**
```
Position_1 = Base_Size × 1.0
Position_2 = Base_Size × 0.5
Position_3 = Base_Size × 0.25
```

**방법 B: 점진적 비율 축소**
```
Position_1 = Base_Size × 1.00  (100%)
Position_2 = Base_Size × 0.75  (75%)
Position_3 = Base_Size × 0.50  (50%)
Position_4 = Base_Size × 0.25  (25%)
```

**예시 (기본 = $20,000):**

방법 A:
- 최초: $20,000
- 추가 1: $10,000
- 추가 2: $5,000
- **합계: $35,000 (기본의 175%)**

방법 B:
- 최초: $20,000
- 추가 1: $15,000
- 추가 2: $10,000
- 추가 3: $5,000
- **합계: $50,000 (기본의 250%)**

### 5.2 위험 조정 포지션 사이징

**변동성 조정 방법:**
```python
def calculate_pyramid_size(base_size, volatility, market_regime):
    """
    주가 변동성과 시장 국면에 따라 피라미딩 추가 매수량 조정
    """
    # 변동성 조정 (가격 대비 ATR 비율)
    if volatility < 2.0:  # 낮은 변동성
        vol_multiplier = 1.0
    elif volatility < 4.0:  # 중간 변동성
        vol_multiplier = 0.75
    else:  # 높은 변동성
        vol_multiplier = 0.5
    
    # 시장 국면 조정
    if market_regime == "confirmed_uptrend":
        regime_multiplier = 1.0
    elif market_regime == "uptrend_pressure":
        regime_multiplier = 0.75
    else:
        regime_multiplier = 0.0  # 약한 시장에서는 피라미딩 금지
    
    adjusted_size = base_size * vol_multiplier * regime_multiplier
    return adjusted_size
```

---

## 6. 승률 및 보상/위험 비율

### 6.1 역사적 승률 통계

**O'Neil/CANSLIM 시스템:**
- **예상 승률**: 30-40% (과반수 매매가 수익이 아님)
- **역사적 현실**: "3할 타율" (30%)이면 허용 가능
- **핵심 통찰**: 소수의 큰 수익 종목 (100%+ 수익)이 다수의 작은 손실 (-7-8%)을 상쇄

**Morales/Kacher:**
- 승률을 명시적으로 제시하지 않음
- 100-500%+ 수익이 가능한 "초고성과 종목"에 집중
- 큰 수익 종목의 이익을 극대화하기 위해 공격적 스케일링 사용

**Minervini:**
- **목표 승률**: 50% 이상 (SEPA 시스템 기준)
- **실제 승률**: 보상/위험 비율이 높으면 35-40%까지 낮아도 가능
- 최소 2:1 또는 3:1 보상/위험 비율에 집중

### 6.2 보상/위험 비율 요건

**평균 수익 vs 평균 손실:**
```
O'Neil 시스템:
- 평균 손실: -7% ~ -8%
- 평균 수익: +20% ~ +25% (최소)
- 최고 수익: +100% ~ +500%+ (8주 보유 규칙 적용 시)

비율:
- 최소: +20% / -8% = 2.5:1
- 일반적: +30% / -7% = 4.3:1
- 초고성과: +200% / -8% = 25:1
```

**Minervini 시스템:**
```
- 평균 손실: -5% ~ -8%
- 평균 수익: +15% ~ +30%
- 최고 수익: +50% ~ +200%+

비율:
- 최소: 2:1 (승률 50% 시)
- 목표: 3:1 (승률 40% 시)
- 최적: 4:1+ (승률 35% 시)
```

### 6.3 손익분기 분석

**공식:**
```
Win_Rate_Required = 1 / (1 + Reward_Risk_Ratio)
```

**손익분기 승률:**
```
1:1 비율 → 필요 승률 50%
2:1 비율 → 필요 승률 33.3%
3:1 비율 → 필요 승률 25%
4:1 비율 → 필요 승률 20%
5:1 비율 → 필요 승률 16.7%
```

**예시:**
매 거래마다 -8%를 감수하고 평균 수익이 +24%인 경우:
```
보상/위험 = 24 / 8 = 3:1
필요 승률 = 1 / (1 + 3) = 25%

실제 승률 30%, 3:1 비율일 때:
기대값 = (0.30 × 3) - (0.70 × 1) = 0.9 - 0.7 = +0.2R (거래당)
```

### 6.4 CANSLIM 기대값 모델

**시나리오: 5회 거래, 승률 40%, 평균 손실 -8%, 평균 수익 +25%**

| 거래 | 결과 | 손익 ($20k 포지션) | 포트폴리오 영향 |
|-------|---------|---------------------|------------------|
| 1 | 수익 | +$5,000 | +5% |
| 2 | 손실 | -$1,600 | -1.6% |
| 3 | 손실 | -$1,600 | -1.6% |
| 4 | 수익 | +$5,000 | +5% |
| 5 | 손실 | -$1,600 | -1.6% |
| **합계** | **2승, 3패** | **+$5,200** | **+5.2%** |

**거래당 기대값:**
```
EV = (Win_Rate × Avg_Win) + (Loss_Rate × Avg_Loss)
EV = (0.40 × 0.25) + (0.60 × -0.08)
EV = 0.10 - 0.048 = +0.052 (포지션당 +5.2%)
```

**1년간 5개 순차 포지션 운영 시:**
```
연간 수익률 = (1 + 0.052)^5 - 1 = 29.1%
```

---

## 7. Stop Loss(손절) 조정 규칙

### 7.1 초기 손절가

**진입 즉시 설정:**
```python
def calculate_initial_stop(entry_price, method="oneil"):
    if method == "oneil":
        stop_loss = entry_price * 0.92  # -8% 손절
    elif method == "oneil_strict":
        stop_loss = entry_price * 0.93  # -7% 손절
    elif method == "minervini":
        stop_loss = entry_price * 0.95  # -5% 손절
    return stop_loss
```

### 7.2 추적 손절 규칙

**+15% 규칙 (O'Neil):**
```
If position_gain >= 0.15:
    new_stop = max(entry_price * 0.95, current_stop)  # -5% 이상으로 이동
```

**+20% 규칙 (O'Neil):**
```
If position_gain >= 0.20:
    new_stop = max(entry_price * 1.0, current_stop)  # 손익분기점 이상으로 이동
    # +20% 수익이었던 종목을 절대 손실로 만들지 않는다
```

**2R 규칙 (Minervini):**
```
If position_gain >= (initial_risk * 2):
    new_stop = entry_price  # 손익분기점으로 이동
```

**10주 이동평균 규칙 (다이나믹 리더):**
```
# 강한 2단계 상승 추세에 있는 종목 대상
If position_gain >= 0.20 and weeks_held >= 8:
    new_stop = ten_week_moving_average
    # 거래량을 동반한 주봉이 10주 이동평균선을 하회할 때까지 보유
```

### 7.3 손절가 조정 알고리즘

```python
def adjust_stop_loss(entry_price, current_price, initial_stop, weeks_held):
    gain_pct = (current_price - entry_price) / entry_price
    initial_risk = entry_price - initial_stop
    
    # +20% 규칙: 절대 손실 종목으로 만들지 않음
    if gain_pct >= 0.20:
        return max(entry_price, initial_stop)
    
    # +15% 규칙: 손절가를 -5%로 상향
    elif gain_pct >= 0.15:
        return max(entry_price * 0.95, initial_stop)
    
    # 2R 규칙: 손익분기점으로 이동
    elif (current_price - entry_price) >= (initial_risk * 2):
        return entry_price
    
    # 8주 보유 규칙: 다이나믹 리더에는 10주 이동평균 사용
    elif gain_pct >= 0.20 and weeks_held >= 8:
        return calculate_10week_ma(current_price)
    
    # 그 외에는 초기 손절가 유지
    else:
        return initial_stop
```

---

## 8. 포트폴리오 구성 예시

### 8.1 보수적 포트폴리오 ($100,000)

**구성:**
- 5개 포지션, 각 20%
- 포지션당 -7% 손절
- 신용 거래 없음

**위험 프로필:**
```
포지션 크기: 각 $20,000
포지션당 위험: $20,000 × 0.07 = $1,400 (포트폴리오의 1.4%)
총 포트폴리오 열 지수: 5 × $1,400 = $7,000 (포트폴리오의 7%)
현금 보유: $0 (0%) - 상승 추세 시 전액 투자
```

**배분:**
| 종목 | 포지션 크기 | 손절가 | 위험 금액 | 위험 비율 |
|-------|---------------|-----------|--------|--------|
| 종목 A | $20,000 | -7% | $1,400 | 1.4% |
| 종목 B | $20,000 | -7% | $1,400 | 1.4% |
| 종목 C | $20,000 | -7% | $1,400 | 1.4% |
| 종목 D | $20,000 | -7% | $1,400 | 1.4% |
| 종목 E | $20,000 | -7% | $1,400 | 1.4% |
| **합계** | **$100,000** | | **$7,000** | **7%** |

### 8.2 피라미딩을 활용한 공격적 포트폴리오 ($100,000)

**구성:**
- 4개 초기 포지션, 각 20%
- 최고 성과 2개 종목을 각 30%까지 피라미딩
- -8% 손절
- 2:1 신용 거래 가능

**초기 구성:**
```
종목 A: $20,000 (20%)
종목 B: $20,000 (20%)
종목 C: $20,000 (20%)
종목 D: $20,000 (20%)
현금: $20,000 (20% 예비)
```

**피라미딩 후 (종목 A와 B가 강세를 보일 때):**
```
종목 A: $30,000 (30%) - +2.5%에서 $10k 추가 매수
종목 B: $30,000 (30%) - +2%에서 $10k 추가 매수
종목 C: $20,000 (20%) - 보유 중
종목 D: $20,000 (20%) - 손절 처리됨
종목 E: $0 - 매수 대기 중
현금: $0 (전액 투자)

총 투자: $100,000
총 열 지수: (30k × 0.08) + (30k × 0.08) + (20k × 0.08) = $6,400 (6.4%)
```

### 8.3 Minervini 1% 위험 포트폴리오 ($100,000)

**구성:**
- 손절 거리에 따른 가변 포지션 크기
- 포지션당 최대 1% 위험
- 목표 5개 포지션

**포지션 예시:**

| 종목 | 진입가 | 손절가 | 주당 위험 | 최대 위험 금액 | 주식 수 | 포지션 금액 | 포지션 비율 |
|-------|-------|------|------------|------------|--------|------------|------------|
| 종목 A | $50 | $47 | $3 | $1,000 | 333 | $16,650 | 16.7% |
| 종목 B | $100 | $92 | $8 | $1,000 | 125 | $12,500 | 12.5% |
| 종목 C | $25 | $23 | $2 | $1,000 | 500 | $12,500 | 12.5% |
| 종목 D | $75 | $71 | $4 | $1,000 | 250 | $18,750 | 18.8% |
| 종목 E | $40 | $38 | $2 | $1,000 | 500 | $20,000 | 20.0% |
| **합계** | | | | **$5,000** | | **$80,400** | **80.4%** |

```
총 포트폴리오 열 지수: $5,000 (포트폴리오의 5%)
현금 보유: $19,600 (19.6%)
```

---

## 9. 구현 체크리스트

### 9.1 매매 전 위험 계산

```python
class PositionSizer:
    def __init__(self, portfolio_value, max_positions, risk_method="oneil"):
        self.portfolio_value = portfolio_value
        self.max_positions = max_positions
        self.risk_method = risk_method
    
    def calculate_position_size(self, entry_price, stop_loss_price=None):
        if self.risk_method == "oneil":
            # 고정 비율 방법
            base_size = self.portfolio_value / self.max_positions
            if stop_loss_price is None:
                stop_loss_price = entry_price * 0.92  # 기본 -8%
            return base_size, stop_loss_price
        
        elif self.risk_method == "minervini":
            # 위험 기반 방법 (최대 위험 1%)
            max_risk_dollar = self.portfolio_value * 0.01
            risk_per_share = entry_price - stop_loss_price
            shares = max_risk_dollar / risk_per_share
            position_size = shares * entry_price
            return position_size, stop_loss_price
    
    def validate_pyramid_add(self, current_price, initial_entry, pivot_price):
        # 진입가 대비 +2% 이상이어야 함
        gain = (current_price - initial_entry) / initial_entry
        if gain < 0.02:
            return False, "피라미딩을 위한 수익 부족 (+2% 필요)"
        
        # 피벗 대비 +5% 초과하면 안 됨
        extension = (current_price - pivot_price) / pivot_price
        if extension > 0.05:
            return False, "피벗 대비 과도하게 상승 (최대 +5%)"
        
        return True, "유효한 피라미딩 구간"
    
    def calculate_portfolio_heat(self, positions):
        total_heat = 0
        for pos in positions:
            risk_dollar = pos['size'] * abs(pos['entry'] - pos['stop']) / pos['entry']
            total_heat += risk_dollar
        
        heat_percentage = total_heat / self.portfolio_value
        return heat_percentage
```

### 9.2 일일 위험 모니터링

**매일 장 마감 전 점검 사항:**
1. 현재 포트폴리오 열 지수 계산
2. 모든 손절이 설정되어 있고 활성화되어 있는지 확인
3. 각 포지션과 손절가 사이의 거리 확인
4. 최근 25일 내 매도 집중일 수 집계
5. 시장 국면 평가 (상승 추세, 압박, 조정)
6. 현재 현금 비중 계산
7. 피라미딩 가능한 포지션 식별
8. +15% 또는 +20% 수익에 근접한 포지션 검토 (손절가 조정)

### 9.3 포지션 진입 체크리스트

포지션 진입 전 확인 사항:
- [ ] 종목이 모든 CAN SLIM 기준을 충족하는가
- [ ] 시장이 확인된 상승 추세인가 (FTD 발생 여부)
- [ ] 매도 집중일 수가 4 미만인가
- [ ] 포지션 크기가 계산되었는가 (포트폴리오의 25% 이하)
- [ ] 손절가가 계산되었는가 (-7% ~ -8%)
- [ ] 이 포지션 추가 후에도 포트폴리오 열 지수가 10% 미만인가
- [ ] 매수가 피벗 포인트 또는 피벗 대비 +5% 이내인가
- [ ] 돌파 거래량이 평균 대비 +50% 이상인가
- [ ] 현금 보유 비중이 현재 시장 국면에 적합한가

---

## 10. 성과 추적 공식

### 10.1 핵심 성과 지표

**승률:**
```
Win_Rate = Winning_Trades / Total_Trades
```

**평균 수익/손실:**
```
Avg_Win = Sum(Winning_Trade_%) / Count(Winning_Trades)
Avg_Loss = Sum(Losing_Trade_%) / Count(Losing_Trades)
```

**수익 팩터:**
```
Profit_Factor = Gross_Profit / Gross_Loss
목표: >= 2.0
우수: >= 3.0
```

**기대값:**
```
Expectancy = (Win_Rate × Avg_Win) - (Loss_Rate × Avg_Loss)
목표: >= 0.05 (거래당 5%)
```

**최대 낙폭:**
```
Max_Drawdown = (Peak_Portfolio_Value - Trough_Value) / Peak_Portfolio_Value
목표: < 20%
```

### 10.2 CANSLIM 시스템 벤치마크

**허용 가능한 성과:**
- 승률: 30-50%
- 수익 팩터: 2.0-3.0
- 평균 수익: +20% ~ +30%
- 평균 손실: -7% ~ -8%
- 기대값: 거래당 +4% ~ +6%
- 연간 수익률: 20-40%

**우수한 성과:**
- 승률: 40-60%
- 수익 팩터: 3.0-5.0
- 평균 수익: +30% ~ +50%+
- 평균 손실: -5% ~ -7%
- 기대값: 거래당 +8% ~ +12%
- 연간 수익률: 40-60%+

**O'Neil 역사적 성과:**
- 25년 수익률: +5,000% (연평균 복리 수익률 20%)
- 1962-1963: +4,000% ($5k에서 2년 만에 $200k)
- 평균 연간 수익률: 40%+

---

## 요약: 핵심 공식 빠른 참조

```
포지션 사이징:
├─ 초기 크기 = Portfolio_Value / Max_Positions (4-7개)
├─ 일반적 = 포지션당 20-25%
└─ Minervini = Max_Risk_$ / (Entry - Stop)

피라미딩:
├─ 1차 추가: 진입가 대비 +2.0% ~ +2.5%
├─ 2차 추가: 진입가 대비 +4.0% ~ +5.0%
├─ 크기: 각 추가 = 이전 추가의 50%
└─ 최대 구간: 피벗 포인트 대비 +5% 이내

위험:
├─ 손절 = 포지션당 -7% ~ -8%
├─ 포지션별 위험 = Position_Size × 0.08
├─ 포트폴리오 열 지수 = 모든 포지션 위험의 합계
├─ 목표 열 지수 = 전체 포트폴리오의 5-8%
└─ 최대 열 지수 = 전체 포트폴리오의 10-12%

현금 배분:
├─ 확인된 상승 추세: 현금 0-25% (75-100% 투자)
├─ 압박받는 상승 추세: 현금 25-50% (50-75% 투자)
├─ 위기의 상승 추세: 현금 50-75% (25-50% 투자)
└─ 조정/약세장: 현금 75-100% (0-25% 투자)

승패 통계:
├─ 예상 승률: 30-50%
├─ 평균 수익: +20% ~ +30%
├─ 평균 손실: -7% ~ -8%
├─ 보상/위험: 2.5:1 ~ 4:1
└─ 기대값: 거래당 +4% ~ +6%
```

---

**공식 문서 끝**

*이 문서는 CANSLIM 트레이딩 봇 구현을 위해 William J. O'Neil, Gil Morales, Chris Kacher, Mark Minervini의 정확한 포지션 사이징, 리스크 관리, 피라미딩 공식을 종합한 것입니다.*
