# 2026-05-27 US 장 감시 내역

## 감시 개요
- 감시 대상: Vultr production `snowa-bot.service`
- 전략 기준: `TURTLE_TRADING_STRATEGY.md`
- 핵심 확인 항목: US live entry, sizing, Donchian breakout, pyramiding, stop/exit handling

## 확인된 production 상태
- 서비스 재시작 후 정상 active.
- US intraday websocket/rest polling 정상 시작.
- market filter: pass, regime=YELLOW, regime_scale=0.5.
- 현재 US open positions:
  - BFH: S1, 1주, avg 89.1198, stop 83.35
  - COCO: S1, 5주, avg 69.87, stop 63.52
  - DELL: S1, 1주, avg 304.98, stop 277.46
  - EZPW: S1, 54주, avg 33.6333, stop 32.22, 3 units

## 발견 및 수정한 버그

### 1. US intraday cash 계산 누락
- 증상: AMD/DELL이 S1/S2 돌파 상태였지만 `entry_skipped_sizing: Insufficient capital`로 반복 스킵.
- 원인: `bot/intraday_monitor.py`의 US cash 계산이 `ord_psbl_frcr_amt`만 보고, 매도 재사용 가능 금액 `sll_ruse_psbl_amt`를 누락.
- 수정: US `_get_cached_cash()`에서 `sll_ruse_psbl_amt`를 더하도록 변경.
- 검증:
  - 수정 전 cash: 239.92
  - 수정 후 cash: 5151.91 확인
  - DELL 주문/체결 확인: BUY ENTRY 1주, filled 304.98

### 2. mid-session restart 시 당일 미완성 일봉이 Donchian에 포함됨
- 증상: 장중 재시작 후 yfinance가 2026-05-26 진행 중 일봉을 저장하면서 Donchian 상단이 오늘 고가로 올라감.
- 전략 위반: `TURTLE_TRADING_STRATEGY.md`는 오늘 제외한 최근 20/55일 고가 기준.
- 영향:
  - AMD upper20/upper55: 481.41 -> 496.89로 잘못 상승
  - DELL upper20/upper55: 298.32 -> 308.64로 잘못 상승
- 수정: `bot/pre_market.py`에서 현재 시장일의 장중 미완성 daily bar를 시그널 계산 전에 제외.
- 검증: production 로그에서 `pre_market_excluding_incomplete_bar`가 AMD/DELL 포함 전 종목에 기록됨.

### 3. sizing skip 로그 폭주
- 증상: AMD가 sizing상 1주 미만일 때 틱마다 `entry_skipped_sizing` 로그가 폭발.
- 수정: sizing skip 시 60초 entry cooldown을 적용하고, 로그에 계산 근거를 추가.
- 검증: production 로그가 60초 간격으로 줄었고 다음 근거가 기록됨:
  - cash=4220.65
  - account_equity=6780.30
  - effective_equity=3390.15
  - regime_scale=0.5
  - AMD n_value=22.8368
  - AMD price 약 489~490

## AMD / DELL 결론
- DELL: 버그 수정 후 실제로 재돌파 조건에서 진입했다. 1주 BUY ENTRY가 제출되고 304.98에 체결되어 open position으로 기록됨.
- AMD: cash 파싱 버그는 해결됐지만 현재 전략 계산상 1주가 안 나온다.
  - YELLOW regime 때문에 effective equity가 절반으로 줄어 약 3390달러.
  - AMD ATR(N)=22.8368, stop distance=2N=45.6736달러.
  - 1% risk budget은 약 33.90달러라 `33.90 / 45.67 < 1주`.
  - 따라서 AMD는 지금 가격이 S1/S2 돌파선 위여도 sizing 규칙상 스킵되는 것이 정상이다.

## 장중 감시 로그

### 01:24 KST / 12:24 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- AMD는 60초 간격으로 sizing skip 유지:
  - price 약 493~495
  - cash=4220.65
  - account_equity=6780.30
  - effective_equity=3390.15
  - n_value=22.8368
  - 결론: 1% risk budget이 1주 리스크보다 작아서 정상 스킵.
- open positions 변화 없음:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주.
- stop-loss, Donchian exit, 추가 entry/order failure 이벤트 없음.

### 01:39 KST / 12:39 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- AMD는 계속 돌파 상태지만 sizing skip 유지:
  - price 약 494.97 -> 497.10
  - cash=4220.65
  - account_equity=6780.30
  - effective_equity=3390.15
  - n_value=22.8368
  - regime_scale=0.5
- open positions 변화 없음:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주.
- stop-loss, Donchian exit, 추가 entry/order failure 이벤트 없음.

### 01:55 KST / 12:55 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- AMD sizing skip 유지:
  - price 약 493.65 -> 495.96
  - cash=4220.65
  - account_equity=6780.30
  - effective_equity=3390.15
  - n_value=22.8368
  - regime_scale=0.5
- open positions 변화 없음:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주.
- stop-loss, Donchian exit, 추가 entry/order failure 이벤트 없음.

### 02:26 KST / 13:26 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- 신규 진입 발생:
  - VICR S1 BUY ENTRY 1주 submitted at 317.00
  - filled at 316.84
  - open position id=52, stop=285.30, n_at_entry=22.4292
- AMD sizing skip 유지:
  - price 약 496.32 -> 497.39
  - cash=3902.07 after VICR fill
  - account_equity=6778.56
  - effective_equity=3389.28
  - n_value=22.8368
  - regime_scale=0.5
- open positions:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주, VICR 1주.
- stop-loss, Donchian exit, order failure 이벤트 없음.

