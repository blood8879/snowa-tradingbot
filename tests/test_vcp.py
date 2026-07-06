"""Unit tests for strategy.vcp.check_vcp — synthetic daily bars.

Run: python -m pytest tests/test_vcp.py -q
 or: python -m tests.test_vcp
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.vcp import check_vcp  # noqa: E402


def _segment(level: float, depth: float, bars: int, volume: float):
    """세그먼트 합성: 고가=level 고정, 저가=level*(1-depth) → 세그먼트 깊이=depth."""
    highs = [level] * bars
    lows = [level * (1 - depth)] * bars
    closes = [level * (1 - depth / 2)] * bars
    volumes = [volume] * bars
    return highs, lows, closes, volumes


def _base(depths: list[float], volumes: list[float], seg_bars: int = 17, level: float = 100.0):
    h: list[float] = []
    l: list[float] = []
    c: list[float] = []
    v: list[float] = []
    for d, vol in zip(depths, volumes):
        sh, sl, sc, sv = _segment(level, d, seg_bars, vol)
        h += sh
        l += sl
        c += sc
        v += sv
    return h, l, c, v


def test_contracting_base_passes():
    # 25% → 12% → 6% 수축 + 거래량 마름 → VCP
    h, l, c, v = _base([0.25, 0.12, 0.06], [1_000_000, 700_000, 400_000])
    res = check_vcp(h, l, c, v, base_len=51, num_segments=3)
    assert res["evaluable"] is True
    assert res["vcp"] is True, res["reason"]


def test_expanding_volatility_fails():
    # 10% → 15% → 25% 확장 → 미충족
    h, l, c, v = _base([0.10, 0.15, 0.25], [500_000, 500_000, 500_000])
    res = check_vcp(h, l, c, v, base_len=51, num_segments=3)
    assert res["evaluable"] is True
    assert res["vcp"] is False
    assert "no contraction" in res["reason"]


def test_final_depth_too_deep_fails():
    # 수축은 하지만 마지막이 18% > 10% 상한 → 미충족
    h, l, c, v = _base([0.40, 0.27, 0.18], [900_000, 600_000, 300_000])
    res = check_vcp(h, l, c, v, base_len=51, num_segments=3)
    assert res["evaluable"] is True
    assert res["vcp"] is False
    assert "final depth" in res["reason"]


def test_rising_volume_recorded_but_not_blocking():
    # 거래량 증가는 기록(dryup=False)만 하고 판정은 가격 수축으로만 한다
    h, l, c, v = _base([0.25, 0.12, 0.06], [300_000, 500_000, 900_000])
    res = check_vcp(h, l, c, v, base_len=51, num_segments=3)
    assert res["evaluable"] is True
    assert res["vcp"] is True
    assert res["volume_dryup"] is False


def test_missing_volume_skips_dryup_check():
    # 거래량 없으면 깊이 수축만으로 판정 (데이터 품질이 오탐을 만들면 안 됨)
    h, l, c, _ = _base([0.25, 0.12, 0.06], [0, 0, 0])
    res = check_vcp(h, l, c, None, base_len=51, num_segments=3)
    assert res["vcp"] is True
    assert res["volume_dryup"] is None


def test_insufficient_bars_not_evaluable():
    h, l, c, v = _base([0.25, 0.12], [500_000, 300_000], seg_bars=10)  # 20봉 < 51
    res = check_vcp(h, l, c, v, base_len=51, num_segments=3)
    assert res["evaluable"] is False
    assert res["vcp"] is False


def test_length_mismatch_not_evaluable():
    res = check_vcp([1.0] * 60, [0.9] * 59, [0.95] * 60, None, base_len=51)
    assert res["evaluable"] is False


def test_only_uses_trailing_window():
    # 앞쪽에 폭락 구간이 있어도 최근 base_len 창만 평가해야 함
    junk_h, junk_l, junk_c, junk_v = _segment(100.0, 0.60, 30, 2_000_000)
    h, l, c, v = _base([0.25, 0.12, 0.06], [1_000_000, 700_000, 400_000])
    res = check_vcp(junk_h + h, junk_l + l, junk_c + c, junk_v + v, base_len=51, num_segments=3)
    assert res["vcp"] is True, res["reason"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
