"""
매매일지 자동 기록을 위한 컨텍스트 빌더.

각 주문 유형별로 JSON 문자열을 생성하여 orders.notes 컬럼에 저장한다.
전략 엔진의 결정 근거(ATR, 돌파 수준, RS Rating 등)를 기록.

이 모듈은 순수 함수만 포함한다 (DB 접근 없음, async 없음, side-effect 없음).
"""

from __future__ import annotations

import json


def build_entry_context(
    *,
    system: str,
    breakout_level: float | None,
    atr: float,
    stop_price: float,
    market_filter: bool,
    rs_rating: float | None,
    composite_score: float | None,
    account_equity: float,
    shares: int,
    entry_price: float,
) -> str:
    """진입(ENTRY) 주문의 매매일지 JSON 컨텍스트 생성.

    새 포지션 진입 시점의 전략 판단 근거를 캡처한다:
    어떤 시스템이 트리거했는지, Donchian 돌파 가격, 현재 ATR,
    초기 스톱로스, 시장 필터 상태, CANSLIM 점수.

    Args:
        system: 트레이딩 시스템 ("S1" 또는 "S2").
        breakout_level: 진입을 트리거한 Donchian 채널 돌파 가격.
        atr: 해당 종목의 현재 ATR (N 값).
        stop_price: 초기 스톱로스 가격.
        market_filter: 진입 시점 SPY > 200MA 여부.
        rs_rating: 워치리스트의 IBD 스타일 RS Rating (또는 None).
        composite_score: 워치리스트의 CANSLIM 종합 점수 (또는 None).
        account_equity: 주문 시점의 계좌 총 자산.
        shares: 주문 수량.
        entry_price: 진입 트리거 가격.

    Returns:
        orders.notes 컬럼에 저장할 JSON 문자열.
    """
    risk_per_share = abs(entry_price - stop_price) if stop_price else 0.0
    position_value = entry_price * shares
    position_size_pct = (
        (position_value / account_equity * 100) if account_equity > 0 else 0.0
    )

    context = {
        "type": "ENTRY",
        "system": system,
        "breakout_level": round(breakout_level, 2) if breakout_level is not None else None,
        "atr": round(atr, 4),
        "stop_price": round(stop_price, 2),
        "risk_per_share": round(risk_per_share, 4),
        "market_filter": market_filter,
        "rs_rating": rs_rating,
        "composite_score": composite_score,
        "account_equity": round(account_equity, 2),
        "position_size_pct": round(position_size_pct, 2),
    }
    return json.dumps(context, ensure_ascii=False)


def build_pyramid_context(
    *,
    system: str,
    atr: float,
    new_stop: float,
    prev_stop: float,
    unit_number: int,
    account_equity: float,
    shares: int,
    entry_price: float,
    last_entry_price: float,
) -> str:
    """피라미딩(PYRAMID) 주문의 매매일지 JSON 컨텍스트 생성.

    피라미딩 판단 근거를 캡처한다: 몇 번째 유닛인지,
    이전 진입가로부터 0.5N 간격, 스톱로스 조정 내역.

    Args:
        system: 트레이딩 시스템 ("S1" 또는 "S2").
        atr: 현재 ATR (N 값).
        new_stop: 이번 피라미딩 후 갱신된 스톱 가격.
        prev_stop: 피라미딩 전 스톱 가격.
        unit_number: 추가되는 유닛 번호 (2, 3, 또는 4).
        account_equity: 주문 시점의 계좌 자산.
        shares: 이번 유닛 주문 수량.
        entry_price: 피라미딩 진입 가격.
        last_entry_price: 직전 유닛의 진입 가격.

    Returns:
        orders.notes 컬럼에 저장할 JSON 문자열.
    """
    position_size_pct = (
        (entry_price * shares / account_equity * 100) if account_equity > 0 else 0.0
    )

    context = {
        "type": "PYRAMID",
        "system": system,
        "unit_number": unit_number,
        "atr": round(atr, 4),
        "new_stop": round(new_stop, 2),
        "prev_stop": round(prev_stop, 2),
        "pyramid_interval": round(entry_price - last_entry_price, 2),
        "account_equity": round(account_equity, 2),
        "position_size_pct": round(position_size_pct, 2),
    }
    return json.dumps(context, ensure_ascii=False)


def build_stop_loss_context(
    *,
    stop_price: float,
    trigger_price: float,
    avg_entry_price: float,
    atr_at_entry: float,
    units_held: int,
    total_shares: int,
) -> str:
    """손절(STOP_LOSS) 주문의 매매일지 JSON 컨텍스트 생성.

    손절 이벤트를 캡처한다: 어떤 스톱 수준이 위반되었는지,
    실제 트리거 가격, 손실률.

    Args:
        stop_price: 위반된 스톱로스 가격.
        trigger_price: 스톱을 트리거한 실제 가격.
        avg_entry_price: 포지션 평균 진입 가격.
        atr_at_entry: 최초 진입 시점의 ATR (N).
        units_held: 손절 시점 보유 유닛 수.
        total_shares: 매도되는 총 주식 수.

    Returns:
        orders.notes 컬럼에 저장할 JSON 문자열.
    """
    loss_pct = (
        ((trigger_price - avg_entry_price) / avg_entry_price * 100)
        if avg_entry_price > 0
        else 0.0
    )

    context = {
        "type": "STOP_LOSS",
        "stop_price": round(stop_price, 2),
        "trigger_price": round(trigger_price, 2),
        "avg_entry_price": round(avg_entry_price, 2),
        "atr_at_entry": round(atr_at_entry, 4),
        "units_held": units_held,
        "total_shares": total_shares,
        "loss_pct": round(loss_pct, 2),
    }
    return json.dumps(context, ensure_ascii=False)


def build_exit_context(
    *,
    system: str,
    exit_level: float | None,
    exit_reason: str,
    avg_entry_price: float,
    atr: float,
    units_held: int,
    total_shares: int,
    current_price: float,
) -> str:
    """Donchian 청산(EXIT) 주문의 매매일지 JSON 컨텍스트 생성.

    Donchian 채널 청산 이벤트를 캡처한다: 어떤 시스템의 청산 채널이
    돌파되었는지, 해당 수준, 추정 손익률.

    Args:
        system: 트레이딩 시스템 ("S1" 또는 "S2").
        exit_level: 청산을 트리거한 Donchian 채널 수준.
        exit_reason: 사람이 읽을 수 있는 청산 사유 문자열.
        avg_entry_price: 포지션 평균 진입 가격.
        atr: 현재 ATR (N 값).
        units_held: 청산 시점 보유 유닛 수.
        total_shares: 매도되는 총 주식 수.
        current_price: 청산 시점 가격.

    Returns:
        orders.notes 컬럼에 저장할 JSON 문자열.
    """
    pnl_pct = (
        ((current_price - avg_entry_price) / avg_entry_price * 100)
        if avg_entry_price > 0
        else 0.0
    )

    context = {
        "type": "DONCHIAN_EXIT",
        "system": system,
        "exit_level": round(exit_level, 2) if exit_level is not None else None,
        "exit_reason": exit_reason,
        "avg_entry_price": round(avg_entry_price, 2),
        "atr": round(atr, 4),
        "units_held": units_held,
        "total_shares": total_shares,
        "pnl_pct": round(pnl_pct, 2),
    }
    return json.dumps(context, ensure_ascii=False)
