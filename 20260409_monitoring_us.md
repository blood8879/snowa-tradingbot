# 2026-04-09 US 장 감시 로그

## 장 시간
- 미국 서머타임: 22:30~05:00 KST (09:30~16:00 ET)

## 시장 상태
- **레짐**: YELLOW (SPY $676.01 > SMA200 $660.16, breadth 49.1%, ROC +1.6%)
- IBD Market Direction: CONFIRMED_UPTREND

## CANSLIM 스크리닝
- 20:00 KST 실행 완료 (약 55분)
- 유니버스: 6,580종목
- CANSLIM 통과: 33종목
- Minervini 통과: 23종목
- **최종 watchlist**: 23종목 (전일 13 → 오늘 23, 대폭 증가)
- 신규 추가: HBM(EPS+505%), AEM(+198%), NEM(+109%), CCJ, TSM, GOOGL, GOOG, NSSC, LAUR, JCI

## 매매 이벤트
### 신규 진입
- **SBS**: BUY 202주 @ $32.28 (S1 돌파, 주문가 $32.35)
  - 손절가: $30.30
  - 현금: $11,745 → ~$5,145 (주문 후)

## 포지션 현황 (22:34 KST 기준)
| 종목 | 주수 | 현재가 | 손절가 | 미실현P&L |
|------|------|--------|--------|----------|
| CVE | 549 | $26.10 | $22.07 | +10.97% |
| AMD | 18 | $232.60 | $200.42 | +4.80% |
| AGX | 6 | $594.00 | $531.00 | +2.60% |
| EZPW | 225 | $28.03 | $25.65 | +2.49% |
| HG | 241 | $31.09 | $28.93 | +1.72% |
| KEX | 147 | $140.48 | $132.16 | +0.80% |
| WWD | 11 | $394.97 | $367.48 | -0.06% |
| AZN | 41 | $202.52 | $194.81 | -0.91% |
| SBS | 202 | $31.84 | $30.30 | -1.37% |

- 총 9개 포지션
- 계좌 equity: $80,890
- 현금: ~$5,145

## 시스템 상태
- REST polling: 25종목, errors=0
- filled_query_failed: 0건
- WS: 연결됨
- fill check: 정상

## 장중 모니터링 요약 (22:30 ~ 00:31 KST)
- fill check: 211회+ 연속 성공
- REST polling: 25종목, errors=0
- filled_query_failed: 1건 (경미, 재시도 성공)
- 포지션 변동: SBS 신규 진입, VRT 신규 진입 → 총 10개
- 청산/손절: 0건
- Equity 추이: $80,890 → $81,509 (+0.8%)
- 신규 버그: 0건 (어제 수정한 rate limiting, equity 계산 정상)

## 대시보드 확인
- [x] /api/status — 정상
- [x] /api/positions — 정상 (10개 포지션)
- [x] /api/watchlist — 정상 (23종목)
- [x] /api/watchlist/history — 정상 (추가/탈락 기록)
- [x] /api/alerts/near-exit — 정상
- [x] /api/alerts/near-entry — 정상
- [x] /api/diary — 정상

## 감시 결론
- 오늘 신규 버그: **0건**
- 어제 수정한 Bug #34(rate limiting), #35(equity), #36(broker cancel) 모두 정상 작동 확인
- CANSLIM 스크리닝: 23종목 (최신 재무데이터 기반 갱신 확인)
- 매수 체결: SBS 202주, VRT 13주 — 모두 정상
- 포지션 관리: 10개 포지션 안정, 손절 트리거 없음
- fill check: 211회+ 성공, filled_query_failed 최소

## 감시 완료
