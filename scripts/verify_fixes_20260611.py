"""2026-06-11 명세 정합성 수정 검증 스크립트 (1회용 스모크 테스트).

검증 항목:
  #3 시장 필터: SMA fail → RED, fail-closed
  #2 상관 그룹: set_stock_info 등록 후 6/10유닛 한도 발동
  #1 S1 필터: 돌파 기록 → 가상 청산 판정 → was_last_breakout_winner
  #9/#10 add_unit: UP_ONLY 가드 + 전 유닛 손절 동기화
  position_sizer 입력 가드 / ADV 캡
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite

from strategy.market_filter import determine_regime
from portfolio.correlation_groups import CorrelationGroupManager
from portfolio.position_sizer import calculate_unit_shares

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name} {detail}")


def test_market_filter() -> None:
    print("[#3] 시장 필터")
    # SMA fail → 무조건 RED (breadth/ROC 양호해도)
    regime, scale = determine_regime(sma_pass=False, breadth_pct=0.9, roc=0.2)
    check("SMA fail → RED", regime == "RED" and scale == 0.0, f"({regime}, {scale})")
    # SMA pass + 둘 다 나쁨 → RED (보수적 추가 레이어 유지)
    regime, _ = determine_regime(sma_pass=True, breadth_pct=0.10, roc=-0.20)
    check("SMA pass + breadth/ROC bad → RED", regime == "RED", f"({regime})")
    # SMA pass + 양호 → GREEN
    regime, scale = determine_regime(sma_pass=True, breadth_pct=0.9, roc=0.1)
    check("SMA pass + healthy → GREEN", regime == "GREEN" and scale == 1.0)
    # SMA pass + 하나 약함 → YELLOW
    regime, scale = determine_regime(sma_pass=True, breadth_pct=0.30, roc=0.1)
    check("SMA pass + one weak → YELLOW 0.5", regime == "YELLOW" and scale == 0.5)
    # 데이터 없음 (None) → SMA만으로 판단
    regime, _ = determine_regime(sma_pass=True, breadth_pct=None, roc=None)
    check("SMA pass + no breadth/roc → GREEN", regime == "GREEN")


def test_correlation() -> None:
    print("[#2] 상관 그룹 한도")
    cg = CorrelationGroupManager()
    for t in ("NVDA", "AMD", "AVGO"):
        cg.set_stock_info(t, "Technology", "Semiconductors")
    cg.set_stock_info("MSFT", "Technology", "Software")
    # NVDA 4 + AMD 2 = 업종 6유닛 → AVGO 진입 차단되어야 함
    result = cg.check_correlation_limits("AVGO", {"NVDA": 4, "AMD": 2})
    check("업종 6유닛 한도 발동", not result["allowed"] and result["correlated_used"] == 6,
          f"(correlated_used={result['correlated_used']})")
    # 섹터 10유닛: NVDA 4 + AMD 2 + MSFT 4 = 10 → 같은 섹터 추가 차단
    result = cg.check_correlation_limits("AVGO", {"NVDA": 4, "AMD": 2, "MSFT": 4})
    check("섹터 10유닛 한도 발동", not result["allowed"] and result["sector_used"] == 10,
          f"(sector_used={result['sector_used']})")
    # 미등록 시 0으로 계산되던 기존 버그 — placeholder는 그룹화되지 않아야 함
    cg2 = CorrelationGroupManager()
    cg2.set_stock_info("AAA", "_unknown_sector_AAA", "_unknown_industry_AAA")
    cg2.set_stock_info("BBB", "_unknown_sector_BBB", "_unknown_industry_BBB")
    r = cg2.check_correlation_limits("AAA", {"BBB": 6})
    check("미분류 placeholder 비그룹화", r["correlated_used"] == 0, f"(={r['correlated_used']})")


def test_sizer() -> None:
    print("[사이징] 가드 + ADV 캡")
    r = calculate_unit_shares(account_equity=100_000, entry_price=100, n_value=0)
    check("n_value=0 → skip", r["skip"])
    r = calculate_unit_shares(account_equity=0, entry_price=100, n_value=2)
    check("equity=0 → skip", r["skip"])
    # 명세 예시 1: $100k, $175, N=$3.5 → 2N=$7 → 142주
    r = calculate_unit_shares(account_equity=100_000, entry_price=175, n_value=3.5)
    check("명세 예시(AAPL) 142주", r["shares"] == 142, f"(={r['shares']})")
    # ADV 캡: ADV 1000주 → 5% = 50주
    r = calculate_unit_shares(account_equity=100_000, entry_price=175, n_value=3.5,
                              avg_daily_volume=1000)
    check("ADV 5% 캡 적용 (50주)", r["shares"] == 50, f"(={r['shares']})")


SCHEMA = """
CREATE TABLE breakout_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    system TEXT NOT NULL,
    breakout_date TEXT NOT NULL,
    breakout_price REAL NOT NULL,
    would_have_been_winner INTEGER,
    hypothetical_exit_price REAL,
    hypothetical_exit_date TEXT,
    was_actually_entered INTEGER DEFAULT 0
);
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT, status TEXT, current_stop_price REAL,
    total_shares INTEGER, total_cost REAL, avg_entry_price REAL
);
CREATE TABLE units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER, unit_number INTEGER,
    entry_price REAL, shares INTEGER,
    entry_stop_price REAL, current_stop_price REAL,
    entered_at TEXT
);
"""


class FakeDB:
    def __init__(self, conn):
        self.conn = conn


class Bar:
    def __init__(self, date, high, low, close):
        self.date = date
        self.high = high
        self.low = low
        self.close = close


async def test_breakout_tracker() -> None:
    print("[#1] S1 돌파 추적")
    from strategy.breakout_tracker import BreakoutTracker

    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(SCHEMA)
    db = FakeDB(conn)
    tracker = BreakoutTracker(db)

    # 이력 없음 → None (진입 허용)
    w = await tracker.was_last_breakout_winner("TEST")
    check("이력 없음 → None", w is None)

    # 돌파 기록 → open breakout 존재, winner는 아직 None
    await tracker.record_breakout("TEST", "S1", 100.0, False, breakout_date="2026-06-01")
    bo = await tracker.get_open_breakout("TEST")
    check("open breakout 조회", bo is not None and bo["breakout_price"] == 100.0)
    w = await tracker.was_last_breakout_winner("TEST")
    check("미해결 → None (진입 허용)", w is None)

    # 가상 청산: 10일 저가 110 > 돌파가 100 → winner
    winner = await tracker.evaluate_hypothetical("TEST", 100.0, 115.0, 110.0)
    await tracker.update_breakout_outcome(bo["id"], bool(winner), 110.0, "2026-06-10")
    w = await tracker.was_last_breakout_winner("TEST")
    check("수익 돌파 → True (다음 S1 스킵)", w is True)
    bo2 = await tracker.get_open_breakout("TEST")
    check("해결 후 open 없음", bo2 is None)

    # pre_market 일봉 로직 시뮬레이션 (PreMarketPreparer._update_breakout_history)
    from bot.pre_market import PreMarketPreparer
    prep = PreMarketPreparer.__new__(PreMarketPreparer)
    prep._db = db
    prep._breakout_tracker = tracker

    # 돌파 일봉 시나리오: 21일 평탄(고가 100) 후 마지막 날 종가 105
    bars = [Bar(f"2026-05-{i:02d}", 100, 95, 98) for i in range(1, 22)]
    bars.append(Bar("2026-06-11", 106, 101, 105))
    await prep._update_breakout_history("TEST2", bars)
    bo = await tracker.get_open_breakout("TEST2")
    check("일봉 돌파 탐지 (breakout=100)", bo is not None and bo["breakout_price"] == 100.0,
          f"({bo and bo['breakout_price']})")

    # 가상 청산 시나리오: 이후 하락하여 10일 저가 이탈 (손실 돌파)
    bars2 = list(bars)
    for i, (h, l, c) in enumerate([(105, 101, 103), (104, 100, 101), (101, 97, 98),
                                    (99, 92, 94)], start=12):
        bars2.append(Bar(f"2026-06-{i:02d}", h, l, c))
    # 마지막 날 종가 94 < 직전 10일 저가 95 → 가상 청산, 95 < 돌파가 100 → 손실
    await prep._update_breakout_history("TEST2", bars2)
    w = await tracker.was_last_breakout_winner("TEST2")
    check("가상 청산 → 손실 판정 (False)", w is False, f"(={w})")

    await conn.close()


async def test_add_unit() -> None:
    print("[#9/#10] add_unit UP_ONLY + 유닛 손절 동기화")
    from portfolio.position_manager import PositionManager

    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(SCHEMA)
    db = FakeDB(conn)
    pm = PositionManager.__new__(PositionManager)
    pm._db = db

    await conn.execute(
        "INSERT INTO positions (ticker, status, current_stop_price, total_shares, total_cost, avg_entry_price)"
        " VALUES ('TEST', 'OPEN', 95.0, 10, 1000.0, 100.0)"
    )
    await conn.execute(
        "INSERT INTO units (position_id, unit_number, entry_price, shares, entry_stop_price, current_stop_price, entered_at)"
        " VALUES (1, 1, 100.0, 10, 95.0, 95.0, '2026-06-01')"
    )
    await conn.commit()

    # 정상 케이스: 더 높은 손절 → 전 유닛 동기화
    await pm.add_unit(position_id=1, entry_price=103.0, shares=10, stop_price=98.0)
    cur = await conn.execute("SELECT current_stop_price FROM units WHERE position_id=1")
    stops = [r[0] for r in await cur.fetchall()]
    check("전 유닛 손절 = 98.0", stops == [98.0, 98.0], f"(={stops})")

    # UP_ONLY: 낮은 손절(90)을 넘기면 기존 98 유지
    await pm.add_unit(position_id=1, entry_price=105.0, shares=10, stop_price=90.0)
    cur = await conn.execute("SELECT current_stop_price FROM positions WHERE id=1")
    pos_stop = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT current_stop_price FROM units WHERE position_id=1")
    stops = [r[0] for r in await cur.fetchall()]
    check("UP_ONLY 가드 (98 유지)", pos_stop == 98.0 and stops == [98.0] * 3,
          f"(pos={pos_stop}, units={stops})")

    await conn.close()


async def main() -> None:
    test_market_filter()
    test_correlation()
    test_sizer()
    await test_breakout_tracker()
    await test_add_unit()
    print(f"\n결과: PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("실패:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
