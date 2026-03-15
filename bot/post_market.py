"""
장후 정리 모듈 — 매일 KST 06:30 (US 장 종료 후) 실행.

1. 브로커 잔고 ↔ DB 포지션 동기화
2. 미체결 주문 처리
3. 일일 리포트 생성 (DailyLog)
4. DB 기록
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from broker.account import AccountManager
from broker.kis_rest import KISRestClient
from broker.order_executor import OrderExecutor
from config.constants import MARKET_BENCHMARK, MARKET_MA_PERIOD
from config.market_config import get_market_config
from core.database import Database
from core.models import DailyLog, OrderStatus
from data.price_cache import PriceCache
from portfolio.position_manager import PositionManager

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Post-Market Processor
# ════════════════════════════════════════════════════════════════


class PostMarketProcessor:
    """매일 장 종료 후 실행되는 정리 루틴.

    의존성을 주입받아 다음 작업을 순차적으로 수행한다:
    1. 브로커 잔고와 DB 포지션 동기화
    2. 미체결 주문 확인 및 취소
    3. 일일 리포트(DailyLog) 생성 → daily_log 테이블에 INSERT
    4. 정리 작업 (bot_state 업데이트)
    """

    def __init__(
        self,
        db: Database,
        rest_client: KISRestClient,
        account_mgr: AccountManager,
        position_mgr: PositionManager,
        order_executor: OrderExecutor,
    ) -> None:
        self._db = db
        self._rest = rest_client
        self._account_mgr = account_mgr
        self._position_mgr = position_mgr
        self._order_executor = order_executor
        self._price_cache = PriceCache(db)

    # ── Public API ───────────────────────────────────────────

    async def run(self, market: str = "US") -> dict:
        """전체 장후 정리 루틴을 실행하고 요약 결과를 반환한다.

        Args:
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            요약 dict::

                {
                    "sync_result": dict,
                    "cancelled_orders": int,
                    "daily_log": DailyLog,
                }
        """
        started_at = datetime.now(timezone.utc)
        logger.info("post_market_started", market=market)

        # Step 1: 브로커 ↔ DB 동기화
        sync_result = await self._sync_positions(market=market)

        # Step 2: 미체결 주문 처리
        cancelled_count = await self._process_unfilled_orders(market=market)

        # Step 3: 일일 리포트 생성 및 DB 저장
        daily_log = await self._generate_daily_report(market=market)

        # Step 3.5: IBD Market Direction update (logging-only)
        await self._update_ibd_direction(market=market)

        # Step 4: 정리 작업
        await self._cleanup(market=market)

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        summary = {
            "sync_result": sync_result,
            "cancelled_orders": cancelled_count,
            "daily_log": daily_log,
        }

        logger.info(
            "post_market_completed",
            market=market,
            elapsed_s=round(elapsed, 2),
            sync_matched=sync_result.get("matched", 0),
            cancelled=cancelled_count,
            equity=daily_log.account_equity,
            daily_pnl=daily_log.daily_pnl,
        )

        return summary

    # ── Step 1: Position Sync ────────────────────────────────

    async def _sync_positions(self, market: str = "US") -> dict:
        """브로커 실제 잔고와 로컬 DB 포지션을 비교/동기화한다.

        Args:
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            ``AccountManager.sync_positions()`` 결과 dict.
        """
        try:
            result = await self._account_mgr.sync_positions()
            logger.info(
                "post_market_sync_done",
                market=market,
                matched=result.get("matched", 0),
                broker_only=result.get("broker_only", []),
                db_only=result.get("db_only", []),
            )
            return result
        except Exception:
            logger.exception("post_market_sync_failed", market=market)
            return {"matched": 0, "broker_only": [], "db_only": []}

    # ── Step 2: Unfilled Orders ──────────────────────────────

    async def _process_unfilled_orders(self, market: str = "US") -> int:
        """미체결 주문을 확인하고, 장 마감 후 잔존하는 주문을 취소한다.

        Args:
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            취소된 주문 수.
        """
        cancelled_count = 0

        try:
            unfilled = await self._rest.get_unfilled_orders(market=market)

            if not unfilled:
                logger.info("post_market_no_unfilled_orders", market=market)
                return 0

            for order_data in unfilled:
                order_no = order_data.get("odno", "")
                ticker = order_data.get("pdno", "")

                # Market-specific field handling
                if market == "KR":
                    # KR may not have ovrs_excg_cd, use default
                    exchange = order_data.get("ovrs_excg_cd", "")
                    qty = int(float(order_data.get("psbl_qty", order_data.get("nccs_qty", 0))))
                else:
                    exchange = order_data.get("ovrs_excg_cd", "NASD")
                    qty = int(float(order_data.get("nccs_qty", 0)))

                if qty <= 0 or not order_no:
                    continue

                try:
                    await self._rest.cancel_order(
                        order_no=order_no,
                        ticker=ticker,
                        exchange=exchange,
                        quantity=qty,
                        market=market,
                    )
                    cancelled_count += 1
                    logger.info(
                        "post_market_order_cancelled",
                        market=market,
                        order_no=order_no,
                        ticker=ticker,
                        quantity=qty,
                    )
                except Exception:
                    logger.exception(
                        "post_market_cancel_failed",
                        market=market,
                        order_no=order_no,
                        ticker=ticker,
                    )

            # DB의 SUBMITTED/PENDING 주문도 CANCELLED로 업데이트 (market 필터 추가)
            await self._db.conn.execute(
                """
                UPDATE orders
                SET status = ?, updated_at = ?
                WHERE status IN (?, ?) AND market = ?
                """,
                (
                    OrderStatus.CANCELLED.value,
                    datetime.now(timezone.utc).isoformat(),
                    OrderStatus.SUBMITTED.value,
                    OrderStatus.PENDING.value,
                    market,
                ),
            )
            await self._db.conn.commit()

        except Exception:
            logger.exception("post_market_unfilled_processing_error", market=market)

        logger.info(
            "post_market_unfilled_processed",
            market=market,
            cancelled=cancelled_count,
        )
        return cancelled_count

    # ── Step 3: Daily Report ─────────────────────────────────

    async def _generate_daily_report(self, market: str = "US") -> DailyLog:
        """일일 거래 리포트를 생성하고 daily_log 테이블에 저장한다.

        Args:
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            생성된 ``DailyLog`` 인스턴스.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 계좌 정보 조회
        try:
            account_info = await self._account_mgr.get_account_info(market=market)
            equity = account_info.total_equity
            cash = account_info.cash_balance
        except Exception:
            logger.exception("post_market_account_info_error", market=market)
            equity = 0.0
            cash = 0.0

        # Market-specific benchmark ticker
        market_cfg = get_market_config(market)
        benchmark_ticker = market_cfg.benchmark_ticker

        # Benchmark 종가 & SMA200
        benchmark_close = await self._price_cache.get_latest_close(benchmark_ticker)

        from data.market_data import MarketDataProvider
        market_data = MarketDataProvider(self._price_cache)
        benchmark_sma200 = await market_data.get_sma(
            benchmark_ticker, MARKET_MA_PERIOD,
        )

        market_filter_pass = False
        if benchmark_close is not None and benchmark_sma200 is not None:
            market_filter_pass = benchmark_close > benchmark_sma200

        # Regime calculation (breadth + ROC)
        from strategy.market_filter import calculate_breadth, calculate_roc, determine_regime
        breadth_pct = await calculate_breadth(self._db, market=market)
        benchmark_closes = await market_data.get_closes(benchmark_ticker, 140)
        from config.constants import MARKET_ROC_PERIOD
        roc = calculate_roc(benchmark_closes, MARKET_ROC_PERIOD) if benchmark_closes else None
        regime, _ = determine_regime(market_filter_pass, breadth_pct, roc)

        # 포지션 통계
        open_positions = await self._position_mgr.get_open_positions()
        total_positions = len(open_positions)
        total_units = await self._position_mgr.get_total_units_count()

        # 일일 P&L 계산 (전일 대비)
        daily_pnl, daily_pnl_pct, cumulative_pnl = await self._calculate_pnl(
            equity, today, market=market,
        )

        # 최대 낙폭 계산
        max_drawdown_pct = await self._calculate_max_drawdown(equity, market=market)

        # 당일 주문 활동 통계
        entries_count, exits_count, stop_losses_count = await self._count_daily_activity(
            today, market=market,
        )

        daily_log = DailyLog(
            date=today,
            spy_close=benchmark_close,
            spy_sma200=benchmark_sma200,
            market_filter_pass=market_filter_pass,
            regime=regime,
            breadth_pct=breadth_pct,
            roc=roc,
            account_equity=equity,
            cash_balance=cash,
            total_positions=total_positions,
            total_units=total_units,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            cumulative_pnl=cumulative_pnl,
            max_drawdown_pct=max_drawdown_pct,
            entries_count=entries_count,
            exits_count=exits_count,
            stop_losses_count=stop_losses_count,
        )

        # DB에 저장
        await self._save_daily_log(daily_log, market=market)

        logger.info(
            "post_market_daily_report",
            market=market,
            date=today,
            equity=equity,
            daily_pnl=daily_pnl,
            positions=total_positions,
            market_filter=market_filter_pass,
        )

        return daily_log

    async def _calculate_pnl(
        self, current_equity: float, today: str, market: str = "US",
    ) -> tuple[float, float, float]:
        """전일 대비 일일 P&L과 누적 P&L을 계산한다.

        Args:
            current_equity: 오늘의 총 평가액.
            today: 오늘 날짜 문자열 (YYYY-MM-DD).
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            (daily_pnl, daily_pnl_pct, cumulative_pnl) 튜플.
        """
        # 전일 equity 조회 (market 필터 추가)
        cursor = await self._db.conn.execute(
            """
            SELECT account_equity FROM daily_log
            WHERE date < ? AND market = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (today, market),
        )
        row = await cursor.fetchone()
        prev_equity = row[0] if row and row[0] else 0.0

        daily_pnl = current_equity - prev_equity if prev_equity > 0 else 0.0
        daily_pnl_pct = (
            (daily_pnl / prev_equity * 100) if prev_equity > 0 else 0.0
        )

        # 누적 P&L: 봇 최초 실행 시 기록된 계좌 잔고 대비
        starting = await self._db.get_state("starting_equity")
        starting_equity = float(starting) if starting else current_equity
        cumulative_pnl = current_equity - starting_equity

        return daily_pnl, round(daily_pnl_pct, 4), cumulative_pnl

    async def _calculate_max_drawdown(self, current_equity: float, market: str = "US") -> float:
        """역대 최고 평가액 대비 현재 낙폭(%)을 계산한다.

        Args:
            current_equity: 오늘의 총 평가액.
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            최대 낙폭 비율 (퍼센트, 음수).
        """
        cursor = await self._db.conn.execute(
            "SELECT MAX(account_equity) FROM daily_log WHERE market = ?",
            (market,),
        )
        row = await cursor.fetchone()
        peak = row[0] if row and row[0] else current_equity

        # 오늘 equity가 새 고점일 수도 있음
        peak = max(peak, current_equity)

        if peak <= 0:
            return 0.0

        drawdown_pct = ((current_equity - peak) / peak) * 100
        return round(drawdown_pct, 4)

    async def _count_daily_activity(
        self, today: str, market: str = "US",
    ) -> tuple[int, int, int]:
        """당일 체결된 주문의 유형별 건수를 집계한다.

        Args:
            today: 오늘 날짜 문자열 (YYYY-MM-DD).
            market: 시장 코드 ("US" 또는 "KR").

        Returns:
            (entries_count, exits_count, stop_losses_count) 튜플.
        """
        # 주문 생성일이 오늘인 체결 건 조회 (market 필터 추가)
        cursor = await self._db.conn.execute(
            """
            SELECT order_type, COUNT(*) FROM orders
            WHERE created_at LIKE ? AND status = 'FILLED' AND market = ?
            GROUP BY order_type
            """,
            (f"{today}%", market),
        )
        rows = await cursor.fetchall()

        entries = 0
        exits = 0
        stop_losses = 0

        for order_type, count in rows:
            if order_type in ("ENTRY", "PYRAMID"):
                entries += count
            elif order_type == "EXIT":
                exits += count
            elif order_type == "STOP_LOSS":
                stop_losses += count

        return entries, exits, stop_losses

    async def _save_daily_log(self, log: DailyLog, market: str = "US") -> None:
        """DailyLog를 daily_log 테이블에 INSERT OR REPLACE 한다.

        Args:
            log: 저장할 DailyLog 인스턴스.
            market: 시장 코드 ("US" 또는 "KR").
        """
        await self._db.conn.execute(
            """
            INSERT OR REPLACE INTO daily_log (
                date, market, spy_close, spy_sma200, market_filter_pass,
                regime, breadth_pct, roc,
                account_equity, cash_balance,
                total_positions, total_units,
                daily_pnl, daily_pnl_pct,
                cumulative_pnl, max_drawdown_pct,
                entries_count, exits_count, stop_losses_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.date,
                market,
                log.spy_close,
                log.spy_sma200,
                1 if log.market_filter_pass else 0,
                log.regime,
                log.breadth_pct,
                log.roc,
                log.account_equity,
                log.cash_balance,
                log.total_positions,
                log.total_units,
                log.daily_pnl,
                log.daily_pnl_pct,
                log.cumulative_pnl,
                log.max_drawdown_pct,
                log.entries_count,
                log.exits_count,
                log.stop_losses_count,
            ),
        )
        await self._db.conn.commit()

        logger.debug("post_market_daily_log_saved", date=log.date, market=market)

    # ── Step 4: Cleanup ──────────────────────────────────────

    async def _update_ibd_direction(self, market: str = "US") -> dict | None:
        try:
            from strategy.ibd_market_direction import IBDMarketDirection
            ibd = IBDMarketDirection(self._db, self._price_cache, market=market)
            result = await ibd.update()
            if result:
                statuses = {ticker: state.status for ticker, state in result.items()}
                overall = result.get("overall")
                logger.info(
                    "ibd_market_direction_updated",
                    overall=overall.status if overall else None,
                    **{k: v for k, v in statuses.items() if k != "overall"},
                )
            return result
        except Exception:
            logger.exception("ibd_market_direction_error")
            return None

    async def _cleanup(self, market: str = "US") -> None:
        """장 마감 후 정리 작업을 수행한다.

        Args:
            market: 시장 코드 ("US" 또는 "KR").

        - bot_state에 마지막 장후 처리 시각을 기록
        - 향후 확장: 오래된 로그 정리, 캐시 최적화 등
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Market-specific state key
        state_key = f"last_post_market_run_{market.lower()}"
        await self._db.set_state(state_key, now_iso)

        logger.info("post_market_cleanup_done", market=market, timestamp=now_iso)