### 02:57 KST / 13:57 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- 추가 신규 주문 없음.
- AMD sizing skip 유지:
  - price 약 496.3 -> 497.9
  - cash=3902.07
  - account_equity=6778.56
  - effective_equity=3389.28
  - n_value=22.8368
  - regime_scale=0.5
- open positions 변화 없음:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주, VICR 1주.
- stop-loss, Donchian exit, order failure 이벤트 없음.

### 03:27 KST / 14:27 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- 추가 신규 주문 없음.
- AMD sizing skip 유지:
  - price 약 495.7 -> 498.7
  - cash=3902.07
  - account_equity=6778.56
  - effective_equity=3389.28
  - n_value=22.8368
  - regime_scale=0.5
- open positions 변화 없음:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주, VICR 1주.
- stop-loss, Donchian exit, order failure 이벤트 없음.

### 04:34 KST / 15:34 ET
- `snowa-bot.service`: active.
- REST polling cycle 정상: errors=0, ok=28.
- heartbeat 정상: 28개 종목 가격 수신.
- VICR pyramiding 정상 발생:
  - order id `363`, broker order `0030479662`.
  - `PYRAMID` BUY 1주, requested 330.18, filled 328.35.
  - unit_number=2, `pyramid_interval=12.35`, `prev_stop=285.30`, `new_stop=296.27`.
  - DB position `VICR` total_shares=2, avg_entry_price=322.595, current_stop_price=296.27.
- cash는 VICR pyramid 체결 후 3902.07 -> 3571.91.
- AMD sizing skip 유지:
  - price 약 499 -> 506 구간까지 상승했으나 YELLOW regime scale 0.5 적용 후 1주 미만이라 정상 skip.
  - cash=3571.91, account_equity=6776.75, effective_equity=3388.37, n_value=22.8368.
- open positions:
  - BFH 1주, COCO 5주, DELL 1주, EZPW 54주, VICR 2주.
- stop-loss, Donchian exit, order failure 이벤트 없음.

### 05:10 KST / 16:10 ET
- 버그 발견: 정규장 마감 후에도 16:30 ET post-market cleanup 전까지 intraday monitor가 계속 틱을 처리해 매수 판단 가능.
- 실제 영향:
  - 16:05 ET에 VICR 3차 pyramid 주문 발생.
  - order id `364`, broker order `0030498194`.
  - `PYRAMID` BUY 1주, requested 344.63, filled 332.95.
  - unit_number=3, `pyramid_interval=15.25`, `prev_stop=296.27`, `new_stop=309.24`.
  - DB position `VICR` total_shares=3, avg_entry_price=326.0467, current_stop_price=309.24.
- 원인:
  - `TradingBot`은 post-market cleanup을 16:30 ET에 실행하므로 16:00~16:30 ET에도 websocket/fill loop가 살아 있음.
  - `IntradayMonitor.on_price_update()`에는 정규장 시간 게이트가 없어 after-hours 틱으로 피라미딩/진입 판단을 계속 수행함.
- 수정:
  - `bot/intraday_monitor.py`에 `_is_regular_market_open()` 추가.
  - `on_price_update()`에서 정규장 밖이면 heartbeat/가격 기록 후 `intraday_trading_skipped_market_closed` 로그만 남기고 매매 판단 전 return.
  - local `python3 -m py_compile bot/intraday_monitor.py` 통과.
  - production 업로드 후 `.venv/bin/python -m py_compile bot/intraday_monitor.py` 통과.
  - `sudo systemctl restart snowa-bot.service` 완료, service active.
- 재시작 후 현재 시각이 정규장 밖이라 catch-up intraday는 재시작되지 않았고, 16:30 ET post-market cleanup만 대기 중.

### 05:30 KST / 16:30 ET Post-Market
- `post_market_start` 정상 실행.
- intraday stop 정상:
  - `intraday_stopping`
  - `intraday_monitor_stopped`
  - `intraday_stopped`
- broker/DB 포지션 동기화 정상: `matched=5`, `broker_only=[]`, `db_only=[]`.
- 미체결 주문 없음: `post_market_no_unfilled_orders`.
- daily report 생성:
  - equity=6881.5
  - daily_pnl=-7.52
  - positions=5
  - market_filter=True
- IBD market direction 갱신:
  - QQQ=CONFIRMED_UPTREND
  - SPY=UPTREND_UNDER_PRESSURE
  - overall=UPTREND_UNDER_PRESSURE
- 최종 open positions:
  - BFH 1주
  - COCO 5주
  - DELL 1주
  - EZPW 54주
  - VICR 3주, avg_entry_price=326.0467, current_stop_price=309.24
- post-market 완료 후 `snowa-bot.service`: active.

## 계속 감시할 항목
- 다음 US 세션에서 정규장 밖 틱 수신 시 `intraday_trading_skipped_market_closed`가 기록되고 주문이 발생하지 않는지.
- AMD가 다음 세션에도 sizing skip인 경우 계산 근거가 변하는지.
- DELL/VICR stop/position 기록 정상 유지 여부.
- stop-loss / pyramiding / Donchian exit / order failure 이벤트 발생 여부.

## 검증 명령 결과 요약
- local `python3 -m py_compile bot/pre_market.py bot/intraday_monitor.py`: 통과.
- production `.venv/bin/python -m py_compile bot/pre_market.py bot/intraday_monitor.py`: 통과.
- LSP diagnostics: 기존 `structlog` import 해석 문제 및 기존 object attribute/type 경고만 존재.
