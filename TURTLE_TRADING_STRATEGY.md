# CANSLIM × 터틀 트레이딩 하이브리드 전략 명세서

> **목적**: CANSLIM의 펀더멘털 종목 선정 능력과 터틀 트레이딩의 기계적 매매 규율을 결합한 하이브리드 시스템
> **원칙**: 종목 선정 = CANSLIM, 진입·청산·리스크 관리 = 터틀 트레이딩 (100% 기계적)
> **출처**: Richard Dennis & William Eckhardt 터틀 트레이딩 원전, Curtis Faith "Way of the Turtle", William O'Neil CANSLIM
> **참조**: `QUANTIFIED_STRATEGY.md` (CANSLIM 종목 선정 상수)
> **작성일**: 2026-02-14

---

## 목차

0. [전략 개요 및 설계 철학](#0-전략-개요-및-설계-철학)
1. [종목 선정 (CANSLIM 기준 — 기존 유지)](#1-종목-선정-canslim-기준--기존-유지)
2. [시장 방향 필터 (간소화)](#2-시장-방향-필터-간소화)
3. [ATR(N) 계산 — 핵심 변수](#3-atrn-계산--핵심-변수)
4. [포지션 사이징 (터틀 유닛 시스템)](#4-포지션-사이징-터틀-유닛-시스템)
5. [진입 규칙 (Donchian Channel 돌파)](#5-진입-규칙-donchian-channel-돌파)
6. [피라미딩 (추가 진입)](#6-피라미딩-추가-진입)
7. [손절 (Stop Loss)](#7-손절-stop-loss)
8. [청산 (Exit) 규칙](#8-청산-exit-규칙)
9. [포지션 한도 (리스크 관리)](#9-포지션-한도-리스크-관리)
10. [전체 상수 요약 (코드용)](#10-전체-상수-요약-코드용)
11. [CANSLIM 순수 전략과의 비교표](#11-canslim-순수-전략과의-비교표)
- [부록 A: 터틀 트레이딩 원전 출처](#부록-a-터틀-트레이딩-원전-출처)
- [부록 B: 하이브리드 전략의 예상 성과 특성](#부록-b-하이브리드-전략의-예상-성과-특성)

---

## 0. 전략 개요 및 설계 철학

### 0.1 왜 하이브리드인가

이 전략은 두 가지 검증된 투자 방법론의 **각각 가장 강한 영역**만을 결합한다:

| 역할 | 방법론 | 이유 |
|------|--------|------|
| **어떤 종목을 살 것인가** | CANSLIM | 70년간 검증된 성장주 선별 능력. 펀더멘털+수급+업종 분석으로 "될 놈"을 골라냄 |
| **언제, 얼마나, 어떻게 사고팔 것인가** | 터틀 트레이딩 | 감정 개입 제로. 모든 매매 결정이 숫자로 사전 정의됨. 40년간 추세추종 시장에서 검증 |

**핵심 통찰**: CANSLIM은 종목 선정에서 탁월하지만, 매매 실행에서 주관적 판단(피벗 포인트 해석, 차트 패턴 인식, 클라이맥스 탑 감지)을 상당 부분 요구한다. 터틀 트레이딩은 매매 실행이 100% 기계적이지만, 종목 선정 없이 "모든 시장"에 진입하므로 필터링이 없다. 이 두 약점을 상대방의 강점으로 보완한다.

### 0.2 순수 CANSLIM 대비 핵심 차이점

이 하이브리드 전략에서 **CANSLIM의 다음 요소는 사용하지 않는다**:

| 미사용 CANSLIM 요소 | 대체 | 이유 |
|---------------------|------|------|
| 피벗 포인트 진입 (Cup & Handle, Double Bottom 등) | Donchian Channel 돌파 | 차트 패턴 인식의 주관성 제거. 돌파는 숫자 하나로 결정됨 |
| -8% 절대 손절 | min(2N, 10%) 하이브리드 손절 | 변동성 기반 손절 + 최대 10% 캡으로 극단적 손실 방지 |
| 클라이맥스 탑 / 기술적 매도 신호 | 10일/20일 저가 이탈 청산 | 단순하고 기계적. 해석 불필요 |
| FTD / Distribution Day 시장 판단 | 200일 이동평균 필터 | 터틀의 기계적 성격에 맞는 단순한 시장 필터 |
| 50/30/20 피라미딩 | 1/2 N 간격 피라미딩 | 변동성 기반 추가 진입이 더 체계적 |
| 8주 보유 규칙 | 해당 없음 | 터틀 청산룰이 보유 기간을 자동으로 결정 |

### 0.3 순수 터틀 대비 핵심 차이점

이 하이브리드 전략에서 **터틀의 다음 요소를 변경했다**:

| 변경 터틀 요소 | 원전 | 변경 내용 | 이유 |
|---------------|------|----------|------|
| 종목 유니버스 | 모든 선물/상품 시장 | CANSLIM 필터를 통과한 주식만 | 무차별 진입 대신 펀더멘털 우량주에 집중 |
| 공매도 | 기본 활성 | 기본 비활성 (선택적) | 개별 주식 공매도는 리스크가 선물과 다름 |
| 시장 수 | 수십 개 선물 시장 동시 | CANSLIM으로 필터링된 소수 종목 | 품질 > 수량 |

### 0.4 200일 이동평균 시장 필터의 근거

CANSLIM의 FTD/Distribution Day 시스템 대신 200일 MA를 사용하는 이유:

1. **개별 주식은 시장과 높은 상관관계를 가진다** — S&P 500이 약세장일 때 개별 종목이 상승세를 유지하기 극히 어렵다. 역사적으로 약세장에서 주식의 75% 이상이 동반 하락한다.
2. **Long-only 전략은 보호 장치가 필요하다** — 선물 시장의 터틀 시스템은 롱/숏 양방향으로 약세장에서도 수익을 낼 수 있지만, 주식 롱 온리 시스템은 약세장 회피가 필수적이다.
3. **터틀의 기계적 성격과 일치한다** — FTD/Distribution Day 시스템은 복수의 조건을 추적하고 상태 머신을 유지해야 하지만, 200일 MA는 "종가 > MA200? Yes/No" 한 줄로 판단 가능하다.
4. **40년 이상 검증된 필터** — 200일 MA 위에서만 매수하는 전략은 Mebane Faber(2006), Jeremy Siegel 등 다수의 연구에서 하방 리스크 감소 효과가 입증되었다.

### 0.5 전략 한 줄 요약

> **CANSLIM으로 골라서, 터틀로 사고판다.**
>
> 매 거래일: CANSLIM 필터 통과 종목 중 → 200일 MA 위의 시장에서 → Donchian 채널 돌파 시 → Minervini 리스크 기반 유닛 사이즈로 진입 → 1/2 N마다 피라미딩 → min(2N, 10%) 손절 또는 10일/20일 저가 이탈 시 전량 청산

---

## 1. 종목 선정 (CANSLIM 기준 — 기존 유지)

> **참조**: 종목 선정의 모든 상세 기준과 계산 공식은 `QUANTIFIED_STRATEGY.md`에 정의되어 있다.
> 이 섹션은 핵심 임계값만 요약하며, **선정 기준만 사용하고 CANSLIM의 매매 규칙은 사용하지 않는다**.

### 1.1 CANSLIM 필터 요약

| 항목 | 기준 | 핵심 임계값 | 필수 여부 |
|------|------|-----------|----------|
| **C** (Current Quarterly EPS) | 분기 EPS 성장률 (YoY) | **≥ +25%** (이상적: +50%~+100%) | 필수 |
| **A** (Annual Earnings) | 연간 EPS 성장률 (5년 CAGR) | **≥ +25%** | 필수 |
| **N** (New) | 52주 신고가 근접 여부 | 적절한 베이스에서 신고가 영역 | 필수 |
| **S** (Supply/Demand) | 수급 분석 | 돌파 거래량 ≥ ADV×1.50, U/D Ratio ≥ 1.5 | 필수 |
| **L** (Leader) | 상대강도 | RS Rating **≥ 80** | 필수 |
| **I** (Institutional) | 기관 투자자 | 보유 기관 ≥ 5개, QoQ +10% 증가 | 필수 |

### 1.2 추가 선정 임계값

| 파라미터 | 값 |
|---------|-----|
| EPS Rating | **≥ 80** (1-99 스케일) |
| Composite Rating | **≥ 90** (1-99 스케일) |
| 최소 주가 | **$10 이상** |
| 최소 일평균 거래량 | **500,000주/일** |
| 최소 달러 거래량 | **$400,000/일** |
| 부채비율 (D/E) | **≤ 2.0** (이상적: ≤ 1.0) |
| 업종 순위 | **상위 40위** (197개 IBD 업종 중) |
| Acc/Dist Rating | **A 또는 B** |

### 1.3 Minervini Trend Template (보조 필터)

CANSLIM 선정 이후 추가 품질 확인:

| # | 조건 | 기준 |
|---|------|------|
| 1 | 현재가 > 50일 SMA | 필수 |
| 2 | 현재가 > 150일 SMA | 필수 |
| 3 | 현재가 > 200일 SMA | 필수 |
| 4 | 50일 SMA > 150일 SMA | 필수 |
| 5 | 150일 SMA > 200일 SMA | 필수 |
| 6 | 200일 SMA 상승 추세 (1개월+) | 필수 |
| 7 | 52주 고가 대비 -25% 이내 | 필수 |
| 8 | 52주 저가 대비 +30% 이상 | 필수 |

### 1.4 중요한 구분: 선정 ≠ 진입

CANSLIM 필터를 통과했다고 즉시 매수하지 않는다. CANSLIM의 역할은 여기서 끝난다.

- ❌ CANSLIM 피벗 포인트에서 진입하지 않는다
- ❌ CANSLIM 차트 패턴(Cup, Double Bottom 등) 돌파를 진입 신호로 쓰지 않는다
- ❌ CANSLIM 돌파 거래량 조건을 진입 조건으로 쓰지 않는다

→ 진입은 **섹션 5의 Donchian Channel 돌파**에서만 결정된다.

CANSLIM 필터를 통과한 종목은 **"관심 종목 풀(Watch List)"**에 등록되고, 이후 Donchian 돌파 신호를 기다린다.

---

## 2. 시장 방향 필터 (간소화)

### 2.1 설계 원칙

터틀 트레이딩의 기계적 특성에 맞추어, 시장 방향 판단을 **단일 지표**로 간소화한다. CANSLIM의 FTD/Distribution Day 상태 머신(5개 상태, 다수 조건)을 사용하지 않는다.

### 2.2 200일 이동평균 필터

```
기준 지수: S&P 500 (SPY) 또는 NASDAQ Composite (QQQ)
이동평균: 200일 단순이동평균 (SMA)
```

| 조건 | 판단 | 행동 |
|------|------|------|
| S&P 500 종가 **> 200일 SMA** | 상승 시장 | **신규 진입 허용** |
| S&P 500 종가 **< 200일 SMA** | 하락 시장 | **신규 진입 차단**, 기존 포지션은 터틀 청산룰 적용 |

### 2.3 정확한 계산

```python
def calculate_market_filter(spy_closes: list[float]) -> bool:
    """
    시장 방향 필터 판단
    
    Args:
        spy_closes: SPY의 최근 201일 이상의 종가 배열 (최신이 마지막)
    
    Returns:
        True = 신규 진입 허용, False = 신규 진입 차단
    """
    if len(spy_closes) < 200:
        return False  # 데이터 부족 시 보수적으로 차단
    
    # 200일 단순이동평균 계산
    sma_200 = sum(spy_closes[-200:]) / 200
    
    # 현재 종가와 비교
    current_close = spy_closes[-1]
    
    return current_close > sma_200
```

### 2.4 필터 적용 시점

| 상황 | 적용 방식 |
|------|----------|
| 신규 진입 | 당일 장 마감 후 SPY 종가 확인 → 200일 MA 위이면 다음 거래일 진입 가능 |
| 기존 포지션 | 시장 필터와 **무관하게** 터틀 청산 규칙(min(2N, 10%) 손절 또는 Donchian 청산)으로만 관리 |
| 필터 전환 시점 | SPY가 200일 MA를 하향 이탈한 당일 이후부터 신규 진입 차단 |
| 필터 복귀 시점 | SPY가 200일 MA를 상향 돌파한 당일 이후부터 신규 진입 재허용 |

### 2.5 간소화의 장점

| 항목 | FTD/Distribution Day | 200일 MA 필터 |
|------|---------------------|---------------|
| 판단 조건 수 | 10개 이상 | **1개** |
| 상태 수 | 5개 (Confirmed ~ Correction) | **2개** (위/아래) |
| 구현 복잡도 | 높음 (상태 머신, 만료 추적, Stalling Day 등) | **극히 단순** |
| 주관적 해석 | 일부 필요 (Stalling Day 판단 등) | **없음** |
| 역사적 검증 | IBD 50년 | **학계·실무 40년+** (Faber 2006, Siegel 등) |
| Whipsaw 빈도 | 보통 | 보통 (200일은 충분히 느린 필터) |

### 2.6 보조 확인 (선택적)

구현 시 다음을 선택적으로 추가할 수 있다. 이들은 **필수가 아닌 보조 지표**이다:

```python
# 선택적: NASDAQ도 200일 MA 위인지 확인 (이중 확인)
MARKET_FILTER_REQUIRE_BOTH = False  # True이면 SPY와 QQQ 모두 200MA 위 필요

# 선택적: MA를 1~2% 이상 돌파해야 유효로 인정 (Whipsaw 감소)
MARKET_FILTER_BUFFER_PCT = 0.00  # 0%: 버퍼 없음 (기본), 0.01~0.02 가능
```

---

## 3. ATR(N) 계산 — 핵심 변수

### 3.1 ATR이 중요한 이유

터틀 트레이딩에서 ATR(Average True Range)은 **모든 규칙의 기초 변수**이다:

| 적용 영역 | ATR 활용 방식 |
|----------|-------------|
| 포지션 사이징 | 리스크 기반 사이징: 실제 손절 폭(min(2N, 10%))으로 유닛 크기 결정 (1% 리스크) |
| 진입 | Donchian 채널 자체는 ATR 무관, 그러나 진입 후 즉시 ATR 기반 손절 설정 |
| 피라미딩 | 1/2 ATR 간격으로 추가 진입 |
| 손절 | max(진입가 - 2 × ATR, 진입가 × 0.90) — 즉 min(2N, 10%) 중 더 타이트한 쪽 |
| 리스크 정규화 | 서로 다른 주식의 변동성을 동일한 리스크 단위로 환산 |

**터틀 원전에서 ATR은 "N"으로 표기된다. 이 문서에서도 N = ATR로 사용한다.**

### 3.2 True Range (TR) 정의

True Range는 다음 세 값 중 **최댓값**이다:

```
TR = max(
    H - L,              # 당일 고가 - 당일 저가
    |H - C_prev|,       # 당일 고가 - 전일 종가 (갭업 반영)
    |L - C_prev|         # 당일 저가 - 전일 종가 (갭다운 반영)
)
```

여기서:
- `H` = 당일 고가 (High)
- `L` = 당일 저가 (Low)
- `C_prev` = 전일 종가 (Previous Close)

**왜 단순한 (H-L)이 아닌가?**

단순 고가-저가는 갭을 반영하지 못한다. 예를 들어 전일 종가 $50에서 당일 $52에 시가가 열리고 $53~$52 사이에서 거래되면, 일중 변동폭은 $1이지만 실제 변동성(전일 종가 대비)은 $3이다. True Range는 이를 정확히 포착한다.

### 3.3 N (= 20일 ATR) 계산

터틀 원전에서 N은 True Range의 **20일 지수이동평균(EMA)**이다:

```
N_today = N_prev × (19/20) + TR_today × (1/20)
```

이것은 EMA 공식으로, 평활 계수(smoothing factor) = 1/20 = 0.05이다.

**초기값 설정**: 첫 번째 N 값은 최초 20일간의 True Range 단순 평균(SMA)으로 계산한다.

```python
def calculate_n(highs: list[float], lows: list[float], closes: list[float], 
                period: int = 20) -> list[float]:
    """
    터틀 트레이딩 N (= 20일 ATR EMA) 계산
    
    Args:
        highs: 고가 배열
        lows: 저가 배열
        closes: 종가 배열
        period: ATR 기간 (기본 20)
    
    Returns:
        N 값 배열 (period일차부터 유효)
    """
    n = len(highs)
    tr = [0.0] * n
    
    # True Range 계산
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],                  # 당일 고가 - 당일 저가
            abs(highs[i] - closes[i - 1]),        # |당일 고가 - 전일 종가|
            abs(lows[i] - closes[i - 1])           # |당일 저가 - 전일 종가|
        )
    # 첫 날의 TR: H - L (전일 종가 없으므로)
    tr[0] = highs[0] - lows[0]
    
    # N 계산 (EMA of TR)
    n_values = [0.0] * n
    
    # 초기값: 최초 period일의 TR 단순 평균
    if n < period:
        return n_values  # 데이터 부족
    
    initial_n = sum(tr[1:period + 1]) / period  # 1~20일차 TR의 SMA
    n_values[period] = initial_n
    
    # EMA 계산
    multiplier = 1.0 / period  # 1/20 = 0.05
    for i in range(period + 1, n):
        n_values[i] = n_values[i - 1] * (1 - multiplier) + tr[i] * multiplier
    
    return n_values
```

### 3.4 Dollar Volatility (달러 변동성)

터틀 원전에서 Dollar Volatility는 "한 포인트 움직임의 달러 가치"를 곱한 값이다:

```
Dollar Volatility = N × Dollars per Point
```

선물 시장에서는 "Dollars per Point"가 계약 사양에 따라 다르다 (예: 원유 1포인트 = $1,000). 
**주식의 경우, 1주의 $1 움직임 = $1이므로**:

```
주식의 Dollar Volatility = N × 1 = N
```

즉, 주식에서 Dollar Volatility는 **N 그 자체**이다. 주가가 $50이고 N이 $2.00이면, 1주당 일일 평균 변동폭이 $2.00라는 뜻이다.

### 3.5 N의 실제 의미 해석

| 주가 | N값 | 의미 | N/주가 비율 |
|------|-----|------|-----------|
| $50 | $1.50 | 일일 평균 $1.50 변동 | 3.0% |
| $100 | $3.00 | 일일 평균 $3.00 변동 | 3.0% |
| $200 | $8.00 | 일일 평균 $8.00 변동 | 4.0% |
| $30 | $2.50 | 일일 평균 $2.50 변동 | 8.3% |

N/주가 비율이 높을수록 변동성이 큰 주식이며, 유닛 크기가 작아진다 (=더 적은 주수를 매수). 이것이 터틀 시스템의 **변동성 정규화** 효과이다.

---

## 4. 포지션 사이징 (Minervini 리스크 기반 유닛 시스템)

### 4.1 유닛(Unit)의 정의

1 유닛은 "계좌 자본의 1%를 **실제 적용되는 손절 폭**으로 리스크에 노출시키는 주식 수"이다.

터틀 원전은 `Unit = (Account × 1%) / N`으로 사이징하지만, 이 공식은 stop = 2N을 전제한다. 우리는 stop = min(2N, 10%)로 변경했으므로, **실제 손절 폭에 기반한 Minervini 리스크 사이징**을 사용한다.

```
실제 손절 폭(달러) = min(2N, 진입가 × 10%)

Unit (주식 수) = (계좌 자본 × RISK_PER_UNIT) / 실제 손절 폭

= (Account × 0.01) / min(2N, Price × 0.10)
```

**터틀 원전 대비 차이점:**
- 터틀 원전: `shares = (Account × 1%) / N` → stop 2N 시 유닛당 리스크 = **2%** (비일관)
- **본 전략**: `shares = (Account × 1%) / actual_stop` → 유닛당 리스크 = **항상 정확히 1%**

### 4.2 유닛 계산 공식

```python
def calculate_unit_size(account_equity: float, entry_price: float,
                         n_value: float, risk_per_unit: float = RISK_PER_UNIT) -> int:
    """
    Minervini 리스크 기반 유닛 크기 계산
    
    실제 적용되는 손절 폭(min(2N, 10%))에 기반하여
    유닛당 리스크가 항상 정확히 risk_per_unit이 되도록 사이징
    
    Args:
        account_equity: 총 계좌 자본 ($)
        entry_price: 진입 예정 가격
        n_value: 현재 N 값 (20일 ATR EMA)
        risk_per_unit: 유닛당 리스크 비율 (기본 1%)
    
    Returns:
        매수할 주식 수 (정수로 내림)
    """
    if n_value <= 0 or entry_price <= 0:
        return 0
    
    # 실제 적용되는 손절 폭 (달러)
    stop_2n = STOP_LOSS_N * n_value                    # 2N
    stop_10pct = entry_price * STOP_LOSS_MAX_PCT       # 진입가의 10%
    actual_stop_distance = min(stop_2n, stop_10pct)    # 더 타이트한 쪽
    
    # 리스크 기반 사이징
    dollar_risk = account_equity * risk_per_unit       # 예: $100,000 × 1% = $1,000
    unit_shares = dollar_risk / actual_stop_distance
    
    return int(unit_shares)  # 내림 (소수점 주식 불가)
```

### 4.3 상세 예시

#### 예시 1: 중변동 종목 (2N < 10% → 2N 적용)

```
계좌 자본: $100,000
종목: AAPL, 현재가 $175
N (20일 ATR): $3.50, N/P = 2.0%
2N = $7.00, 10% = $17.50 → min = $7.00 (2N 적용)

Unit = ($100,000 × 0.01) / $7.00
     = $1,000 / $7.00
     = 142주

포지션 금액 = 142 × $175 = $24,850 (계좌의 24.9%)
손절 시 손실 = 142 × $7.00 = $994 ≈ 계좌의 1.0% ✓
```

#### 예시 2: 고변동 종목 (2N > 10% → 10% 캡 적용)

```
계좌 자본: $100,000
종목: TSLA, 현재가 $250
N (20일 ATR): $15.00, N/P = 6.0%
2N = $30.00, 10% = $25.00 → min = $25.00 (10% 캡 적용)

Unit = ($100,000 × 0.01) / $25.00
     = $1,000 / $25.00
     = 40주

포지션 금액 = 40 × $250 = $10,000 (계좌의 10.0%)
손절 시 손실 = 40 × $25.00 = $1,000 = 계좌의 1.0% ✓
```

#### 예시 3: 저변동 종목 (2N << 10% → 2N 적용)

```
계좌 자본: $100,000
종목: JNJ, 현재가 $160
N (20일 ATR): $1.80, N/P = 1.1%
2N = $3.60, 10% = $16.00 → min = $3.60 (2N 적용)

Unit = ($100,000 × 0.01) / $3.60
     = $1,000 / $3.60
     = 277주

포지션 금액 = 277 × $160 = $44,320 (계좌의 44.3%)
손절 시 손실 = 277 × $3.60 = $997 ≈ 계좌의 1.0% ✓
```

### 4.4 리스크 정규화의 효과

위 세 예시에서 주목할 점: **어떤 종목이든, 어떤 변동성이든, 손절 시 손실은 항상 정확히 계좌의 1%**이다.

- 변동성이 큰 주식 → 손절 폭이 넓음 → 적은 주수 매수 → 리스크 1%
- 변동성이 작은 주식 → 손절 폭이 좁음 → 많은 주수 매수 → 리스크 1%
- **10% 캡 작동 시 → 포지션이 자연스럽게 작아짐 → 과도한 자금 투입 방지**

이는 CANSLIM의 동일 비중법(20% × 5종목)보다 **종목 특성에 맞는 사이징**을 제공한다.

**터틀 원전 대비 개선점:**

| 종목 유형 | 터틀 원전 포지션 | 본 전략 포지션 | 차이 |
|-----------|----------------|--------------|------|
| 저변동 (N/P=1.1%) | $88,800 (89%) | **$44,320 (44%)** | 절반으로 축소 → 자금 초과 방지 |
| 중변동 (N/P=2.0%) | $49,875 (50%) | **$24,850 (25%)** | 절반으로 축소 |
| 고변동 (N/P=6.0%) | $20,750 (21%) | **$10,000 (10%)** | 축소 (10% 캡 효과) |

### 4.5 유닛 크기 제한

리스크 기반 사이징이 자연스럽게 포지션을 제한하지만, 추가 안전장치를 적용한다:

```python
def apply_unit_limits(unit_shares: int, current_price: float, 
                       account_equity: float, avg_daily_volume: int) -> int:
    """
    유닛 크기에 현실적 제한 적용
    """
    # 제한 1: 단일 유닛이 계좌의 MAX_SINGLE_UNIT_PCT를 초과 불가
    max_by_equity = int((account_equity * MAX_SINGLE_UNIT_PCT) / current_price)
    
    # 제한 2: 일평균 거래량의 5% 초과 불가 (유동성)
    max_by_liquidity = int(avg_daily_volume * MAX_POSITION_PCT_OF_ADV)
    
    # 최종 유닛 = 세 값 중 최소
    return min(unit_shares, max_by_equity, max_by_liquidity)
```

### 4.6 유닛 금액의 계좌 비중 범위 (리스크 기반 사이징)

N/주가 비율에 따른 1 유닛의 계좌 비중 (RISK_PER_UNIT = 1%):

| N/주가 비율 | 적용 손절 | 1 유닛 계좌 비중 | 4유닛 합계 비중 | 해석 |
|-----------|----------|----------------|---------------|------|
| 1% | 2% (2N) | 50% | 200% ⛔ | 극저변동 — 제한 필요 |
| 2% | 4% (2N) | 25% | 100% | 저변동 — 4유닛 가능하나 타이트 |
| 3% | 6% (2N) | 17% | 68% | 보통 — 4유닛 여유 |
| 4% | 8% (2N) | 12.5% | 50% ✅ | 이상적 |
| 5% | 10% (동일) | 10% | 40% ✅ | 분기점 |
| 6% | 10% (캡) | 10% | 40% ✅ | 고변동 — 캡이 크기 제한 |
| 8% | 10% (캡) | 10% | 40% ✅ | 고변동 — 포지션 자동 제한 |

---

## 5. 진입 규칙 (Donchian Channel 돌파)

### 5.1 System 1 — 단기 시스템 (20일 돌파)

#### 진입 조건

```
매수 진입: 현재가가 최근 20 거래일의 최고가를 상향 돌파
```

수학적으로:

```
Donchian_Upper_20 = max(High[-20], High[-19], ..., High[-1])

진입 조건: Close_today > Donchian_Upper_20
          또는
          High_today > Donchian_Upper_20  (장중 돌파 시)
```

**구현 선택**: 종가 기준 vs 장중 기준

| 방식 | 장점 | 단점 |
|------|------|------|
| **종가 기준** (권장) | 가짜 돌파 감소, 실행 간단 | 진입 타이밍 약간 늦음 |
| 장중 기준 | 빠른 진입 | 가짜 돌파 증가, 실시간 모니터링 필요 |

이 시스템에서는 **종가 기준**을 기본으로 한다.

#### System 1 필터: 이전 돌파가 수익인 경우 건너뛰기

터틀 원전의 핵심 규칙 중 하나:

```
직전 20일 돌파가 수익이었다면 → 이번 20일 돌파 신호를 건너뛴다
직전 20일 돌파가 손실이었다면 → 이번 20일 돌파 신호에 진입한다
```

**"직전 20일 돌파"의 정의**: 실제로 진입했든 안 했든, 마지막으로 발생한 20일 돌파 신호를 추적한다. 해당 돌파가 수익이 되었을 것인지(= 10일 저가 청산 기준으로) 가상으로 계산한다.

```python
def should_skip_system1_entry(
    breakout_history: list[dict],  # [{'date': ..., 'price': ..., 'would_have_been_winner': bool}, ...]
) -> bool:
    """
    System 1 필터: 직전 돌파가 수익이면 이번 진입 건너뛰기
    
    Args:
        breakout_history: 과거 20일 돌파 기록 (시간순, 마지막이 최신)
    
    Returns:
        True = 이번 진입 건너뛰기, False = 진입 실행
    """
    if not breakout_history:
        return False  # 이전 기록 없으면 진입
    
    last_breakout = breakout_history[-1]
    
    # 직전 돌파가 수익이었으면 → 이번 건너뛰기
    return last_breakout['would_have_been_winner']
```

**왜 이 필터를 쓰는가?**

연속적인 돌파 성공 후에는 추세가 소진되었을 확률이 높다. 이 필터는 과열된 연속 돌파를 피하고, 실패 후의 "신선한" 돌파를 잡는다. 통계적으로 System 1의 승률을 개선하는 효과가 있다.

**건너뛴 신호는 어떻게 되는가?**

System 1에서 건너뛴 종목이 계속 상승하면, System 2(55일 돌파)에서 잡힌다. 즉, 진정한 대형 추세를 놓치지 않는 안전장치가 있다.

#### System 1 진입 구현

```python
def check_system1_entry(
    highs: list[float], 
    closes: list[float],
    lookback: int = 20,
    last_breakout_was_winner: bool = False
) -> dict:
    """
    System 1 진입 신호 확인
    
    Args:
        highs: 고가 배열 (최신이 마지막)
        closes: 종가 배열
        lookback: 돌파 기간 (20일)
        last_breakout_was_winner: 직전 돌파 수익 여부
    
    Returns:
        {'signal': bool, 'breakout_price': float, 'skipped': bool}
    """
    if len(highs) < lookback + 1:
        return {'signal': False, 'breakout_price': 0.0, 'skipped': False}
    
    # 20일 최고가 (오늘 제외)
    donchian_upper = max(highs[-(lookback + 1):-1])
    
    # 돌파 확인 (종가 기준)
    current_close = closes[-1]
    breakout = current_close > donchian_upper
    
    if not breakout:
        return {'signal': False, 'breakout_price': donchian_upper, 'skipped': False}
    
    # System 1 필터: 직전 돌파가 수익이면 건너뛰기
    if last_breakout_was_winner:
        return {'signal': False, 'breakout_price': donchian_upper, 'skipped': True}
    
    return {'signal': True, 'breakout_price': donchian_upper, 'skipped': False}
```

### 5.2 System 2 — 장기 시스템 (55일 돌파)

#### 진입 조건

```
매수 진입: 현재가가 최근 55 거래일의 최고가를 상향 돌파
```

```
Donchian_Upper_55 = max(High[-55], High[-54], ..., High[-1])

진입 조건: Close_today > Donchian_Upper_55
```

#### 필터 없음

System 2에서는 **모든 돌파 신호에 진입한다**. 직전 돌파의 수익/손실 여부와 무관하다.

이유: 55일 돌파는 이미 충분히 긴 기간의 돌파이므로, 추세가 진정으로 강할 때만 발생한다. 추가 필터는 불필요하다.

#### System 2의 역할

1. System 1에서 필터로 건너뛴 종목의 **안전망** — 진정한 대형 추세를 놓치지 않음
2. 장기 추세 포착에 더 적합 — 55일 채널은 약 11주(거의 3개월)의 가격 범위
3. 더 긴 청산 기간(20일 저가)과 결합 → 추세를 더 오래 탐

```python
def check_system2_entry(
    highs: list[float], 
    closes: list[float],
    lookback: int = 55
) -> dict:
    """
    System 2 진입 신호 확인 (필터 없음 — 모든 돌파에 진입)
    """
    if len(highs) < lookback + 1:
        return {'signal': False, 'breakout_price': 0.0}
    
    # 55일 최고가 (오늘 제외)
    donchian_upper = max(highs[-(lookback + 1):-1])
    
    # 돌파 확인 (종가 기준)
    current_close = closes[-1]
    breakout = current_close > donchian_upper
    
    return {'signal': breakout, 'breakout_price': donchian_upper}
```

### 5.3 진입 조건 종합 체크리스트

하나의 종목에 진입하기 위해 **모든 조건이 순서대로 충족**되어야 한다:

```
[1단계] 시장 필터 확인
  └→ S&P 500 종가 > 200일 SMA? ────→ No → 진입 불가 (종료)
                                    Yes ↓

[2단계] 종목 선정 확인
  └→ CANSLIM 필터 통과 종목인가? ────→ No → 진입 불가 (종료)
                                      Yes ↓

[3단계] Donchian 돌파 신호 확인
  └→ System 1 (20일) 또는 System 2 (55일) 돌파? ──→ No → 대기 (종료)
                                                     Yes ↓

[4단계] System 1 필터 확인 (System 1인 경우만)
  └→ 직전 돌파가 수익? ────→ Yes → System 1 건너뛰기 → System 2 대기
                            No ↓

[5단계] 포지션 한도 확인
  └→ 단일 종목 4유닛 미만? ────────→ No → 진입 불가 (종료)
  └→ 상관 종목 6유닛 미만? ────────→ No → 진입 불가 (종료)
  └→ 전체 포트폴리오 12유닛 미만? ──→ No → 진입 불가 (종료)
                                     Yes ↓

[6단계] 유닛 크기 계산 (Minervini 리스크 기반)
  └→ 실제 손절 폭 = min(2N, 진입가 × 10%)
  └→ Unit = (Account × 1%) / 실제 손절 폭
  └→ 유동성 제한 적용
  └→ 계좌 비중 제한 적용
                                       ↓

[7단계] 진입 실행
  └→ Unit 만큼 매수 (1 유닛)
  └→ 손절가 설정: max(진입가 - 2N, 진입가 × 0.90)  ← min(2N, 10%) 하이브리드
  └→ 기록: 진입가, 유닛 수, 손절가, N 값
```

```python
def execute_entry_checklist(
    spy_closes: list[float],
    stock_data: dict,
    canslim_watchlist: list[str],
    portfolio: dict,
    account_equity: float
) -> dict:
    """
    진입 체크리스트 실행
    
    Returns:
        {'action': 'BUY'|'SKIP', 'shares': int, 'stop_price': float, ...}
    """
    ticker = stock_data['ticker']
    
    # 1단계: 시장 필터
    if not calculate_market_filter(spy_closes):
        return {'action': 'SKIP', 'reason': '시장 필터 미통과 (SPY < 200MA)'}
    
    # 2단계: CANSLIM 종목 확인
    if ticker not in canslim_watchlist:
        return {'action': 'SKIP', 'reason': 'CANSLIM 필터 미통과'}
    
    # 3단계: Donchian 돌파 확인
    s1 = check_system1_entry(stock_data['highs'], stock_data['closes'])
    s2 = check_system2_entry(stock_data['highs'], stock_data['closes'])
    
    system = None
    if s1['signal']:
        system = 'S1'
    elif s1['skipped'] and s2['signal']:
        system = 'S2'  # S1 건너뛰었지만 S2에서 진입
    elif s2['signal']:
        system = 'S2'
    else:
        return {'action': 'SKIP', 'reason': 'Donchian 돌파 미발생'}
    
    # 5단계: 포지션 한도 확인
    current_units = portfolio.get(ticker, {}).get('units', 0)
    if current_units >= MAX_UNITS_PER_STOCK:
        return {'action': 'SKIP', 'reason': f'단일 종목 한도 초과 ({current_units}/{MAX_UNITS_PER_STOCK})'}
    
    total_units = sum(p.get('units', 0) for p in portfolio.values())
    if total_units >= MAX_UNITS_LONG:
        return {'action': 'SKIP', 'reason': f'전체 포지션 한도 초과 ({total_units}/{MAX_UNITS_LONG})'}
    
    # 6단계: 유닛 크기 계산 (Minervini 리스크 기반)
    n_value = stock_data['n_value']
    entry_price = stock_data['closes'][-1]
    unit_shares = calculate_unit_size(account_equity, entry_price, n_value)
    
    # min(2N, 10%) 하이브리드 손절
    stop_2n = entry_price - (STOP_LOSS_N * n_value)
    stop_10pct = entry_price * (1 - STOP_LOSS_MAX_PCT)
    stop_price = max(stop_2n, stop_10pct)
    
    # 7단계: 진입
    return {
        'action': 'BUY',
        'system': system,
        'ticker': ticker,
        'shares': unit_shares,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'n_value': n_value,
        'unit_number': current_units + 1
    }
```

### 5.4 공매도 (Short) 규칙 (참고)

> **기본 설정: SHORT 비활성화**
> 개별 주식의 공매도는 무한 손실 가능성, 대여 비용, 숏 스퀴즈 리스크 등으로 인해 선물 공매도와는 근본적으로 다르다. 이 시스템에서는 기본적으로 롱 온리로 운영한다.

터틀 원전의 공매도 규칙을 참고용으로 기록한다:

#### System 1 숏 진입
```
진입: 현재가가 최근 20일의 최저가를 하향 돌파
필터: 직전 20일 하향 돌파가 수익이었다면 건너뛰기
청산: 10일 최고가 돌파 시 전량 숏 커버
```

#### System 2 숏 진입
```
진입: 현재가가 최근 55일의 최저가를 하향 돌파
필터: 없음 (모든 돌파에 진입)
청산: 20일 최고가 돌파 시 전량 숏 커버
```

#### 숏 활성화 조건 (선택적)

공매도를 활성화하려면 다음 조건을 추가 적용한다:

```python
SHORT_ENABLED = False  # 기본값: 비활성

# 활성화 시 조건:
# S&P 500 < 200일 MA일 때만 숏 진입 허용
# (상승 시장에서의 공매도는 위험하므로)
def can_short(spy_closes: list[float]) -> bool:
    if not SHORT_ENABLED:
        return False
    sma_200 = sum(spy_closes[-200:]) / 200
    return spy_closes[-1] < sma_200
```

---

## 6. 피라미딩 (추가 진입)

### 6.1 피라미딩 규칙

포지션이 수익 방향으로 움직이면 추가 유닛을 투입한다. 이것이 터틀 시스템에서 대형 수익을 만드는 핵심 메커니즘이다.

```
추가 진입 간격: 1/2 N (직전 진입가 기준)
최대 유닛 수: 4 유닛 per 종목
각 추가 유닛의 크기: 첫 유닛과 동일 ((Account × 1%) / min(2N, Price × 10%))
```

| 유닛 # | 진입 가격 | 이전 진입 대비 |
|--------|----------|--------------|
| **1st** | 돌파가 (Breakout Price) | — |
| **2nd** | 돌파가 + 1/2 N | +1/2 N |
| **3rd** | 돌파가 + 1 N | +1/2 N |
| **4th** | 돌파가 + 1.5 N | +1/2 N |

### 6.2 상세 예시: 4단계 피라미딩

```
종목: NVDA
계좌 자본: $100,000
현재가: $450 (Donchian 20일 돌파)
N = $9.00 (20일 ATR), N/P = 2.0%
2N = $18.00, 10% = $45.00 → min = $18.00 (2N 적용)
1 Unit = ($100,000 × 0.01) / $18.00 = 55주
```

#### 단계별 진행

| 단계 | 이벤트 | 진입가 | 주수 | 누적 주수 | 포지션 금액 | 계좌 비중 |
|------|--------|--------|------|----------|-----------|----------|
| **1st Unit** | $450에서 20일 돌파 | $450.00 | 55주 | 55주 | $24,750 | 24.8% |
| **2nd Unit** | +1/2 N = +$4.50 | $454.50 | 55주 | 110주 | $49,995 | 50.0% |
| **3rd Unit** | +1/2 N = +$4.50 | $459.00 | 55주 | 165주 | $75,735 | 75.7% |
| **4th Unit** | +1/2 N = +$4.50 | $463.50 | 55주 | 220주 | $101,970 | 102.0% |

**참고**: 리스크 기반 사이징으로 포지션이 자연스럽게 작아져서, 3유닛까지는 레버리지 없이 완전히 가능하다. 4유닛은 비중 제한(MAX_SINGLE_POSITION_PCT)에 의해 조정될 수 있다.

### 6.3 피라미딩 시 손절 조정

**이것이 가장 중요한 규칙이다:**

> 추가 유닛이 진입될 때마다, **모든 기존 유닛의 손절을 최신 진입가 기준 min(2N, 10%)으로 올린다.**
> 단, 각 유닛의 개별 10% 바닥선(진입가 × 0.90)도 항상 유지한다.

#### 손절 조정 추적표 (N = $9, N/P ≈ 2% → 2N = 4% < 10%이므로 2N 적용)

| 시점 | 1st 손절 | 2nd 손절 | 3rd 손절 | 4th 손절 |
|------|---------|---------|---------|---------|
| 1st 진입 ($450.00) | $432.00 (= $450 - 2×$9) | — | — | — |
| 2nd 진입 ($454.50) | **$436.50** | $436.50 | — | — |
| 3rd 진입 ($459.00) | **$441.00** | **$441.00** | $441.00 | — |
| 4th 진입 ($463.50) | **$445.50** | **$445.50** | **$445.50** | $445.50 |

> 위 예시는 N/P ≈ 2%인 저변동 종목이므로 10% 캡이 작동하지 않는다 (2N = 4% < 10%).

#### 고변동 종목 예시 (N = $6, 주가 $100 → N/P = 6%, 2N = 12% > 10% → 10% 캡 작동)

| 시점 | 2N 손절 | 10% 손절 | **적용 손절** |
|------|---------|---------|-------------|
| 1st 진입 ($100.00) | $88.00 | $90.00 | **$90.00** (10% 캡) |
| 2nd 진입 ($103.00) | $91.00 | $92.70 | **$92.70** (10% 캡) |
| 3rd 진입 ($106.00) | $94.00 | $95.40 | **$95.40** (10% 캡) |
| 4th 진입 ($109.00) | $97.00 | $98.10 | **$98.10** (10% 캡) |

4th 유닛 진입 후의 상태 (저변동 예시, N=$9):

- 모든 유닛의 손절가 = $445.50
- 1st 유닛: 진입 $450.00, 손절 $445.50 → 리스크 = -$4.50/주 = -1.0%
- 2nd 유닛: 진입 $454.50, 손절 $445.50 → 리스크 = -$9.00/주 = -2.0%
- 3rd 유닛: 진입 $459.00, 손절 $445.50 → 리스크 = -$13.50/주 = -2.9%
- 4th 유닛: 진입 $463.50, 손절 $445.50 → 리스크 = -$18.00/주 = -3.9%

4th 유닛 진입 후의 상태 (고변동 예시, N=$6):

- 각 유닛별 손절 = max(최신 2N 기준, 해당 유닛 × 0.90)
- 1st 유닛: 진입 $100.00, 손절 $98.10 → 리스크 = -$1.90/주 = -1.9%
- 2nd 유닛: 진입 $103.00, 손절 $98.10 → 리스크 = -$4.90/주 = -4.8%
- 3rd 유닛: 진입 $106.00, 손절 $98.10 → 리스크 = -$7.90/주 = -7.5%
- 4th 유닛: 진입 $109.00, 손절 $98.10 → 리스크 = -$10.90/주 = -10.0%
- **참고**: 10% 캡 적용 시 고변동 종목에서도 개별 유닛의 최대 손실이 10%로 제한됨

### 6.4 피라미딩 구현

```python
def check_pyramid_add(
    position: dict,
    current_price: float,
    account_equity: float
) -> dict:
    """
    피라미딩 추가 진입 확인
    
    Args:
        position: {
            'units': [{'entry_price': float, 'shares': int, 'stop': float}, ...],
            'n_value': float,
            'ticker': str
        }
        current_price: 현재가
        account_equity: 계좌 자본
    
    Returns:
        {'add': bool, 'shares': int, 'entry_price': float, 'new_stops': list[float]}
    """
    units = position['units']
    n = position['n_value']
    
    # 최대 4 유닛 제한
    if len(units) >= MAX_UNITS_PER_STOCK:
        return {'add': False, 'reason': '최대 유닛 수 도달 (4)'}
    
    # 직전 진입가 확인
    last_entry = units[-1]['entry_price']
    
    # 1/2 N 이상 상승했는가?
    pyramid_trigger = last_entry + (n * PYRAMID_INTERVAL_N)  # 0.5N
    
    if current_price < pyramid_trigger:
        return {'add': False, 'reason': f'피라미드 트리거 미달 (필요: ${pyramid_trigger:.2f})'}
    
    # 새 유닛 크기 계산 (Minervini 리스크 기반)
    new_shares = calculate_unit_size(account_equity, current_price, n)
    
    # 새 손절가: min(2N, 10%) 하이브리드
    stop_2n = current_price - (STOP_LOSS_N * n)
    stop_10pct = current_price * (1 - STOP_LOSS_MAX_PCT)
    new_stop = max(stop_2n, stop_10pct)  # 둘 중 높은 가격 = 더 타이트한 손절
    
    # 모든 기존 유닛의 손절도 새 손절가로 올림
    updated_stops = []
    for unit in units:
        # 각 유닛의 개별 10% 바닥선도 확인
        unit_floor = unit['entry_price'] * (1 - STOP_LOSS_MAX_PCT)
        # 기존 손절, 새 손절, 개별 바닥선 중 가장 높은 것
        updated_stop = max(unit['stop'], new_stop, unit_floor)
        updated_stops.append(updated_stop)
    updated_stops.append(new_stop)  # 새 유닛의 손절
    
    return {
        'add': True,
        'shares': new_shares,
        'entry_price': current_price,
        'new_stop': new_stop,
        'all_stops': updated_stops
    }
```

### 6.5 피라미딩의 수학적 효과

피라미딩은 **수익이 나는 포지션에만 추가 투입**하므로, 평균 매수가가 시장 방향으로 이동하면서도 손절 조정으로 리스크를 제한한다.

4 유닛 전체가 투입된 후의 종합 분석 (NVDA 예시, N=$9, 55주/유닛):

```
총 투입 주수: 220주
평균 매수가: ($450.00 + $454.50 + $459.00 + $463.50) / 4 = $456.75
통합 손절가: $463.50 - $18.00 = $445.50 (2N 적용, 10% 캡 미작동)
평균 매수가 대비 손절 하락: ($456.75 - $445.50) / $456.75 = -2.46%

각 유닛별 최대 손실:
  1st: 55 × ($450.00 - $445.50) = -$247.50 (= -0.25% of account)
  2nd: 55 × ($454.50 - $445.50) = -$495.00 (= -0.50% of account)
  3rd: 55 × ($459.00 - $445.50) = -$742.50 (= -0.74% of account)
  4th: 55 × ($463.50 - $445.50) = -$990.00 (= -0.99% of account)

총 최대 손실 (모든 유닛 동시 손절 시):
  = $247.50 + $495.00 + $742.50 + $990.00
  = $2,475.00
  = 계좌의 2.48%
```

**핵심 관찰**: 리스크 기반 사이징에서 4 유닛이 모두 동시에 손절되어도 **계좌의 약 2.5%만 손실**된다. 이는 터틀 원전(5.0%)의 절반 수준이다. 각 유닛의 독립 리스크가 1%(터틀 원전의 2%가 아닌)이기 때문이다. 정확히 0.25% + 0.50% + 0.74% + 0.99% ≈ 2.5%.

**12유닛 전체 동시 손절 시 최대 리스크**: 약 7.5% (터틀 원전 15% → 절반으로 감소)

---

## 7. 손절 (Stop Loss)

### 7.1 기본 손절 규칙 — min(2N, 10%) 하이브리드

```
초기 손절 = max(진입가 - 2N, 진입가 × 0.90)
         = 진입가 - min(2N, 진입가 × 10%)
```

즉, **2N과 10% 중 더 타이트한(좁은) 쪽을 적용**한다.

| 파라미터 | 값 |
|---------|-----|
| 손절 폭 | **min(2N, 10%)** — 둘 중 더 좁은 쪽 |
| 진입 즉시 | 손절 주문 설정 |
| 손절 방향 | **절대로 멀리 이동하지 않음** (좁히기만 함) |
| 10% 캡 | 어떤 종목이든 단일 유닛 최대 손실이 10%를 넘지 않음 |

**왜 min(2N, 10%)인가?**

- **2N의 장점 유지**: 저~중변동성 종목(N/P ≤ 5%)에서는 2N이 10%보다 좁으므로, 변동성 적응형 손절이 그대로 작동한다.
- **10% 캡의 보호**: 고변동성 종목(N/P > 5%)에서 2N이 12~16%까지 벌어지는 것을 방지한다.
- **순수 8%보다 10%를 택한 이유**: 8%로 하면 피라미딩 3~4유닛이 고변동 종목에서 구조적으로 불가능해진다. 10%는 4유닛 피라미딩을 허용하면서도 극단적 손실을 제한하는 균형점이다.
- 1N은 일상적인 변동폭이므로, 정상적인 가격 움직임에 의해 자주 트리거됨 → 과도한 whipsaw
- 3N은 너무 넓어서 큰 손실 발생 가능
- 2N은 "정상적인 노이즈는 견디되, 진정한 추세 반전에는 탈출하는" 최적 지점

**분기점: N/P = 5%에서 2N(10%)과 10% 캡이 일치한다.**

실제 %로 변환하면:

| N/주가 비율 | 2N (%) | 10% 캡 | **적용 손절** | 해석 |
|-----------|--------|--------|-------------|------|
| 2% | 4% | 10% | **4% (2N)** | 저변동성 — 2N이 더 타이트 |
| 3% | 6% | 10% | **6% (2N)** | 보통 — 2N이 더 타이트 |
| 4% | 8% | 10% | **8% (2N)** | CANSLIM -8%와 유사 |
| 5% | 10% | 10% | **10% (동일)** | 분기점 |
| 6% | 12% | 10% | **10% (캡)** | 고변동 — 10% 캡 작동 |
| 7% | 14% | 10% | **10% (캡)** | 고변동 — 10% 캡 작동 |
| 8% | 16% | 10% | **10% (캡)** | 극고변동 — 10% 캡 작동 |

```python
def calculate_stop_price(entry_price: float, n_value: float) -> float:
    """
    min(2N, 10%) 하이브리드 손절가 계산
    
    두 손절 중 더 높은 가격(= 더 타이트한 손절)을 반환
    """
    stop_2n = entry_price - (STOP_LOSS_N * n_value)        # 터틀 기본: 2N
    stop_10pct = entry_price * (1 - STOP_LOSS_MAX_PCT)     # 최대 10% 캡
    return max(stop_2n, stop_10pct)  # 높은 가격 = 더 타이트한 손절
```

### 7.2 피라미딩 시 손절 조정 규칙

> **핵심: 새 유닛이 추가될 때마다, 모든 기존 유닛의 손절을 "최신 진입가 기준 min(2N, 10%)"으로 올린다.**
> 단, 각 유닛의 개별 10% 바닥선(진입가 × 0.90)도 항상 유지한다.

이 규칙의 의미:

1. 초기 유닛의 손절이 점점 좁아진다 → 리스크 감소
2. 모든 유닛이 동일한 손절가를 공유 → 관리 단순화
3. 손절에 걸리면 **전체 포지션이 한 번에 청산** → 부분 청산 없음
4. **10% 캡**: 어떤 유닛도 진입가 대비 10%를 초과하여 손실을 보지 않음

```python
def update_stops_on_pyramid(
    position: dict,
    new_entry_price: float,
    n_value: float
) -> list[float]:
    """
    피라미딩 시 모든 유닛의 손절을 업데이트
    
    규칙: 새 손절 = max(new_entry_price - 2N, new_entry_price × 0.90)
    추가로 각 유닛의 개별 10% 바닥선도 확인
    기존 손절이 새 손절보다 이미 높으면 유지 (절대 내리지 않음)
    """
    # min(2N, 10%) 하이브리드 손절
    stop_2n = new_entry_price - (STOP_LOSS_N * n_value)
    stop_10pct = new_entry_price * (1 - STOP_LOSS_MAX_PCT)
    new_stop = max(stop_2n, stop_10pct)
    
    updated_stops = []
    for unit in position['units']:
        # 각 유닛의 개별 10% 바닥선
        unit_floor = unit['entry_price'] * (1 - STOP_LOSS_MAX_PCT)
        # 기존 손절, 새 손절, 개별 바닥선 중 가장 높은 것
        updated_stop = max(unit['stop'], new_stop, unit_floor)
        updated_stops.append(updated_stop)
    
    return updated_stops
```

### 7.3 손절 절대 불가 규칙

| 규칙 | 설명 |
|------|------|
| **손절을 멀리 이동 금지** | 한 번 설정된 손절을 진입가에서 더 먼 곳으로 이동하면 안 된다 |
| **손절 취소 금지** | 어떤 이유로든 손절을 취소하면 안 된다 |
| **"한 번만 더" 금지** | "조금만 더 기다리면 반등할 것 같다"는 생각은 시스템 위반 |
| **심리적 손절 금지** | 반드시 실제 주문으로 설정해야 한다 (머릿속 손절은 실행 안 됨) |

### 7.4 최대 리스크 수학적 증명

4 유닛 피라미딩 후 전체 손절 시의 정확한 리스크를 계산한다.

#### 케이스 A: 저~중변동 종목 (N/P ≤ 5% → 2N ≤ 10% → 10% 캡 미작동)

이 경우 순수 터틀 2N 손절과 동일하다.

**설정**:
- 1 유닛 = (Account × 1%) / actual_stop 주 (Minervini 리스크 기반)
- 1/2 N 간격으로 피라미딩
- 모든 손절 = 최종 진입가 - 2N (10% 캡이 작동하지 않으므로)

```
진입가:
  1st: P
  2nd: P + 0.5N
  3rd: P + 1.0N
  4th: P + 1.5N

통합 손절가: (P + 1.5N) - 2N = P - 0.5N

각 유닛의 손실 (주당):
  1st: P - (P - 0.5N) = 0.5N
  2nd: (P + 0.5N) - (P - 0.5N) = 1.0N
  3rd: (P + 1.0N) - (P - 0.5N) = 1.5N
  4th: (P + 1.5N) - (P - 0.5N) = 2.0N

각 유닛의 계좌 리스크:
  리스크 기반 사이징: 1 유닛이 stop_distance(=2N)만큼 움직이면 = 계좌의 1%
  따라서 1N 움직임 = 계좌의 0.5%

  1st: 0.5N → 0.25%
  2nd: 1.0N → 0.50%
  3rd: 1.5N → 0.75%
  4th: 2.0N → 1.00%

총 리스크 = 0.25% + 0.50% + 0.75% + 1.00% = 2.50%
```

**결론 A**: 저~중변동 종목에서 4 유닛 피라미딩 후 전체 손절 시 **최대 2.50%의 계좌 리스크**. (터틀 원전 5.0%의 절반)

#### 케이스 B: 고변동 종목 (N/P > 5% → 2N > 10% → 10% 캡 작동)

이 경우 10% 캡이 작동하여 리스크가 감소한다.

**예시: 주가 $100, N = $6 (N/P = 6%)**

```
진입가:
  1st: $100.00
  2nd: $103.00 (+0.5N)
  3rd: $106.00 (+1.0N)
  4th: $109.00 (+1.5N)

손절가 (10% 캡 적용):
  최신 2N 기준: $109 - $12 = $97.00
  최신 10% 기준: $109 × 0.90 = $98.10 ← 더 타이트
  → 통합 손절가: $98.10

유닛 크기 (Minervini 리스크 기반):
  actual_stop = min(2×$6, $100×0.10) = min($12, $10) = $10
  shares = ($100,000 × 0.01) / $10 = 100주

각 유닛의 손실:
  1st: ($100.00 - $98.10) × 100주 = $190  (0.19%)
  2nd: ($103.00 - $98.10) × 100주 = $490  (0.49%)
  3rd: ($106.00 - $98.10) × 100주 = $790  (0.79%)
  4th: ($109.00 - $98.10) × 100주 = $1,090 (1.09%)

총 리스크 = 0.19% + 0.49% + 0.79% + 1.09% = 2.56%
```

**결론 B**: 고변동 종목(N/P=6%)에서 Minervini 리스크 기반 사이징 + 10% 캡 적용 시, 4 유닛 전체 손절의 리스크가 **~2.56%**로 제한된다. 터틀 원전 대비 약 절반 수준의 리스크.

#### 요약

| 종목 변동성 | 적용 규칙 | 4유닛 최대 리스크 (Minervini) |
|-----------|----------|---------------------------|
| N/P ≤ 5% | 2N (캡 미작동) | ≤2.5% |
| N/P = 6% | 10% 캡 | ~2.56% |
| N/P = 7% | 10% 캡 | ~2.3% |

> **Minervini 사이징 효과**: 터틀 원전 대비 4유닛 최대 리스크가 약 **절반**으로 감소한다. 이는 `shares = (Account×1%) / actual_stop_distance` 공식이 실제 손절 폭에 정확히 비례하여 유닛 크기를 조절하기 때문이다.

그러나 실제로는 1st 유닛이 이미 수익 구간에 있으므로 (1.5N 상승), 심리적 충격은 크지 않다. 1st 유닛 기준으로는 0.5N 이하 손실에 불과하다.

### 7.5 Whipsaw 처리

손절 후에도 해당 종목이 다시 Donchian 돌파 신호를 발생시키면 **재진입 가능**하다.

```python
def handle_whipsaw_reentry(
    ticker: str,
    stop_out_history: list[dict],
    current_signal: dict
) -> bool:
    """
    손절 후 재진입 허용 여부
    
    규칙: 손절 후에도 Donchian 돌파가 재발생하면 진입 가능
    단, 포지션 한도 내에서만
    """
    # 특별한 제한 없음 — 돌파 신호가 다시 발생하면 새 포지션으로 진입
    # System 1 필터(직전 돌파 수익 여부)만 정상 적용
    return current_signal['signal']  # 신호가 있으면 진입
```

**Whipsaw는 정상이다**: 터틀 시스템에서 연속 손절은 흔하다. 승률이 35~40%이므로 10번 중 6~7번은 손절이다. 이것을 받아들이는 것이 시스템 트레이딩의 핵심이다.

---

## 8. 청산 (Exit) 규칙

### 8.1 System 1 청산

```
청산: 현재가가 최근 10 거래일의 최저가를 하향 이탈
```

```
Donchian_Lower_10 = min(Low[-10], Low[-9], ..., Low[-1])

청산 조건: Close_today < Donchian_Lower_10
```

**전량 청산** — 보유 중인 모든 유닛을 한 번에 매도한다. 부분 청산은 없다.

```python
def check_system1_exit(
    lows: list[float],
    closes: list[float],
    lookback: int = 10
) -> bool:
    """
    System 1 청산 확인: 10일 최저가 하향 이탈
    """
    if len(lows) < lookback + 1:
        return False
    
    # 10일 최저가 (오늘 제외)
    donchian_lower = min(lows[-(lookback + 1):-1])
    
    # 종가가 10일 최저가 아래인지
    return closes[-1] < donchian_lower
```

#### System 1 청산의 특성

| 특성 | 설명 |
|------|------|
| **수익 트레이드도 빨리 청산됨** | 10일 저가는 상대적으로 짧은 기간 → 작은 조정에도 청산 |
| **큰 수익 기회 제한** | 대형 추세를 끝까지 타지 못할 수 있음 |
| **원전의 어려운 규칙** | Curtis Faith에 의하면, 많은 터틀들이 이 규칙을 가장 따르기 어려워했음 |
| **심리적 함정** | "수익이 나고 있는데 왜 청산해?"라는 유혹 → 하지만 규칙은 규칙 |

**이것은 버그가 아니라 기능(feature)이다**: 빠른 청산은 작은 수익을 많이 쌓고, 큰 손실을 피하는 구조이다. 대형 수익은 System 2에 맡긴다.

### 8.2 System 2 청산

```
청산: 현재가가 최근 20 거래일의 최저가를 하향 이탈
```

```
Donchian_Lower_20 = min(Low[-20], Low[-19], ..., Low[-1])

청산 조건: Close_today < Donchian_Lower_20
```

**전량 청산** — 역시 모든 유닛을 한 번에 매도한다.

```python
def check_system2_exit(
    lows: list[float],
    closes: list[float],
    lookback: int = 20
) -> bool:
    """
    System 2 청산 확인: 20일 최저가 하향 이탈
    """
    if len(lows) < lookback + 1:
        return False
    
    donchian_lower = min(lows[-(lookback + 1):-1])
    return closes[-1] < donchian_lower
```

#### System 2 청산의 특성

| 특성 | 설명 |
|------|------|
| **추세를 더 오래 탈 수 있음** | 20일은 약 1개월 → 작은 조정을 견딤 |
| **큰 수익 포착 가능** | 대형 추세에서 더 긴 보유 기간 |
| **더 큰 되돌림 감수** | 고점 대비 더 많이 하락한 후 청산 → 이익의 일부를 반납 |

### 8.3 청산 vs 손절 우선순위

| 우선순위 | 이벤트 | 행동 |
|---------|--------|------|
| **1순위** | 손절 min(2N, 10%) 트리거 | **즉시 전량 매도** — 긴급 탈출 |
| **2순위** | Donchian 청산 트리거 | **종가 기준 전량 매도** — 정상 청산 |

```python
def check_exit_signals(
    position: dict,
    current_price: float,
    lows: list[float],
    closes: list[float]
) -> dict:
    """
    청산 신호 종합 확인 (우선순위 순)
    """
    # 1순위: 손절 확인 — min(2N, 10%) 하이브리드
    # 모든 유닛의 손절 중 가장 높은 것 (= 가장 타이트한 손절)
    highest_stop = max(unit['stop'] for unit in position['units'])
    if current_price <= highest_stop:
        return {
            'exit': True,
            'reason': 'STOP_LOSS',
            'trigger_price': highest_stop,
            'exit_all': True
        }
    
    # 2순위: Donchian 청산 확인
    system = position.get('system', 'S1')
    if system == 'S1':
        if check_system1_exit(lows, closes):
            return {
                'exit': True,
                'reason': 'SYSTEM1_EXIT',
                'trigger_price': min(lows[-11:-1]),
                'exit_all': True
            }
    elif system == 'S2':
        if check_system2_exit(lows, closes):
            return {
                'exit': True,
                'reason': 'SYSTEM2_EXIT',
                'trigger_price': min(lows[-21:-1]),
                'exit_all': True
            }
    
    return {'exit': False}
```

### 8.4 청산 시 주의사항

| 규칙 | 설명 |
|------|------|
| **전량 청산** | 부분 청산 없음. 해당 종목의 모든 유닛(1~4)을 한 번에 매도 |
| **종가 기준** | Donchian 청산은 종가 기준으로 판단. 장중 일시적 이탈은 무시 |
| **손절은 장중 적용** | min(2N, 10%) 손절가에 도달하면 장중이라도 즉시 실행 (손절은 긴급 탈출) |
| **갭 다운 처리** | 갭 다운으로 손절가 아래에서 시가가 열리면 → 시가(Market Open)에 즉시 매도 |
| **슬리피지 감수** | 갭 다운 시 손절가보다 낮은 가격에 체결될 수 있음 — 이는 시스템의 일부 |
| **재진입 가능** | 청산 후에도 해당 종목이 다시 Donchian 돌파 신호를 발생시키면 재진입 가능 |

### 8.5 갭 다운 처리 상세

```python
def handle_gap_down(position: dict, market_open_price: float) -> dict:
    """
    갭 다운 시 처리
    
    장전에 min(2N, 10%) 손절가 아래에서 시가가 형성된 경우
    """
    highest_stop = max(unit['stop'] for unit in position['units'])
    
    if market_open_price < highest_stop:
        # 시가에서 즉시 시장가 매도
        return {
            'exit': True,
            'reason': 'GAP_DOWN_STOP',
            'execution_price': market_open_price,  # 시가에서 체결
            'slippage': highest_stop - market_open_price,  # 추가 손실
            'exit_all': True
        }
    
    return {'exit': False}
```

---

## 9. 포지션 한도 (리스크 관리)

### 9.1 단일 종목 한도

```
최대 유닛 수: 4 유닛 per 종목
```

| 파라미터 | 값 |
|---------|-----|
| 최대 유닛 | **4** |
| 최대 계좌 리스크 (전체 손절 시) | **≤2.5%** (Minervini 사이징, 고변동 종목 10% 캡 적용 시 ~2.56%) |
| 피라미딩 간격 | **1/2 N** |

4 유닛 한도는 하나의 종목에 과도하게 집중되는 것을 방지한다. 4 유닛이 모두 손절되어도 계좌의 최대 2.5% (Minervini 리스크 기반 사이징)만 손실이므로, 회복이 매우 용이한 수준이다.

### 9.2 상관 종목 한도

상관관계가 높은 종목들은 동시에 손절될 확률이 높다 (min(2N, 10%) 손절 적용). 이를 방지하기 위해 **상관 그룹별 유닛 한도**를 설정한다.

#### "근접 상관" (Closely Correlated) 정의

```
근접 상관 = 같은 IBD Industry Group (197개 업종 분류)
예: 반도체 장비 업종 내의 ASML, LRCX, KLAC는 근접 상관
```

| 파라미터 | 값 |
|---------|-----|
| 최대 유닛 (근접 상관) | **6 유닛** |
| 정의 | 같은 IBD Industry Group 내 종목 |
| 예시 | 반도체 업종에 NVDA(4) + AMD(2) = 6유닛까지 허용 |

#### "느슨한 상관" (Loosely Correlated) 정의

```
느슨한 상관 = 같은 GICS Sector (11개 섹터 분류)
예: Technology 섹터 내의 반도체, 소프트웨어, 하드웨어는 느슨한 상관
```

| 파라미터 | 값 |
|---------|-----|
| 최대 유닛 (느슨한 상관) | **10 유닛** |
| 정의 | 같은 GICS Sector 내 종목 |
| 예시 | Tech 섹터에 NVDA(4) + MSFT(3) + CRM(3) = 10유닛까지 허용 |

#### GICS 11개 섹터 목록

```
1. Information Technology (정보기술)
2. Health Care (헬스케어)
3. Financials (금융)
4. Consumer Discretionary (임의소비재)
5. Communication Services (커뮤니케이션)
6. Industrials (산업재)
7. Consumer Staples (필수소비재)
8. Energy (에너지)
9. Utilities (유틸리티)
10. Real Estate (부동산)
11. Materials (소재)
```

### 9.3 전체 포트폴리오 한도

| 방향 | 최대 유닛 |
|------|----------|
| **롱 방향** | **12 유닛** |
| **숏 방향** | **12 유닛** (숏 활성화 시) |
| **합계** | **24 유닛** (양방향) |
| **롱 온리 모드** | **12 유닛** (기본 설정) |

```python
def check_position_limits(
    portfolio: dict,
    ticker: str,
    industry_group: str,
    gics_sector: str
) -> dict:
    """
    포지션 한도 확인
    
    Args:
        portfolio: {ticker: {'units': int, 'industry': str, 'sector': str}, ...}
        ticker: 진입 대상 종목
        industry_group: IBD 업종 그룹
        gics_sector: GICS 섹터
    
    Returns:
        {'allowed': bool, 'reason': str}
    """
    current_ticker_units = portfolio.get(ticker, {}).get('units', 0)
    
    # 1. 단일 종목 한도 (4 유닛)
    if current_ticker_units >= MAX_UNITS_SINGLE:
        return {
            'allowed': False, 
            'reason': f'단일 종목 한도 초과: {ticker} = {current_ticker_units}/{MAX_UNITS_SINGLE}'
        }
    
    # 2. 근접 상관 한도 (6 유닛)
    correlated_units = sum(
        p['units'] for t, p in portfolio.items() 
        if p.get('industry') == industry_group
    )
    if correlated_units >= MAX_UNITS_CORRELATED:
        return {
            'allowed': False, 
            'reason': f'근접 상관 한도 초과: {industry_group} = {correlated_units}/{MAX_UNITS_CORRELATED}'
        }
    
    # 3. 느슨한 상관 한도 (10 유닛)
    loosely_correlated_units = sum(
        p['units'] for t, p in portfolio.items() 
        if p.get('sector') == gics_sector
    )
    if loosely_correlated_units >= MAX_UNITS_LOOSELY_CORRELATED:
        return {
            'allowed': False, 
            'reason': f'느슨한 상관 한도 초과: {gics_sector} = {loosely_correlated_units}/{MAX_UNITS_LOOSELY_CORRELATED}'
        }
    
    # 4. 전체 포트폴리오 한도 (12 유닛 롱)
    total_long_units = sum(p['units'] for p in portfolio.values())
    if total_long_units >= MAX_UNITS_LONG:
        return {
            'allowed': False, 
            'reason': f'전체 포트폴리오 한도 초과: {total_long_units}/{MAX_UNITS_LONG}'
        }
    
    return {'allowed': True}
```

### 9.4 리스크 수학

#### 최악의 시나리오 분석

```
Minervini 리스크 기반 사이징에서 유닛당 리스크 = 정확히 1%.
피라미딩 4유닛 시 종목당 최대 리스크 ≤ 2.5% (§7.4 참조).

시나리오 1: 모든 종목이 4유닛 피라미딩 후 동시 손절
  - 3 종목 × 4 유닛 = 12 유닛
  - 종목당 리스크: ≤2.5% (Minervini 사이징, 고변동 종목 10% 캡 적용 시 ~2.56%)
  - 총 리스크: 3 × 2.5% = **7.5%** (이론적 최대)

시나리오 2: 각 종목이 1유닛씩 12종목에서 손절
  - 12 종목 × 1 유닛 = 12 유닛
  - 종목당 리스크: 1.0% (유닛당 정확히 1%)
  - 총 리스크: 12 × 1.0% = **12.0%** ← 이론적 최악

시나리오 3: 현실적 혼합 (가장 가능성 높은)
  - 2 종목 × 4 유닛 + 2 종목 × 2 유닛 = 12 유닛
  - 리스크: 2 × 2.5% + 2 × (0.5% + 1.0%) = **8.0%**
```

#### CANSLIM과의 비교

| 항목 | CANSLIM 순수 | 터틀 하이브리드 |
|------|-------------|--------------|
| 종목당 최대 리스크 | 8% × 20% 비중 = 1.6% | ≤2.5% (4유닛 피라미딩 시, Minervini 사이징) |
| 최대 포트폴리오 리스크 | 5종목 × 1.6% = 8.0% | 7.5~12% (시나리오별, §9.4 참조) |
| 리스크 정규화 | 없음 (동일 비중) | 있음 (변동성 기반) |
| 리스크 조절 방식 | 시장 상태별 투자 비중 조절 | 유닛 수 제한 |

**터틀 하이브리드 vs CANSLIM 리스크 비교**: Minervini 리스크 기반 사이징 적용 후, 터틀 하이브리드의 최대 포트폴리오 리스크(7.5~12%)와 CANSLIM(8.0%)은 유사한 수준이다. 다만 터틀은 피라미딩 구조로 대형 추세에서 더 큰 수익을 추구하며, 승률은 낮지만 (35~40%) 평균 수익이 평균 손실의 수 배이므로 기대값이 양수이다.

### 9.5 리스크 완화 옵션

보수적 운용을 원하는 경우 다음을 조정할 수 있다:

```python
# 보수적 설정
MAX_UNITS_LONG_CONSERVATIVE = 8       # 12 → 8
RISK_PER_UNIT_PCT_CONSERVATIVE = 0.005  # 1% → 0.5%

# 이 경우:
# 8 유닛 × 0.5% = 4% 최대 리스크 (매우 보수적)
```

---

## 10. 전체 상수 요약 (코드용)

```python
# ============================================================
# CANSLIM × TURTLE TRADING HYBRID STRATEGY
# 전체 상수 정의 (코드 구현용)
# ============================================================
#
# 이 파일의 모든 상수는 "하나의 숫자, 하나의 의미"를 가진다.
# 애매한 범위(예: "2~3%")가 아닌 정확한 값만 사용한다.
#
# 참조: CANSLIM 종목 선정 상수는 QUANTIFIED_STRATEGY.md 참조
# ============================================================


# ============================================================
# ATR (N) 계산
# ============================================================
ATR_PERIOD = 20                        # N 계산 기간 (20일)
ATR_METHOD = "EMA"                     # 지수이동평균 (터틀 원전)
ATR_SMOOTHING_FACTOR = 1 / 20          # EMA 평활 계수 = 0.05


# ============================================================
# 진입 (Donchian Channel Breakout)
# ============================================================

# System 1 — 단기
SYSTEM1_ENTRY_DAYS = 20                # 20일 최고가 돌파로 진입
SYSTEM1_EXIT_DAYS = 10                 # 10일 최저가 이탈로 청산
SYSTEM1_FILTER_ENABLED = True          # 직전 돌파 수익 시 건너뛰기 (원전 규칙)

# System 2 — 장기
SYSTEM2_ENTRY_DAYS = 55                # 55일 최고가 돌파로 진입
SYSTEM2_EXIT_DAYS = 20                 # 20일 최저가 이탈로 청산
SYSTEM2_FILTER_ENABLED = False         # 필터 없음 — 모든 돌파에 진입

# 진입 기준
ENTRY_PRICE_BASIS = "CLOSE"            # "CLOSE" = 종가 기준, "HIGH" = 장중 기준


# ============================================================
# 포지션 사이징 (Minervini 리스크 기반)
# ============================================================
RISK_PER_UNIT_PCT = 0.01               # 유닛당 리스크: 계좌의 1%
# actual_stop = min(STOP_LOSS_N × N, entry_price × STOP_LOSS_MAX_PCT)
# Unit (shares) = (Account × RISK_PER_UNIT_PCT) / actual_stop
MAX_SINGLE_UNIT_PCT = 0.30             # 단일 유닛 최대 비중: 계좌의 30%
MAX_SINGLE_POSITION_PCT = 0.40         # 단일 포지션(4유닛) 최대 비중: 계좌의 40%


# ============================================================
# 피라미딩 (Pyramiding)
# ============================================================
MAX_UNITS_PER_STOCK = 4                # 종목당 최대 4 유닛
PYRAMID_INTERVAL_N = 0.5               # 추가 진입 간격: 1/2 N (= 0.5 × ATR)
# 추가 유닛 트리거: 직전 진입가 + PYRAMID_INTERVAL_N × N


# ============================================================
# 손절 (Stop Loss)
# ============================================================
STOP_LOSS_N = 2.0                      # 터틀 기본 손절 폭: 2N (= 2 × ATR)
STOP_LOSS_MAX_PCT = 0.10               # 최대 손절 캡: 10% (진입가 대비)
# 하이브리드 손절 = max(진입가 - 2N, 진입가 × 0.90)
# = 진입가 - min(2N, 진입가 × 10%)
# N/P ≤ 5%: 2N 적용 (10% 캡 미작동)
# N/P > 5%: 10% 캡 작동 (2N 대신 10%가 더 타이트)
# 피라미딩 시: 모든 손절 = 최신 진입가 기준 min(2N, 10%) (좁히기만 가능)
STOP_LOSS_MOVE_DIRECTION = "UP_ONLY"   # 손절은 올리기만 가능, 내리기 금지


# ============================================================
# 포지션 한도 (Position Limits)
# ============================================================
MAX_UNITS_SINGLE = 4                   # 단일 종목: 4 유닛
MAX_UNITS_CORRELATED = 6               # 근접 상관 (같은 IBD Industry Group): 6 유닛
MAX_UNITS_LOOSELY_CORRELATED = 10      # 느슨한 상관 (같은 GICS Sector): 10 유닛
MAX_UNITS_LONG = 12                    # 롱 방향 전체: 12 유닛
MAX_UNITS_SHORT = 12                   # 숏 방향 전체: 12 유닛 (숏 활성화 시)
MAX_UNITS_TOTAL = 24                   # 양방향 합계: 24 유닛


# ============================================================
# 시장 방향 필터
# ============================================================
MARKET_MA_PERIOD = 200                 # 200일 단순이동평균
MARKET_MA_TYPE = "SMA"                 # 단순이동평균
MARKET_BENCHMARK = "SPY"               # S&P 500 ETF
MARKET_FILTER_RULE = "ABOVE_MA"        # 종가 > MA이면 진입 허용
MARKET_FILTER_BUFFER_PCT = 0.00        # 버퍼 없음 (0% = 정확히 MA 기준)

# 시장 필터 적용 범위
MARKET_FILTER_APPLIES_TO = "NEW_ENTRIES"  # 신규 진입에만 적용
# 기존 포지션은 시장 필터와 무관하게 터틀 청산 규칙으로 관리


# ============================================================
# 공매도 (Short Selling) — 기본 비활성
# ============================================================
SHORT_ENABLED = False                  # 기본값: 숏 비활성
SHORT_SYSTEM1_ENTRY_DAYS = 20          # 20일 최저가 하향 돌파
SHORT_SYSTEM2_ENTRY_DAYS = 55          # 55일 최저가 하향 돌파
SHORT_SYSTEM1_EXIT_DAYS = 10           # 10일 최고가 돌파 시 커버
SHORT_SYSTEM2_EXIT_DAYS = 20           # 20일 최고가 돌파 시 커버
SHORT_MARKET_CONDITION = "BELOW_MA"    # SPY < 200MA일 때만 숏 허용


# ============================================================
# CANSLIM 종목 선정 상수 (QUANTIFIED_STRATEGY.md 참조)
# 아래는 핵심 임계값만 반복 기재 — 상세는 원본 참조
# ============================================================
CANSLIM_MIN_QUARTERLY_EPS_GROWTH = 0.25   # C: +25% YoY
CANSLIM_MIN_ANNUAL_EPS_CAGR = 0.25        # A: +25% 5년 CAGR
CANSLIM_MIN_RS_RATING = 80                # L: RS Rating ≥ 80
CANSLIM_MIN_EPS_RATING = 80               # EPS Rating ≥ 80
CANSLIM_MIN_COMPOSITE_RATING = 90         # Composite ≥ 90
CANSLIM_MIN_INSTITUTIONAL_HOLDERS = 5     # I: 최소 5개 기관
CANSLIM_MIN_ADV = 500_000                 # S: 최소 일평균 50만주
CANSLIM_MAX_DEBT_TO_EQUITY = 2.0          # D/E ≤ 2.0
CANSLIM_MIN_PRICE = 10.0                  # 최소 주가 $10
CANSLIM_INDUSTRY_RANK_MAX = 40            # 업종 상위 40위


# ============================================================
# 유동성 및 실행 제한
# ============================================================
MAX_POSITION_PCT_OF_ADV = 0.05         # 유닛 크기 ≤ 일평균 거래량의 5%
EXECUTION_PRICE_BASIS = "CLOSE"        # 진입/청산: 종가 기준
STOP_EXECUTION = "INTRADAY"            # 손절: 장중 즉시 실행
GAP_DOWN_HANDLING = "MARKET_OPEN"      # 갭 다운: 시가에 시장가 매도


# ============================================================
# 시스템 운영 파라미터
# ============================================================
LOOKBACK_DATA_DAYS = 300               # 최소 필요 가격 데이터: 300일 (200MA + 여유)
REBALANCE_FREQUENCY = "DAILY"          # 매일 장 마감 후 신호 확인
ACCOUNT_EQUITY_BASIS = "TOTAL"         # 계좌 자본 = 현금 + 포지션 평가액 합계
```

---

## 11. CANSLIM 순수 전략과의 비교표

### 11.1 항목별 비교

| 항목 | CANSLIM 순수 | 터틀 하이브리드 |
|------|-------------|--------------|
| **종목 선정** | CANSLIM (C, A, N, S, L, I, M) | CANSLIM (C, A, N, S, L, I) — M 제외 |
| **시장 필터** | FTD / Distribution Day (5상태) | 200일 MA (2상태) |
| **진입 트리거** | 피벗 포인트 돌파 (Cup & Handle 등) | Donchian Channel 돌파 (20일/55일) |
| **진입 거래량 조건** | ADV × 1.50 이상 | 없음 (가격 돌파만) |
| **포지션 사이징** | 동일 비중 (20% × 5종목) | Minervini 리스크 기반 (유닛당 정확히 1% 리스크, 변동성 정규화) |
| **피라미딩** | 50% → 30% → 20% (가격 +2.5%, +5%) | 유닛 × 4 (매 1/2 N 간격) |
| **손절** | -8% 절대 손절 | min(2N, 10%) 하이브리드 (ATR 기반 + 10% 캡) |
| **트레일링 스톱** | +15%→BEP-5%, +20%→BEP | 없음 (Donchian 청산이 대체) |
| **청산** | Climax Top, 기술적 신호, RS 하락 등 복수 규칙 | 10일 저가 (S1) / 20일 저가 (S2) |
| **보유 기간 관리** | 8주 보유 규칙, 13주 무반응 매도 | 자동 (청산룰이 결정) |
| **최대 종목 수** | 2~7 (계좌 규모별) | 유닛 기반 (12유닛 ÷ 종목당 유닛) |
| **상관 관리** | 업종 상위 40위 확인 | 업종 6유닛, 섹터 10유닛 한도 |

### 11.2 장단점 비교

| 측면 | CANSLIM 순수 | 터틀 하이브리드 |
|------|-------------|--------------|
| **장점** | 높은 승률 (40~50%), 선별적 진입, 다양한 매도 규칙으로 이익 극대화 | 100% 기계적 실행, 감정 개입 불가, 변동성 정규화, 피라미딩 효과 |
| **장점** | 차트 패턴 인식으로 최적 진입 타이밍 | 코드 구현 단순 (조건이 모두 숫자), 백테스팅 정확 |
| **장점** | 시장 상태별 세밀한 비중 조절 | System 1/2 이중 안전망으로 대형 추세 포착 |
| **단점** | 차트 패턴 인식의 주관성, 구현 복잡 | 낮은 승률 (35~40%), 연속 손절의 심리적 부담 (10% 캡으로 완화) |
| **단점** | 매도 규칙이 복잡 (10개+ 규칙) | 수익 트레이드도 빨리 청산 (10일 저가) |
| **단점** | 실시간 Distribution Day 추적 필요 | 피라미딩으로 포지션 금액 커질 수 있음 |
| **적합 대상** | 차트 해석에 능숙한 트레이더 | 규칙 기반 시스템 트레이더, 알고리즘 봇 |
| **정서적 요구** | 매도 타이밍에서 주관적 판단 필요 | 연속 손절 인내력 필요 (6~7/10 실패) |

### 11.3 성과 기대치 비교

| 지표 | CANSLIM 순수 | 터틀 하이브리드 (예상) |
|------|-------------|---------------------|
| 기대 승률 | 35~50% | 35~40% |
| 평균 수익 (winner) | +20~30% | +30~80% (피라미딩 + 장기 보유 효과) |
| 평균 손실 (loser) | -7~8% | -4~10% (min(2N, 10%) 기반, 종목마다 다름, 최대 10% 캡) |
| 손익비 (R:R) | 2.5:1 ~ 4:1 | 3:1 ~ 8:1 (소수의 대형 수익이 지배) |
| 최대 낙폭 (예상) | 15~25% | 10~20% (Minervini 사이징 + 10% 캡으로 순수 터틀 대비 MDD 대폭 개선) |
| 연간 거래 횟수 | 30~60회 | 40~80회 (재진입 포함) |

---

## 부록 A: 터틀 트레이딩 원전 출처

### A.1 원전 자료

| 출처 | 저자 | 연도 | 핵심 내용 |
|------|------|------|----------|
| **The Original Turtle Trading Rules** | Curtis Faith | 2003 | 터틀 프로그램 원전 규칙의 최초 공개 문서. 무료 배포 |
| **Way of the Turtle** | Curtis Faith | 2007 | 터틀 트레이더 출신의 상세 회고록. 심리적 측면과 실전 경험 포함 |
| **The Complete TurtleTrader** | Michael Covel | 2007 | 터틀 프로그램의 역사, Richard Dennis와 William Eckhardt의 이야기 |
| **Trend Following** | Michael Covel | 2004 | 추세추종 전략 전반. 터틀 시스템 포함 |

### A.2 핵심 인물

| 이름 | 역할 |
|------|------|
| **Richard Dennis** | 터틀 프로그램 창시자. "거래는 가르칠 수 있다"고 주장 |
| **William Eckhardt** | Dennis의 파트너. "거래는 타고나야 한다"고 주장. Dennis와 내기 |
| **Curtis Faith** | 가장 성공적인 터틀 중 한 명. 원전 규칙 최초 공개자 |
| **Jerry Parker** | 터틀 출신. Chesapeake Capital 설립, 현재까지 운용 중 |

### A.3 터틀 실험의 역사적 배경

1983년, Richard Dennis와 William Eckhardt는 "성공적인 트레이더를 양성할 수 있는가"에 대해 의견이 갈렸다. Dennis는 가르칠 수 있다고 주장했고, Eckhardt는 타고난 재능이 필요하다고 주장했다. 이 논쟁을 해결하기 위해 Dennis는 월스트리트 저널에 광고를 내고 지원자를 모집했다.

1,000명 이상의 지원자 중 23명이 선발되어 2주간 교육을 받았다. 이 교육 내용이 바로 이 문서에서 사용하는 터틀 트레이딩 규칙이다. 5년간의 실험에서 터틀들은 연평균 80% 이상의 수익률을 기록했다.

**이 실험이 증명한 것**: 명확하고 기계적인 규칙 + 규칙을 따르는 규율 = 수익 가능한 트레이딩. Dennis가 논쟁에서 이겼다.

### A.4 Donchian Channel의 기원

Richard Donchian(1905~1993)이 개발한 가격 채널 기법. 터틀 시스템의 진입/청산 규칙은 Donchian의 "4주 규칙"(20 거래일)에서 직접 유래했다.

```
Donchian의 4주 규칙 (1960년대):
- 매수: 최근 4주 최고가 돌파 시
- 매도: 최근 4주 최저가 이탈 시
```

터틀 시스템은 이 단순한 규칙에 ATR 기반 포지션 사이징, 피라미딩, 포지션 한도를 추가하여 완전한 트레이딩 시스템으로 발전시켰다.

---

## 부록 B: 하이브리드 전략의 예상 성과 특성

### B.1 기대 승률

| 시스템 | 예상 승률 | 근거 |
|--------|----------|------|
| 터틀 원전 (선물) | 35~40% | Curtis Faith 공개 데이터 |
| 터틀 + CANSLIM 필터 | **40~45%** (추정) | CANSLIM으로 품질 종목만 선별 → 돌파 성공률 개선 |

**CANSLIM 필터가 승률을 개선하는 이유**:

1. CANSLIM 종목은 이미 펀더멘털이 우수한 성장주 → 돌파 후 추세 지속 확률 높음
2. 기관 매집이 확인된 종목 → 돌파 후 기관의 추가 매수가 추세를 지지
3. RS Rating 80+ 종목 → 이미 시장 대비 강한 모멘텀 보유
4. 업종 상위 40위 → 섹터 로테이션의 수혜 종목

### B.2 수익 분포 특성

터틀 시스템(추세추종 전반)의 수익 분포는 **정규분포가 아닌 양의 비대칭(positive skew)**이다:

```
전형적인 100회 거래 분포:

  손실 거래 (~60회):
    -10%~-5%:  ████████████████████████████  (28회, 소형 손실)
    -5%~-2%:   ████████████████████████      (24회, 미니 손실)
    -2%~0%:    ████████                       (8회, 손익분기 근처)
    
  수익 거래 (~40회):
    0%~+5%:    ██████████████                 (14회, 소형 수익)
    +5%~+20%:  ██████████████                 (14회, 보통 수익)
    +20%~+50%: ████████                       (8회, 대형 수익)
    +50%~+100%:████                           (3회, 초대형 수익)
    +100%+:    █                              (1회, 블랙스완 수익)
```

**핵심**: 상위 3~5개 거래가 전체 수익의 대부분을 차지한다. 이것이 "Let winners run" 원칙의 실제 모습이다.

### B.3 드로다운 특성

| 드로다운 유형 | 예상 범위 | 기간 |
|-------------|----------|------|
| 일상적 드로다운 | -5% ~ -10% | 1~4주 |
| 보통 드로다운 | -10% ~ -15% | 1~3개월 |
| 심한 드로다운 | -15% ~ -25% | 3~6개월 |
| 극단적 드로다운 | -25% ~ -35% | 6~12개월 (약세장) |

**드로다운 발생 패턴**:

추세추종 시스템은 **횡보장(Range-bound market)**에서 가장 고통스럽다. 돌파 후 바로 반전되는 whipsaw가 반복되기 때문이다. 그러나 CANSLIM 필터가 이를 부분적으로 완화한다 — 펀더멘털이 우수한 종목은 무의미한 횡보 돌파보다 진정한 추세 돌파를 더 자주 보여주기 때문이다.

### B.4 CANSLIM 필터가 터틀 원전 성과를 개선할 것으로 기대하는 영역

| 영역 | 터틀 원전 (무필터) | CANSLIM 필터 적용 시 |
|------|-----------------|-------------------|
| 가짜 돌파 빈도 | 높음 (모든 종목에 진입) | **감소** (품질 종목만) |
| 연속 손절 횟수 | 많음 (8~10회 연속 가능) | **감소** (5~7회로 추정) |
| 평균 수익 크기 | 보통 | **증가** (성장주의 추세 지속력) |
| 최대 낙폭 | 높음 | **감소** (시장 필터 + 품질 종목) |

### B.5 운용 시 핵심 마인드셋

1. **승률에 집착하지 않는다** — 35~45% 승률은 정상이다. 100번 중 55~65번 손절은 시스템이 작동하고 있다는 증거이다.

2. **연속 손절을 기대한다** — 5~7번 연속 손절은 흔하다. 이것에 감정적으로 반응하면 시스템을 포기하게 된다.

3. **한 번의 대형 수익이 다수의 소형 손실을 보상한다** — 이것이 추세추종의 본질이다. 100번의 거래 중 3~5번의 대형 수익이 전체 성과를 결정한다.

4. **시스템을 신뢰하고, 시스템을 따른다** — Richard Dennis: "내가 규칙을 모두 신문에 공개해도, 사람들은 따르지 않을 것이다. 왜냐하면 그들은 자신의 감정을 이길 수 없기 때문이다."

5. **가장 어려운 순간이 가장 중요하다** — 연속 손절 후의 다음 진입 신호가 대형 수익을 줄 수 있다. 그 신호를 건너뛰면 시스템이 무너진다.

---

## 부록 C: 전체 매매 플로우 다이어그램

```
                          ┌─────────────────────────┐
                          │    매일 장 마감 후 실행    │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  1. 시장 필터 확인         │
                          │  SPY 종가 > 200일 SMA?    │
                          └────────────┬────────────┘
                                 Yes / No
                              ┌────┘    └────┐
                              │              │
                    ┌─────────▼─────┐  ┌─────▼──────────────┐
                    │  신규 진입 허용  │  │  신규 진입 차단       │
                    └─────────┬─────┘  │  기존 포지션:         │
                              │        │  터틀 청산룰만 적용    │
                              │        └────────────────────┘
                    ┌─────────▼──────────────────┐
                    │  2. CANSLIM 관심 종목 풀 확인  │
                    │  필터 통과 종목 목록 조회       │
                    └─────────┬──────────────────┘
                              │
                    ┌─────────▼──────────────────┐
                    │  3. 각 종목별 Donchian 확인    │
                    │  System 1: 20일 최고가 돌파?   │
                    │  System 2: 55일 최고가 돌파?   │
                    └─────────┬──────────────────┘
                       Signal / No Signal
                     ┌────┘        └──→ 다음 종목
                     │
           ┌─────────▼──────────────────┐
           │  4. 포지션 한도 확인          │
           │  단일(4), 상관(6),           │
           │  느슨(10), 전체(12) 미달?     │
           └─────────┬──────────────────┘
                Pass / Fail
              ┌────┘    └──→ 진입 불가
              │
    ┌──────────▼───────────────────────────┐
    │  5. 유닛 크기 계산 (Minervini)        │
    │  stop = min(2N, Price×10%)           │
    │  Unit = (Account×1%) / stop          │
    │  유동성 제한 + 비중 제한 적용          │
    └──────────┬───────────────────────────┘
              │
    ┌─────────▼──────────────────┐
    │  6. 진입 실행               │
    │  매수: Unit 주수             │
    │  손절 설정: max(진입가-2N,     │
    │            진입가×0.90)      │
    └─────────┬──────────────────┘
              │
              ▼
    ┌──────────────────────────────────────┐
    │  7. 보유 중 매일 확인                   │
    │                                       │
    │  A. 피라미딩 조건? (+1/2N → 추가 진입)   │
    │  B. 손절 트리거? (가격 ≤ 손절가)         │
    │  C. Donchian 청산? (S1: 10일 저가,      │
    │                     S2: 20일 저가)      │
    └─────────┬────────────────────────────┘
              │
        ┌─────┼──────┐
        A     B      C
        │     │      │
   피라미딩  손절    청산
   (반복)  (전량)  (전량)
```

---

## 부록 D: 빈번한 질문 (FAQ)

### Q1. CANSLIM 피벗 포인트 돌파와 Donchian 20일 돌파는 어떻게 다른가?

**CANSLIM 피벗**: Cup & Handle, Double Bottom 등 특정 차트 패턴의 저항선을 돌파하는 것. 패턴 인식이 필요하며 주관적 판단이 개입될 수 있다.

**Donchian 20일 돌파**: 최근 20 거래일의 최고가를 넘는 것. 패턴 인식 불필요. 숫자 하나로 결정된다. 차트 패턴과 무관하게 가격이 일정 기간의 고점을 넘으면 진입한다.

실무적으로, CANSLIM 기준을 통과한 종목이 적절한 베이스를 형성한 후 돌파할 때 두 신호가 비슷한 시점에 발생할 수 있다. 그러나 Donchian 20일 돌파는 패턴의 형태에 의존하지 않으므로 더 기계적이다.

### Q2. 왜 CANSLIM의 -8% 손절 대신 min(2N, 10%)을 쓰는가?

| 종목 | 주가 | N (ATR) | CANSLIM -8% | 순수 2N | **min(2N, 10%)** |
|------|------|---------|-------------|---------|-----------------|
| 저변동성 주식 | $100 | $1.50 | -$8.00 (너무 넓음) | -$3.00 | **-$3.00 (2N)** |
| 보통 주식 | $100 | $4.00 | -$8.00 (적절) | -$8.00 | **-$8.00 (2N)** |
| 고변동성 주식 | $100 | $6.00 | -$8.00 (너무 좁음) | -$12.00 (너무 넓음) | **-$10.00 (10% 캡)** |
| 극고변동성 주식 | $100 | $8.00 | -$8.00 (너무 좁음) | -$16.00 (너무 넓음) | **-$10.00 (10% 캡)** |

min(2N, 10%) 하이브리드 손절은 **양쪽의 장점을 결합**한다:
- **저~중변동 종목 (N/P ≤ 5%)**: 2N이 자동 적용 → 변동성 적응형 손절의 장점 유지
- **고변동 종목 (N/P > 5%)**: 10% 캡이 작동 → 순수 2N의 과도한 손실(12~16%) 방지
- CANSLIM의 8%보다 약간 넓은 10%를 캡으로 설정하여, 고변동 성장주에서의 whipsaw를 줄이면서도 피라미딩 4유닛이 가능하도록 균형을 맞춤

### Q3. System 1과 System 2를 동시에 운용하는가?

예. 같은 종목에 대해 System 1과 System 2가 동시에 작동할 수 있다. 다만, 한 종목에 대해 이미 System 1로 포지션을 보유 중이면 System 2 진입은 추가 유닛으로 처리된다 (4유닛 한도 내에서).

일반적인 시나리오:
1. System 1 (20일 돌파)에서 진입 → 피라미딩 → 10일 저가에서 청산
2. System 1에서 필터(이전 돌파 수익)로 건너뜀 → System 2 (55일 돌파)에서 진입 → 20일 저가에서 청산

### Q4. 시장 필터가 OFF일 때 기존 포지션은 어떻게 되는가?

SPY가 200일 MA 아래로 하락해도, **기존 포지션은 터틀 청산 규칙으로만 관리**한다:

- 손절 min(2N, 10%)에 도달하면 청산
- Donchian 청산 (10일/20일 저가)에 도달하면 청산
- 시장 필터 OFF라고 해서 즉시 전량 매도하지는 않음

이유: 개별 종목이 시장과 반대로 움직일 수 있기 때문이다. 시장 필터는 **신규 진입만 차단**하고, 기존 포지션은 각자의 리스크 관리 규칙에 맡긴다.

---

*이 문서는 CANSLIM의 종목 선정 능력과 터틀 트레이딩의 기계적 매매 규율을 결합한 하이브리드 전략의 완전한 명세서이다.*
*모든 파라미터가 정확한 숫자로 정의되어 있으며, 코드 구현 시 이 문서의 상수와 공식만으로 완전한 매매 시스템을 구축할 수 있다.*
*원전 출처: Richard Dennis & William Eckhardt (1983), Curtis Faith "Way of the Turtle" (2007), William O'Neil "How to Make Money in Stocks"*
