"""VCP (Volatility Contraction Pattern) detection — pure functions only.

Quantified approximation of Minervini's VCP:
  the base window is split into successive segments (oldest → newest) and the
  price depth (high-to-low range as % of segment high) must contract from one
  segment to the next, with the final segment tight enough to form a pivot.
  Volume drying up in the final segment supports the read but data-quality
  gaps must not create false negatives, so missing volume only skips that check.

No DB, clock, or broker access — takes plain lists, returns a dict.
Used by pre_market to stamp PrecomputedSignals.vcp_pass, which the intraday
entry gate consumes in shadow or enforce mode.
"""

from __future__ import annotations

from config.constants import (
    VCP_BASE_LEN,
    VCP_CONTRACTION_RATIO,
    VCP_MAX_FINAL_DEPTH,
    VCP_NUM_SEGMENTS,
)


def check_vcp(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    base_len: int = VCP_BASE_LEN,
    num_segments: int = VCP_NUM_SEGMENTS,
    max_final_depth: float = VCP_MAX_FINAL_DEPTH,
    contraction_ratio: float = VCP_CONTRACTION_RATIO,
) -> dict:
    """Evaluate whether the trailing *base_len* bars form a contracting base.

    Args:
        highs/lows/closes: Daily series, oldest first. Must be equal length.
        volumes: Optional volume series (same length). Missing/invalid volume
            skips the dry-up check rather than failing the pattern.
        base_len: Bars in the base window.
        num_segments: Successive segments the base is split into.
        max_final_depth: Final segment depth ceiling (e.g. 0.10 = 10%).
        contraction_ratio: Each segment's depth must be ≤ prior × this ratio.

    Returns:
        {
          "evaluable": bool,   # False → caller must fall back to current behavior
          "vcp": bool,
          "depths": list[float],
          "volume_dryup": bool | None,   # None when volume unusable
          "reason": str,
        }
    """
    result = {
        "evaluable": False,
        "vcp": False,
        "depths": [],
        "volume_dryup": None,
        "reason": "",
    }

    n = len(highs)
    if n != len(lows) or n != len(closes):
        result["reason"] = "series length mismatch"
        return result
    if n < base_len or num_segments < 2:
        result["reason"] = f"insufficient bars ({n} < {base_len})"
        return result

    win_h = highs[-base_len:]
    win_l = lows[-base_len:]
    seg_size = base_len // num_segments
    if seg_size < 2:
        result["reason"] = "segments too small"
        return result

    depths: list[float] = []
    for i in range(num_segments):
        # 마지막 세그먼트가 나머지 바를 모두 흡수해 최신 구간이 잘리지 않게 한다.
        start = i * seg_size
        end = (i + 1) * seg_size if i < num_segments - 1 else base_len
        seg_high = max(win_h[start:end])
        seg_low = min(win_l[start:end])
        if seg_high <= 0:
            result["reason"] = "non-positive segment high"
            return result
        depths.append((seg_high - seg_low) / seg_high)

    result["evaluable"] = True
    result["depths"] = [round(d, 4) for d in depths]

    for prev, cur in zip(depths, depths[1:]):
        if cur > prev * contraction_ratio:
            result["reason"] = (
                f"no contraction: depth {cur:.1%} > {prev:.1%} x {contraction_ratio}"
            )
            return result

    if depths[-1] > max_final_depth:
        result["reason"] = (
            f"final depth {depths[-1]:.1%} > max {max_final_depth:.0%}"
        )
        return result

    # 거래량 dry-up은 기록만 한다(판정에 미사용). 세그먼트 평균은 피벗 직전
    # dry-up의 거친 프록시라 차단 사유로 쓰면 정상 매집 돌파까지 걸러낸다.
    # 돌파 거래량 자체는 CANSLIM S필터가 별도로 본다.
    if volumes is not None and len(volumes) >= base_len:
        win_v = volumes[-base_len:]
        first_v = win_v[:seg_size]
        last_v = win_v[-(base_len - seg_size * (num_segments - 1)):]
        avg_first = sum(first_v) / len(first_v)
        avg_last = sum(last_v) / len(last_v)
        if avg_first > 0 and avg_last > 0:
            result["volume_dryup"] = avg_last < avg_first

    result["vcp"] = True
    result["reason"] = "contracting base"
    return result
