"""
메인 오케스트레이터 — APScheduler로 전체 트레이딩 사이클 관리.

- KST 22:00: 장전 준비
- KST 23:30~06:00: 장중 모니터링
- KST 06:30: 장후 정리
- 킬스위치: KILL_SWITCH 파일 존재 시 정지
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.daily_screening import DailyScreeningPipeline
from bot.intraday_monitor import IntradayMonitor
from bot.mode import ModeManager
from bot.pre_market import PreMarketPreparer
from bot.post_market import PostMarketProcessor
from broker.account import AccountManager
from broker.kis_auth import KISAuth
from broker.kis_rest import KISRestClient
from broker.kis_websocket import KISWebSocket
from broker.order_executor import OrderExecutor
from config.constants import DAILY_SCREENING_HOUR, DAILY_SCREENING_MINUTE
from config.settings import get_settings
from core.database import Database
from core.events import EventBus
from portfolio.correlation_groups import CorrelationGroupManager
from portfolio.position_manager import PositionManager
from portfolio.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# ════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════

KILL_SWITCH_PATH = Path("KILL_SWITCH")
KILL_SWITCH_CHECK_INTERVAL_SECONDS = 30


# ════════════════════════════════════════════════════════════════
# Trading Bot
# ════════════════════════════════════════════════════════════════


class TradingBot:
    """메인 트레이딩 봇 오케스트레이터.

    APScheduler cron 기반으로 전체 사이클을 관리한다:
      - KST 22:00 (UTC 13:00): 장전 준비 (pre_market)
      - KST 23:30 (UTC 14:30): 장중 모니터링 시작 (market_open)
      - KST 06:30 (UTC 21:30): 장후 정리 (post_market)

    킬스위치: 프로젝트 루트에 ``KILL_SWITCH`` 파일이 존재하면
    모니터링을 중단하고 봇을 안전하게 종료한다.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

        # ── Core Infrastructure ──
        self._db = Database(self._settings.db_path)
        self._event_bus = EventBus()

        # ── Broker Layer ──
        self._auth = KISAuth()
        self._rest_client = KISRestClient(self._auth)

        # ── Portfolio Layer ──
        self._account_mgr = AccountManager(self._rest_client, self._db)
        self._position_mgr = PositionManager(self._db)
        self._correlation_mgr = CorrelationGroupManager()
        self._risk_mgr = RiskManager(self._position_mgr, self._correlation_mgr)

        # ── Order Executor (after position_mgr for fill-confirmed management) ──
        self._order_executor = OrderExecutor(
            self._rest_client,
            self._db,
            self._position_mgr,
        )

        # ── Bot Layer ──
        self._mode_mgr = ModeManager(self._db)
        self._intraday = IntradayMonitor(
            db=self._db,
            event_bus=self._event_bus,
            rest_client=self._rest_client,
            order_executor=self._order_executor,
            position_mgr=self._position_mgr,
            risk_mgr=self._risk_mgr,
            correlation_mgr=self._correlation_mgr,
        )
        self._pre_market = PreMarketPreparer(
            db=self._db,
            auth=self._auth,
            rest_client=self._rest_client,
            account_mgr=self._account_mgr,
            position_mgr=self._position_mgr,
        )
        self._post_market = PostMarketProcessor(
            db=self._db,
            rest_client=self._rest_client,
            account_mgr=self._account_mgr,
            position_mgr=self._position_mgr,
            order_executor=self._order_executor,
        )

        # ── Daily Screening ──
        self._daily_screening = DailyScreeningPipeline(db=self._db)

        # ── WebSocket (price callback → intraday monitor) ──
        self._websocket = KISWebSocket(
            auth=self._auth,
            price_callback=self._intraday.on_price_update,
            rest_client=self._rest_client,
        )

        # ── Scheduler ──
        self._scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
        self._running: bool = False
        self._intraday_started: bool = False  # 레이스 컨디션 방지 가드
        self._ws_task: asyncio.Task | None = None
        self._fill_check_task: asyncio.Task | None = None

    # ────────────────────────────────────────────────────────
    # Main Entry Point
    # ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """봇 메인 루프.

        1. DB 초기화 & 모드 설정
        2. KIS 인증 초기화
        3. APScheduler 크론 작업 등록 및 시작
        4. 킬스위치 체크 루프
        """
        logger.info(
            "trading_bot_starting",
            mode=self._settings.trading_mode.value,
            db_path=self._settings.db_path,
        )

        # Step 1: 인프라 초기화
        await self._db.initialize()
        await self._mode_mgr.initialize()

        await self._initialize_auth_with_retry(max_retries=5, base_delay=120)

        # Step 2.5: 브로커 포지션 동기화 (DB ↔ 브로커 불일치 방지)
        try:
            sync_result = await self._account_mgr.sync_positions()
            logger.info("startup_sync_positions", **sync_result)
        except Exception as exc:
            logger.warning("startup_sync_positions_failed", error=str(exc))

        # Step 2.6: 최초 실행 시 시작 잔고 기록
        await self._record_starting_equity()

        # Step 3: 봇 상태 DB 기록
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.set_state("bot_started_at", now_iso)
        await self._db.set_state("last_heartbeat", now_iso)
        await self._db.set_state("trading_mode", self._settings.trading_mode.value)

        # Step 4: 스케줄러 설정
        self._setup_scheduler()
        self._scheduler.start()
        self._running = True

        logger.info(
            "trading_bot_running",
            mode=self._mode_mgr.mode_label,
            scheduler_jobs=len(self._scheduler.get_jobs()),
        )

        # Step 4.5: 장중 재시작 감지 → pre_market + intraday 즉시 실행
        await self._catchup_if_market_open()

        # Step 5: 킬스위치 감시 + heartbeat 루프
        try:
            while self._running:
                if self._check_kill_switch():
                    logger.warning("kill_switch_detected")
                    break
                # heartbeat 갱신
                await self._db.set_state(
                    "last_heartbeat",
                    datetime.now(timezone.utc).isoformat(),
                )
                await asyncio.sleep(KILL_SWITCH_CHECK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("trading_bot_cancelled")
        finally:
            await self.shutdown()

    # ────────────────────────────────────────────────────────
    # Scheduler Setup
    # ────────────────────────────────────────────────────────

    def _setup_scheduler(self) -> None:
        """APScheduler 크론 작업을 등록한다.

        모든 시각은 KST(Asia/Seoul) 기준:
          - 20:00 KST: 매일 CANSLIM 스크리닝 (pre_market 2시간 전)
          - 22:00 KST: 장전 준비 (US 마켓 오픈 ~1.5h 전)
          - 23:30 KST: 장중 모니터링 시작 (US 마켓 오픈)
          - 06:30 KST: 장후 정리 (US 마켓 종료 ~30min 후)

        월~금만 실행 (day_of_week="mon-fri").
        """
        # 매일 스크리닝: KST 20:00 (pre_market 2시간 전)
        self._scheduler.add_job(
            self._run_daily_screening,
            trigger=CronTrigger(
                hour=DAILY_SCREENING_HOUR,
                minute=DAILY_SCREENING_MINUTE,
                day_of_week="mon-fri",
                timezone="Asia/Seoul",
            ),
            id="daily_screening",
            name="Daily CANSLIM Screening",
            misfire_grace_time=7200,
        )

        # 장전 준비: KST 22:00 (= UTC 13:00)
        self._scheduler.add_job(
            self._run_pre_market,
            trigger=CronTrigger(
                hour=22,
                minute=0,
                day_of_week="mon-fri",
                timezone="Asia/Seoul",
            ),
            id="pre_market",
            name="Pre-Market Preparation",
            misfire_grace_time=7200,
        )

        # 장중 모니터링 시작: KST 23:30 (= UTC 14:30)
        self._scheduler.add_job(
            self._start_intraday,
            trigger=CronTrigger(
                hour=23,
                minute=30,
                day_of_week="mon-fri",
                timezone="Asia/Seoul",
            ),
            id="market_open",
            name="Market Open - Start Intraday",
            misfire_grace_time=7200,
        )

        # 장후 정리: KST 06:30 (= UTC 21:30, 다음 날)
        self._scheduler.add_job(
            self._run_post_market,
            trigger=CronTrigger(
                hour=6,
                minute=30,
                day_of_week="tue-sat",
                timezone="Asia/Seoul",
            ),
            id="post_market",
            name="Post-Market Cleanup",
            misfire_grace_time=7200,
        )

        logger.info(
            "scheduler_configured",
            jobs=[j.id for j in self._scheduler.get_jobs()],
        )

    # ────────────────────────────────────────────────────────
    # Auth Initialization with Retry
    # ────────────────────────────────────────────────────────

    async def _initialize_auth_with_retry(
        self,
        max_retries: int = 5,
        base_delay: int = 120,
    ) -> None:
        """KIS 인증 초기화 (지수 백오프).

        KIS는 토큰 발급을 1분당 1회로 제한한다.
        systemd 자동재시작과 겹치면 rate-limit death spiral이 발생하므로
        봇 레벨에서 지수 백오프로 충분한 대기 시간을 확보한다.

        백오프: 120 → 240 → 480 → 960 → 1920초 (최대 ~32분)
        """
        for attempt in range(1, max_retries + 1):
            delay = base_delay * (2 ** (attempt - 1))
            try:
                await self._auth.initialize()
                return
            except Exception as exc:
                logger.error(
                    "auth_initialization_failed",
                    attempt=attempt,
                    max_retries=max_retries,
                    next_retry_delay=delay,
                    error=str(exc),
                )
                if attempt >= max_retries:
                    raise RuntimeError(f"KIS auth failed after {max_retries} attempts") from exc
                await asyncio.sleep(delay)

    # ────────────────────────────────────────────────────────
    # Market-Hours Catch-Up
    # ────────────────────────────────────────────────────────

    async def _catchup_if_market_open(self) -> None:
        """Detect mid-session restart during US market hours and auto-recover.

        US regular hours: 09:30–16:00 ET (KST 23:30–06:00 next day).
        If the bot starts inside this window, run pre_market + start_intraday
        immediately so we don't sit idle until next scheduled trigger.
        """
        now_et = datetime.now(ZoneInfo("America/New_York"))
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

        weekday = now_et.weekday()  # 0=Mon ... 4=Fri
        if weekday > 4:
            logger.info("catchup_skip_weekend", weekday=weekday)
            return

        if not (market_open <= now_et <= market_close):
            logger.info(
                "catchup_skip_outside_hours",
                now_et=now_et.isoformat(),
            )
            return

        logger.warning(
            "catchup_mid_session_restart_detected",
            now_et=now_et.isoformat(),
        )

        await self._run_pre_market()
        await self._start_intraday()

    # ────────────────────────────────────────────────────────
    # Scheduled Tasks
    # ────────────────────────────────────────────────────────

    async def _record_starting_equity(self) -> None:
        """봇 최초 실행 시 실제 계좌 잔고를 DB에 기록한다.

        이미 기록된 유효한 값(> 0)이 있으면 건너뛴다.
        0으로 잘못 기록된 경우 다시 조회한다.
        누적 P&L 계산의 기준점으로 사용된다.
        """
        existing = await self._db.get_state("starting_equity")
        if existing is not None and float(existing) > 0:
            logger.info("starting_equity_already_recorded", value=existing)
            return

        try:
            account_info = await self._account_mgr.get_account_info()
            equity = account_info.total_equity
            if equity > 0:
                await self._db.set_state("starting_equity", str(equity))
                logger.info("starting_equity_recorded", equity=equity)
            else:
                logger.warning("starting_equity_zero_skipped", equity=equity)
        except Exception:
            logger.exception("starting_equity_record_failed")

    async def _run_daily_screening(self) -> None:
        """매일 CANSLIM 스크리닝 — KST 20:00 실행.

        1. 유니버스 가격 갱신 (최근 5거래일)
        2. Earnings Calendar 기반 재무 데이터 갱신
        3. CANSLIM + Minervini 스크리닝 → 워치리스트 업데이트
        4. 완료 후 놓친 스케줄 작업 복구
        """
        logger.info("daily_screening_start")

        try:
            result = await self._daily_screening.run()
            logger.info(
                "daily_screening_complete",
                universe=result.get("universe_count", 0),
                watchlist=result.get("watchlist_count", 0),
                elapsed=result.get("elapsed", 0),
            )
        except Exception as e:
            logger.error("daily_screening_failed", error=str(e), exc_info=True)

        await self._check_and_recover_missed_jobs()

    async def _check_and_recover_missed_jobs(self) -> None:
        """스크리닝 완료 후, 놓친 장전/장중 스케줄을 즉시 실행.

        daily_screening이 45분+ 걸리면 pre_market(22:00)이나
        market_open(23:30)이 misfire될 수 있다. 현재 KST 시각을 확인하여
        해당 작업이 오늘 아직 실행되지 않았으면 즉시 실행한다.
        """
        now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
        today_str = now_kst.strftime("%Y-%m-%d")
        weekday = now_kst.weekday()

        if weekday > 4:
            return

        last_pre_market_date = await self._db.get_state("last_pre_market_date")
        last_market_open_date = await self._db.get_state("last_market_open_date")

        if now_kst.hour >= 22 and last_pre_market_date != today_str:
            logger.warning(
                "recover_missed_pre_market",
                now_kst=now_kst.isoformat(),
                last_run=last_pre_market_date,
            )
            await self._run_pre_market()

        if (
            now_kst.hour > 23 or (now_kst.hour == 23 and now_kst.minute >= 30)
        ) and last_market_open_date != today_str:
            logger.warning(
                "recover_missed_market_open",
                now_kst=now_kst.isoformat(),
                last_run=last_market_open_date,
            )
            await self._start_intraday()

    async def _run_pre_market(self) -> None:
        """장전 준비 — KST 22:00 실행.

        1. PreMarketPreparer 실행 (토큰/데이터/시그널/마켓필터)
        2. 결과를 인트라데이 모니터에 주입
        3. 실패 시 최대 3회 재시도 (5분 간격)
        """
        logger.info("pre_market_start")

        max_retries = 3
        retry_delay = 300

        for attempt in range(1, max_retries + 1):
            try:
                result = await self._pre_market.run()

                signals = result.get("signals", [])
                self._intraday.precomputed_signals = {s.ticker: s for s in signals}
                self._intraday.market_filter_pass = result.get("market_filter_pass", False)

                logger.info(
                    "pre_market_complete",
                    market_filter=result.get("market_filter_pass"),
                    watchlist=result.get("watchlist_count", 0),
                    positions=result.get("position_count", 0),
                    signals=len(signals),
                )

                today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
                await self._db.set_state("last_pre_market_date", today_str)
                return

            except Exception as e:
                logger.error(
                    "pre_market_failed",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                    exc_info=True,
                )
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)

        logger.critical(
            "pre_market_all_retries_exhausted",
            max_retries=max_retries,
        )

    async def _start_intraday(self) -> None:
        """장중 모니터링 시작 — KST 23:30 실행.

        1. 인트라데이 모니터 시작
        2. WebSocket 연결 및 종목 구독
        """
        # 레이스 컨디션 방지: 스케줄러와 catchup이 동시 호출 시 이중 실행 차단
        if self._intraday_started:
            logger.warning("intraday_already_started_skipping")
            return
        self._intraday_started = True

        logger.info("intraday_start")

        try:
            # 재시작 등으로 precomputed_signals가 비어있으면 pre_market을 먼저 실행
            if not self._intraday.precomputed_signals:
                logger.warning(
                    "intraday_signals_empty_running_pre_market",
                    msg="precomputed_signals 비어있음 → pre_market 실행",
                )
                await self._run_pre_market()

            await self._intraday.start()

            tickers = list(self._intraday.precomputed_signals.keys())

            open_positions = await self._position_mgr.get_open_positions()
            for pos in open_positions:
                if pos.ticker not in tickers:
                    tickers.append(pos.ticker)

            if not tickers:
                logger.critical(
                    "intraday_no_tickers_available",
                    precomputed_signals=len(self._intraday.precomputed_signals),
                    market_filter=self._intraday.market_filter_pass,
                )
                return

            ticker_exchanges = await self._build_ticker_exchange_map(tickers)

            self._ws_task = asyncio.create_task(
                self._websocket.start(ticker_exchanges),
                name="websocket_listener",
            )
            self._fill_check_task = asyncio.create_task(
                self._fill_check_loop(),
                name="fill_check_loop",
            )
            await self._db.set_state("ws_status", "CONNECTED")

            today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
            await self._db.set_state("last_market_open_date", today_str)

            logger.info("intraday_started", tickers_count=len(tickers))

        except Exception as e:
            logger.error("intraday_start_failed", error=str(e), exc_info=True)

    async def _build_ticker_exchange_map(self, tickers: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for ticker in tickers:
            try:
                cursor = await self._db.conn.execute(
                    "SELECT exchange FROM watchlist WHERE ticker = ?",
                    (ticker,),
                )
                row = await cursor.fetchone()
                result[ticker] = row[0] if row and row[0] else "NASD"
            except Exception:
                result[ticker] = "NASD"
        return result

    async def _fill_check_loop(self) -> None:
        FILL_CHECK_INTERVAL = 30
        HEARTBEAT_INTERVAL = 300  # 5분마다 heartbeat 로그
        last_heartbeat = 0.0
        check_count = 0
        try:
            while True:
                await asyncio.sleep(FILL_CHECK_INTERVAL)
                check_count += 1
                try:
                    filled = await self._order_executor.check_order_fills()
                    if filled:
                        logger.info("fill_check_matched", count=len(filled))
                except Exception:
                    logger.exception("fill_check_error")

                # 주기적 heartbeat 로그
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    last_heartbeat = now
                    pending = await self._db.conn.execute(
                        "SELECT COUNT(*) FROM orders WHERE status IN ('SUBMITTED','PARTIAL')"
                    )
                    pending_count = (await pending.fetchone())[0]
                    logger.info(
                        "fill_check_heartbeat",
                        checks_done=check_count,
                        pending_orders=pending_count,
                    )
        except asyncio.CancelledError:
            pass

    async def _stop_intraday(self) -> None:
        """장중 모니터링 중지.

        WebSocket 연결을 끊고 인트라데이 모니터를 정지한다.
        """
        logger.info("intraday_stopping")

        try:
            await self._db.set_state("ws_status", "DISCONNECTED")
            await self._websocket.stop()

            for task_ref in (self._ws_task, self._fill_check_task):
                if task_ref is not None and not task_ref.done():
                    task_ref.cancel()
                    try:
                        await task_ref
                    except asyncio.CancelledError:
                        pass
            self._ws_task = None
            self._fill_check_task = None

            await self._intraday.stop()
            self._intraday_started = False  # 다음 세션을 위해 가드 리셋
            logger.info("intraday_stopped")

        except Exception as e:
            self._intraday_started = False
            logger.error("intraday_stop_failed", error=str(e), exc_info=True)

    async def _run_post_market(self) -> None:
        """장후 정리 — KST 06:30 실행.

        1. 장중 모니터링 중지
        2. PostMarketProcessor 실행 (동기화/미체결/리포트)
        """
        logger.info("post_market_start")

        try:
            # 모니터링 중지
            await self._stop_intraday()

            # 장후 정리 실행
            result = await self._post_market.run()

            logger.info(
                "post_market_complete",
                sync=result.get("sync_result"),
                cancelled=result.get("cancelled_orders", 0),
            )

        except Exception as e:
            logger.error("post_market_failed", error=str(e), exc_info=True)

    # ────────────────────────────────────────────────────────
    # Kill Switch
    # ────────────────────────────────────────────────────────

    def _check_kill_switch(self) -> bool:
        """킬스위치 파일 존재 여부를 확인한다.

        프로젝트 루트에 ``KILL_SWITCH`` 파일이 존재하면
        True를 반환하여 봇을 안전하게 종료시킨다.

        Returns:
            True if KILL_SWITCH file exists, False otherwise.
        """
        return KILL_SWITCH_PATH.exists()

    # ────────────────────────────────────────────────────────
    # Shutdown
    # ────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """봇 안전 종료.

        1. 스케줄러 중지
        2. 장중 모니터링 중지
        3. DB 연결 종료
        """
        logger.info("trading_bot_shutting_down")
        self._running = False

        # 스케줄러 중지
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

        # 장중 모니터링 중지
        await self._stop_intraday()

        # DB 종료
        await self._db.close()

        logger.info("trading_bot_shutdown_complete")
