# 2026-03-05 손절/청산 트리거 버그 5개 수정

## 배경
- UGP 1주 매도 테스트 → Paper 모드에서 정상 체결 확인 (주문번호 0000040978)
- 이후 손절/청산 파이프라인 전체 코드 리뷰 → 치명적 버그 5개 발견

---

## Bug #1 (CRITICAL): precomputed_signals 없는 포지션 → 손절 도달 불가

**파일**: `bot/intraday_monitor.py` L282-285

**문제**:
```python
signals = self.precomputed_signals.get(ticker)
if signals is None:
    return  # ← 여기서 함수 전체가 종료됨
```

`precomputed_signals`는 장전 스크리닝(pre_market)에서 워치리스트 종목에 대해서만 계산된다.
하지만 **이미 보유 중인 포지션 종목이 워치리스트에서 빠지면** signals가 없다.

`trading_bot.py`에서 open positions의 ticker를 WebSocket 구독 목록에는 추가하지만:
```python
tickers = list(self._intraday.precomputed_signals.keys())
for pos in open_positions:
    if pos.ticker not in tickers:
        tickers.append(pos.ticker)  # WS 구독에만 추가
# precomputed_signals에는 추가 안 함 ← 버그
```

**결과**: 틱은 수신되지만 `signals is None`에서 즉시 return → **손절/청산 로직에 도달하지 못함**

**왜 치명적인가**:
- 터틀 트레이딩의 핵심은 **손절(stop-loss)**. 손절이 안 되면 큰 손실이 발생
- 워치리스트는 매일 바뀜 → 어제 진입한 종목이 오늘 워치리스트에서 빠질 수 있음
- 이 경우 보유 종목의 손절이 **완전히 비활성화**됨
- 봇은 정상 작동하는 것처럼 보이지만 실제로는 손절 보호 없이 방치

**수정**:
```python
signals = self.precomputed_signals.get(ticker)
position = await self._position_mgr.get_position(ticker)

# signals 없고 포지션도 없으면 무시
if signals is None and position is None:
    return

# Priority 1: 손절 체크 (signals 불필요, position만 있으면 가능)
if position is not None:
    stop_hit = check_stop_hit(price, position.current_stop_price)
    ...

# signals 없으면 피라미딩/진입/Donchian은 불가 → 여기서 return
if signals is None:
    return
```

---

## Bug #2 (MEDIUM): 손절 쿨다운 중 return → Donchian 청산도 차단

**파일**: `bot/intraday_monitor.py` L294-297

**문제**:
```python
if stop_hit:
    cd = self._stop_loss_cooldown.get(ticker, 0.0)
    if now_mono - cd < self._STOP_LOSS_COOLDOWN:
        return  # ← Donchian 청산(Priority 4)도 실행 안 됨!
```

손절 주문이 실패하면 120초 쿨다운이 설정된다.
이 쿨다운 기간 동안 `return`으로 함수 전체가 종료되어 Donchian 청산 체크도 막힌다.

**왜 문제인가**:
- 손절 실패(API 오류 등) 후 120초 동안 **어떤 매도 로직도 작동 안 함**
- 급락 중에 손절 실패 → 쿨다운 → Donchian 청산도 차단 → 더 큰 손실

**수정**: 쿨다운 시 손절만 skip, Donchian 청산은 fall-through로 계속 체크

---

## Bug #3 (MEDIUM): SUBMITTED 매도 주문이 새 손절 재발동 차단 (2시간)

**파일**: `broker/order_executor.py` L474

**문제**:
```python
if age_s > 7200 and (order.filled_shares or 0) == 0:  # 2시간
```

매도 주문이 SUBMITTED 상태로 남아있으면 `has_submitted_order()`가 새 손절 시도를 차단.
auto-expire가 2시간이라, 체결 매칭 실패 시 **2시간 동안 손절 불가**.

**수정**: 매도 주문 expire 시간을 2시간 → 30분으로 단축
```python
expire_seconds = 1800 if order.side == OrderSide.SELL else 7200
```

---

## Bug #4 (LOW): execute_exit_sell 재시도 없음

**파일**: `broker/order_executor.py` L265-293

**문제**: 손절(`execute_stop_loss_sell`)은 3회 재시도하지만, 청산(`execute_exit_sell`)은 1회뿐.
장 마감 직전 API 과부하 시 청산 실패 가능.

**수정**: 2회 재시도 추가 (가격 갱신 후 재시도)

---

## Bug #5 (LOW): REST 폴백 시 30초 손절 지연

**파일**: `config/constants.py` L188

**문제**: WebSocket 장애 → REST 폴백 모드에서 30초 간격 폴링. 급락 시 최대 30초 지연.

**수정**: 30초 → 10초로 단축

---

## 수정 파일 목록
1. `bot/intraday_monitor.py` — Bug #1, #2
2. `broker/order_executor.py` — Bug #3, #4
3. `config/constants.py` — Bug #5

## 배포
- 서버에 scp로 3개 파일 배포 후 `systemctl restart snowa-bot.service`
