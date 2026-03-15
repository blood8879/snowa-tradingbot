# US 장 감시 내역 — 2026-03-09 (월)

## 요약
- **감시 시간**: 23:30 ~ 05:00 (KST) / 09:30 AM ~ 16:00 (ET)
- **시장 필터**: PASS (SPY close=$678.17, SMA200=$654.58)
- **워치리스트**: 14 종목
- **보유 포지션**: 3개 (CVE, ISSC, VRT)
- **계좌 자산**: $85,480.59 (현금 $23,641.36)
- **버그 수정**: Bug #19 (KRW/USD 혼합), Bug #20 (REST 가격 미수신), 쿨다운 개선
- **장중 매매**: VRT 진입 32주 @ $261.96 (Bug #19 수정 후)
- **총 틱 수신**: 53,978, REST cycle 246, 에러 0

## 사전 점검 (21:25 KST)
- [x] 봇 정상 가동 (6시간 연속)
- [x] US 스크리닝 완료 (6,669종목 → 14종목)
- [x] 포지션 2개 OPEN, 유닛 기록 정상
- [x] 미체결 주문 없음
- [x] 시장 필터 PASS
- [x] Bug #18 수정 배포 완료 (market 필드, 유닛 기록)

## 포지션 상세

### CVE (Cenovus Energy)
- 시스템: S1
- 주수: 549주 (1유닛: U1=549주@23.52)
- 평균단가: $23.52
- 손절가: $22.07
- 진입일: 2026-03-06

### ISSC (Innovative Solutions and Support)
- 시스템: S1
- 주수: 1,414주 (2유닛: U1=852주@24.99, U2=562주@27.53)
- 평균단가: $26.00
- 손절가: $24.75
- 진입일: 2026-03-05 (U1), 2026-03-05 (U2 피라미딩)

## 워치리스트 (14종목)
| 종목 | RS등급 |
|------|--------|
| AEM | 91 |
| CVE | 89 |
| VRT | 95 |
| HXL | 84 |
| AROC | 87 |
| TSM | 89 |
| UGP | 85 |
| WWD | 90 |
| EZPW | 91 |
| WT | 90 |
| JCI | 82 |
| GE | 80 |
| NVS | 81 |
| OUT | 89 |

## Pre-Market 실행 (22:00 KST)
- [x] 가격 업데이트: 16종목 완료 (new_records=0, 주말이라 변동 없음)
- [x] 시그널 사전계산: 15/15 성공
- [x] 시장 필터: PASS (SPY 672.63 > SMA200 654.00)
- [x] 갭다운 체크: 0건
- [x] 소요시간: 2.99초

## 장 오픈 (23:30 KST)
- [x] WS 연결 성공 (reconnect_count=0)
- [x] 15종목 구독 완료 (14 워치리스트 + ISSC 포지션)
- [x] 첫 틱 수신: TSM $334.845
- [x] REST polling 시작 (15종목, 에러 0)
- [x] fill_check_loop 시작 (pending_orders=0)

## Bug #19 발견 및 수정 (00:15 KST)
- **증상**: VRT 진입 시그널 발생 → `required=$1,079,141` (현금 $32K 초과)
- **원인**: `_execute_entry`/`_execute_pyramid`에서 `get_open_positions()`가 **전 시장 포지션** 반환
  - KR 포지션 비용(₩10,062,607)이 USD 현금과 합산 → equity $10,094,715 (실제 $81,780)
- **수정**: `sum(p.total_cost for p in open_positions if p.market == self._market)` 필터 추가
- **배포**: 00:20 배포 + 봇 재시작, catchup 정상 실행
- **검증**: VRT 시그널 미발생 (가격 하락), 봇 정상 동작 확인

## 쿨다운 수정 배포 (02:28 KST)
- **증상**: ISSC pyramid_blocked_risk 7회+ 반복 (42초간)
- **원인**: 리스크 매니저 차단 후 쿨다운 미설정
- **수정**: `_pyramid_cooldown[ticker]`, `_entry_cooldown[ticker]` 설정 추가
- **배포**: 02:28 배포 + 봇 재시작

## Bug #20 발견 및 수정 (02:32~02:40 KST)
- **증상**: 봇 재시작 후 WS 1틱만 수신 후 침묵, REST `ok=0` (가격 데이터 완전 불통)
- **원인 1**: `get_current_price()`가 `/quotations/price-detail` 사용 → paper 모드에서 빈 응답
- **원인 2**: REST API 거래소 코드 형식 불일치 (NYSE→NYS, NASD→NAS, AMEX→AMS 필요)
- **수정**:
  - 엔드포인트 변경: `price-detail` → `price` (기본)
  - `EXCHANGE_SHORT_MAP` 추가 (NASD→NAS, NYSE→NYS, AMEX→AMS)
- **배포**: 02:40 배포 + 봇 재시작
- **검증**: REST polling `ok=15/15` (이전 `ok=0`), heartbeat tick_count=2,015, 15종목 전부 가격 수신

## 장중 이벤트
- **00:39 KST** — VRT S1 돌파 진입: BUY 32주 @ $261.96 체결 (Bug #19 수정 효과 확인!)
  - 수정 전: equity $10M(KRW 혼합) → 4,300주 → 현금 부족 차단
  - 수정 후: equity $81K(USD only) → 32주 → 정상 체결
- **02:47 KST** — 3 포지션 정상 감시 중: CVE $22.99(손절 $22.07), ISSC, VRT
- **03:12~03:19 KST** — ISSC pyramid_blocked_risk 매 분 반복 (10분 쿨다운 수정 전)
- **03:20 KST** — 10분 쿨다운 배포 후 ISSC 스팸 해소 (03:20→03:30→03:40 간격)
- **04:45~05:00 KST** — Donchian exit 윈도우 진입, 3 포지션 모두 Donchian 하한 위 → exit 없음
- **05:00 KST** — 장 마감: CVE $22.82, VRT $264.76(+1.07%), ISSC $28.82

## 장 마감 포지션 상세 (05:00 KST)
| 종목 | 주수 | 유닛 | 평균단가 | 종가 | 손절가 | 수익률 |
|------|------|------|----------|------|--------|--------|
| CVE | 549 | 1 | $23.52 | $22.82 | $22.07 | -2.97% |
| ISSC | 1,414 | 2 | $26.00 | $28.82 | $24.75 | +10.85% |
| VRT | 32 | 1 | $261.96 | $264.76 | $237.21 | +1.07% |

- **계좌 자산**: $85,480.59 (현금 $23,641, 포지션 $61,839)
- **시장 필터**: PASS (SPY $678.17 > SMA200 $654.58)

## 코드 점검 (21:40 KST)
- [x] Bug #1~5 (손절/청산 트리거) 서버 배포 확인
  - precomputed_signals 정상, 쿨다운→donchian fall-through, SUBMITTED 만료(SELL 30분/BUY 2시간)
- [x] Bug #18 (market 필드, 유닛 기록) 서버 배포 확인
- [x] on_price_update 시그널 우선순위 흐름 정상 (손절→피라미딩→진입→Donchian청산)
- [x] 미체결 주문 0건

## 대시보드 US 탭 확인 (21:50 KST)
- [x] 포지션 — CVE 549주 1유닛(-3.36%), ISSC 1414주 2유닛(-0.99%)
- [x] 매매내역 — CVE 진입, AEM 손절 등 기록 표시
- [x] 종목일기(Diary) — 정상
- [x] 워치리스트 — 14종목, RS등급/유닛사이즈 포함
- [x] 진입 알림 — CVE close(3.0%), OUT close(3.1%) 등
- [x] 청산 알림 — CVE safe(6.1%), ISSC safe(10.6%)
- [x] 시장 필터 — PASS (SPY 672.38 > SMA200 654.13)
- [x] 시장 상태 — paper 모드, WS DISCONNECTED(장전 정상), 계좌 $80,983
- [x] PnL — 일별 수익 데이터 정상
- [x] 매매일지(Journal) — 월간 통계(4건, 승률 0%) + 거래 상세 정상
