"""
메인 오케스트레이터 — APScheduler로 전체 트레이딩 사이클 관리.

- KST 22:00: 장전 준비
- KST 23:30~06:00: 장중 모니터링
- KST 06:30: 장후 정리
- 킬스위치: KILL_SWITCH 파일 존재 시 정지
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

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
        self._order_executor = OrderExecutor(self._rest_client, self._db)

        # ── Portfolio Layer ──
        self._account_mgr = AccountManager(self._rest_client, self._db)
        self._position_mgr = PositionManager(self._db)
        self._correlation_mgr = CorrelationGroupManager()
        self._risk_mgr = RiskManager(self._position_mgr, self._correlation_mgr)

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
        )

        # ── Scheduler ──
        self._scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
        self._running: bool = False
        self._ws_task: asyncio.Task | None = None

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

        # Step 2: KIS 인증 (최대 3회 시도, 실패 시 2분 대기 후 재시도)
        await self._initialize_auth_with_retry(max_retries=3, delay_seconds=120)

        # Step 2.5: 최초 실행 시 시작 잔고 기록
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
            misfire_grace_time=600,
        )

        # 장전 준비: KST 22:00 (= UTC 13:00)
        self._scheduler.add_job(
            self._run_pre_market,
            trigger=CronTrigger(
                hour=22, minute=0, day_of_week="mon-fri", timezone="Asia/Seoul",
            ),
            id="pre_market",
            name="Pre-Market Preparation",
            misfire_grace_time=300,
        )

        # 장중 모니터링 시작: KST 23:30 (= UTC 14:30)
        self._scheduler.add_job(
            self._start_intraday,
            trigger=CronTrigger(
                hour=23, minute=30, day_of_week="mon-fri", timezone="Asia/Seoul",
            ),
            id="market_open",
            name="Market Open - Start Intraday",
            misfire_grace_time=300,
        )

        # 장후 정리: KST 06:30 (= UTC 21:30, 다음 날)
        self._scheduler.add_job(
            self._run_post_market,
            trigger=CronTrigger(
                hour=6, minute=30, day_of_week="tue-sat", timezone="Asia/Seoul",
            ),
            id="post_market",
            name="Post-Market Cleanup",
            misfire_grace_time=300,
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
        max_retries: int = 3,
        delay_seconds: int = 120,
    ) -> None:
        """KIS 인증 초기화를 재시도 로직과 함께 수행한다.

        ``KISAuth.initialize()`` 자체에도 요청별 재시도가 있지만,
        전체 초기화 프로세스(토큰 + approval key)가 실패할 경우
        봇 레벨에서 추가로 재시도한다.

        Args:
            max_retries: 최대 시도 횟수
            delay_seconds: 실패 시 대기 시간 (초)
        """
        for attempt in range(1, max_retries + 1):
            try:
                await self._auth.initialize()
                return
            except Exception as exc:
                logger.error(
                    "auth_initialization_failed",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(exc),
                    msg=f"KIS 인증 실패 ({attempt}/{max_retries}). "
                        f"{delay_seconds}초 후 재시도합니다.",
                )
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"KIS 인증 {max_retries}회 모두 실패. 봇을 시작할 수 없습니다."
                    ) from exc
                await asyncio.sleep(delay_seconds)

    # ────────────────────────────────────────────────────────
    # Scheduled Tasks
    # ────────────────────────────────────────────────────────

    async def _record_starting_equity(self) -> None:
        """봇 최초 실행 시 실제 계좌 잔고를 DB에 기록한다.

        이미 기록된 값이 있으면 건너뛴다.
        누적 P&L 계산의 기준점으로 사용된다.
        """
        existing = await self._db.get_state("starting_equity")
        if existing is not None:
            logger.info("starting_equity_already_recorded", value=existing)
            return

        try:
            account_info = await self._account_mgr.get_account_info()
            equity = account_info.total_equity
            await self._db.set_state("starting_equity", str(equity))
            logger.info("starting_equity_recorded", equity=equity)
        except Exception:
            logger.exception("starting_equity_record_failed")

    async def _run_daily_screening(self) -> None:
        """매일 CANSLIM 스크리닝 — KST 20:00 실행.

        1. 유니버스 가격 갱신 (최근 5거래일)
        2. Earnings Calendar 기반 재무 데이터 갱신
        3. CANSLIM + Minervini 스크리닝 → 워치리스트 업데이트
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

    async def _run_pre_market(self) -> None:
        """장전 준비 — KST 22:00 실행.

        1. PreMarketPreparer 실행 (토큰/데이터/시그널/마켓필터)
        2. 결과를 인트라데이 모니터에 주입
        """
        logger.info("pre_market_start")

        try:
            result = await self._pre_market.run()

            # 사전 계산된 시그널을 인트라데이 모니터에 주입
            signals = result.get("signals", [])
            self._intraday.precomputed_signals = {
                s.ticker: s for s in signals
            }
            self._intraday.market_filter_pass = result.get("market_filter_pass", False)

            logger.info(
                "pre_market_complete",
                market_filter=result.get("market_filter_pass"),
                watchlist=result.get("watchlist_count", 0),
                positions=result.get("position_count", 0),
                signals=len(signals),
            )

        except Exception as e:
            logger.error("pre_market_failed", error=str(e), exc_info=True)

    async def _start_intraday(self) -> None:
        """장중 모니터링 시작 — KST 23:30 실행.

        1. 인트라데이 모니터 시작
        2. WebSocket 연결 및 종목 구독
        """
        logger.info("intraday_start")

        try:
            await self._intraday.start()

            # 구독할 종목 목록 (사전 계산된 시그널이 있는 종목)
            tickers = list(self._intraday.precomputed_signals.keys())

            # 보유 중인 포지션 종목도 추가
            open_positions = await self._position_mgr.get_open_positions()
            for pos in open_positions:
                if pos.ticker not in tickers:
                    tickers.append(pos.ticker)

            if not tickers:
                logger.warning("intraday_no_tickers")
                return

            # WebSocket 을 별도 태스크로 시작
            self._ws_task = asyncio.create_task(
                self._websocket.start(tickers),
                name="websocket_listener",
            )

            logger.info("intraday_started", tickers_count=len(tickers))

        except Exception as e:
            logger.error("intraday_start_failed", error=str(e), exc_info=True)

    async def _stop_intraday(self) -> None:
        """장중 모니터링 중지.

        WebSocket 연결을 끊고 인트라데이 모니터를 정지한다.
        """
        logger.info("intraday_stopping")

        try:
            await self._websocket.stop()
            if self._ws_task is not None and not self._ws_task.done():
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except asyncio.CancelledError:
                    pass
                self._ws_task = None

            await self._intraday.stop()
            logger.info("intraday_stopped")

        except Exception as e:
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
