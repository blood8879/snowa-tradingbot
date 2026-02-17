"""
Telegram Bot — 실시간 알림 + 대화형 명령어.
python-telegram-bot v20+ (async) 사용.

명령어: /start, /stop, /mode, /status, /positions, /watchlist, /orders, /pnl, /trades, /journal
알림: 진입, 청산, 손절, 에러, 일일요약
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import get_settings
from core.database import Database

logger = structlog.get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════

KILL_SWITCH_FILE = Path("KILL_SWITCH")

HELP_TEXT = (
    "🤖 <b>Snowa Trading Bot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📌 사용 가능한 명령어:\n\n"
    "/start — 봇 시작 / 도움말\n"
    "/stop — 긴급 정지 (KILL_SWITCH)\n"
    "/mode — 현재 트레이딩 모드\n"
    "/status — 시스템 상태 요약\n"
    "/positions — 보유 포지션 상세\n"
    "/watchlist — 워치리스트 상위 10종목\n"
    "/orders — 미체결 주문\n"
    "/pnl — 수익률 (오늘/주간/월간/누적)\n"
    "/trades — 최근 거래 내역\n"
    "/journal — 월간 매매일지 요약\n"
)


# ════════════════════════════════════════════════════════════════
# Telegram Notifier
# ════════════════════════════════════════════════════════════════


class TelegramNotifier:
    """
    텔레그램 봇: 실시간 알림 전송 + 대화형 명령어 처리.

    python-telegram-bot v20+ async API 기반.
    모든 메시지는 HTML parse_mode 사용.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._settings = get_settings()
        self._app: Application | None = None
        self._bot_token: str = self._settings.telegram_bot_token
        self._chat_id: str = self._settings.telegram_chat_id
        self._started = False

    # ── Lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        """Application 빌드, 핸들러 등록, 폴링 시작."""
        if not self._bot_token or not self._chat_id:
            logger.warning("telegram_disabled", reason="bot_token 또는 chat_id 미설정")
            return

        self._app = Application.builder().token(self._bot_token).build()

        # 명령어 핸들러 등록
        handlers = [
            ("start", self._cmd_start),
            ("stop", self._cmd_stop),
            ("mode", self._cmd_mode),
            ("status", self._cmd_status),
            ("positions", self._cmd_positions),
            ("watchlist", self._cmd_watchlist),
            ("orders", self._cmd_orders),
            ("pnl", self._cmd_pnl),
            ("trades", self._cmd_trades),
            ("journal", self._cmd_journal),
        ]
        for command, callback in handlers:
            self._app.add_handler(CommandHandler(command, callback))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        self._started = True
        logger.info("telegram_bot_started")

    async def stop(self) -> None:
        """봇 정지."""
        if self._app and self._started:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._started = False
            logger.info("telegram_bot_stopped")

    async def send_message(self, text: str) -> None:
        """chat_id 로 HTML 메시지 전송."""
        if not self._app or not self._chat_id:
            logger.debug("telegram_send_skipped", reason="bot not configured")
            return

        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("telegram_send_failed")

    # ════════════════════════════════════════════════════════════
    # Command Handlers (11 commands)
    # ════════════════════════════════════════════════════════════

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/start — 환영 + 명령어 목록."""
        await update.message.reply_text(HELP_TEXT, parse_mode="HTML")

    # ── /stop ────────────────────────────────────────────────

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/stop — KILL_SWITCH 파일 생성, 긴급 정지."""
        KILL_SWITCH_FILE.touch()
        text = (
            "🚨 <b>긴급 정지 활성화</b>\n\n"
            "KILL_SWITCH 파일이 생성되었습니다.\n"
            "봇이 다음 루프에서 모든 거래를 중단합니다.\n\n"
            "⚠️ 재시작하려면 KILL_SWITCH 파일을 삭제하세요."
        )
        await update.message.reply_text(text, parse_mode="HTML")
        logger.warning("kill_switch_activated", source="telegram")

    # ── /mode ────────────────────────────────────────────────

    async def _cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/mode — Paper/Live 모드 표시."""
        mode = self._settings.trading_mode.value
        emoji = "📝" if self._settings.is_paper else "💰"
        label = "모의투자 (Paper)" if self._settings.is_paper else "실전 (Live)"
        text = f"{emoji} <b>트레이딩 모드:</b> {label}\n\n설정값: <code>{mode}</code>"
        await update.message.reply_text(text, parse_mode="HTML")

    # ── /status ──────────────────────────────────────────────

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/status — 모드, 시장필터, WS상태, 유닛 사용량."""
        mode_label = "📝 Paper" if self._settings.is_paper else "💰 Live"
        kill_active = "🔴 활성" if KILL_SWITCH_FILE.exists() else "🟢 정상"

        # 시장필터 상태
        market_filter_raw = await self._db.get_state("market_filter_pass")
        if market_filter_raw == "1":
            market_filter = "🟢 통과 (SPY > 200MA)"
        elif market_filter_raw == "0":
            market_filter = "🔴 차단 (SPY ≤ 200MA)"
        else:
            market_filter = "⚪ 미확인"

        # WS 상태
        ws_status = await self._db.get_state("ws_status") or "미확인"

        # 유닛 사용량
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM units u "
            "JOIN positions p ON u.position_id = p.id "
            "WHERE p.status = 'OPEN'"
        )
        row = await cursor.fetchone()
        total_units = row[0] if row else 0

        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'"
        )
        row = await cursor.fetchone()
        open_positions = row[0] if row else 0

        text = (
            "📊 <b>시스템 상태</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"모드: {mode_label}\n"
            f"킬스위치: {kill_active}\n"
            f"시장 필터: {market_filter}\n"
            f"WebSocket: {ws_status}\n"
            f"보유 종목: {open_positions}개\n"
            f"유닛 사용: {total_units}/12\n"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ── /positions ───────────────────────────────────────────

    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/positions — 보유 포지션 상세 (유닛별 진입가, 손절, P&L)."""
        # 유닛 총수
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM units u "
            "JOIN positions p ON u.position_id = p.id "
            "WHERE p.status = 'OPEN'"
        )
        row = await cursor.fetchone()
        total_units_used = row[0] if row else 0

        # 오픈 포지션
        cursor = await self._db.conn.execute(
            "SELECT id, ticker, system, total_shares, avg_entry_price, "
            "current_stop_price, total_cost "
            "FROM positions WHERE status = 'OPEN' "
            "ORDER BY opened_at DESC"
        )
        positions = await cursor.fetchall()

        if not positions:
            await update.message.reply_text("📋 보유 포지션이 없습니다.", parse_mode="HTML")
            return

        header = f"📋 <b>보유 포지션</b> ({len(positions)}종목 / {total_units_used}/12 유닛)\n"
        lines: list[str] = [header, "━━━━━━━━━━━━━━━━━━━━━━"]

        for pos_id, ticker, system, shares, avg_price, stop_price, total_cost in positions:
            # 유닛 정보
            cursor = await self._db.conn.execute(
                "SELECT unit_number, entry_price, shares, current_stop_price "
                "FROM units WHERE position_id = ? ORDER BY unit_number",
                (pos_id,),
            )
            units = await cursor.fetchall()
            unit_count = len(units)

            # 현재가 조회 (bot_state 에서)
            current_price_raw = await self._db.get_state(f"price_{ticker}")
            current_price = float(current_price_raw) if current_price_raw else None

            lines.append(f"\n<b>{ticker}</b> — {system} | {unit_count}유닛")

            if current_price and avg_price > 0:
                pnl_pct = (current_price - avg_price) / avg_price * 100
                pnl_amount = (current_price - avg_price) * shares
                pnl_sign = "+" if pnl_pct >= 0 else ""
                lines.append(
                    f"  진입: ${avg_price:,.2f} → 현재: ${current_price:,.2f} ({pnl_sign}{pnl_pct:.2f}%)"
                )
                lines.append(
                    f"  미실현 P&L: {pnl_sign}${pnl_amount:,.2f}"
                )
            else:
                lines.append(f"  평균진입가: ${avg_price:,.2f} | 수량: {shares}주")

            if avg_price > 0:
                stop_pct = (stop_price - avg_price) / avg_price * 100
                lines.append(f"  손절: ${stop_price:,.2f} ({stop_pct:+.2f}%)")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ── /watchlist ───────────────────────────────────────────

    async def _cmd_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/watchlist — 워치리스트 상위 10종목."""
        cursor = await self._db.conn.execute(
            "SELECT ticker, custom_composite_score, rs_rating, sector "
            "FROM watchlist "
            "WHERE status = 'ACTIVE' "
            "ORDER BY custom_composite_score DESC "
            "LIMIT 10"
        )
        rows = await cursor.fetchall()

        if not rows:
            await update.message.reply_text("📭 워치리스트가 비어있습니다.", parse_mode="HTML")
            return

        cursor_cnt = await self._db.conn.execute(
            "SELECT COUNT(*) FROM watchlist WHERE status = 'ACTIVE'"
        )
        total_row = await cursor_cnt.fetchone()
        total_count = total_row[0] if total_row else 0

        lines: list[str] = [
            f"📋 <b>워치리스트 상위 10</b> (총 {total_count}종목)\n",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for idx, (ticker, score, rs, sector) in enumerate(rows, 1):
            score_str = f"{score:.1f}" if score is not None else "-"
            rs_str = f"{rs:.0f}" if rs is not None else "-"
            sector_str = sector or "-"
            lines.append(
                f"{idx}. <b>{ticker}</b>  점수:{score_str}  RS:{rs_str}  {sector_str}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ── /orders ──────────────────────────────────────────────

    async def _cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/orders — 미체결 주문."""
        cursor = await self._db.conn.execute(
            "SELECT ticker, side, order_type, requested_shares, requested_price, status, created_at "
            "FROM orders "
            "WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIAL') "
            "ORDER BY created_at DESC "
            "LIMIT 20"
        )
        rows = await cursor.fetchall()

        if not rows:
            await update.message.reply_text("📭 미체결 주문이 없습니다.", parse_mode="HTML")
            return

        lines: list[str] = [
            f"📋 <b>미체결 주문</b> ({len(rows)}건)\n",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for ticker, side, order_type, req_shares, req_price, status, created_at in rows:
            side_emoji = "🟢" if side == "BUY" else "🔴"
            created_short = created_at[:16] if created_at else ""
            lines.append(
                f"{side_emoji} <b>{ticker}</b> {side} {order_type}\n"
                f"   {req_shares}주 @ ${req_price:,.2f} [{status}] {created_short}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ── /pnl ─────────────────────────────────────────────────

    async def _cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/pnl — 수익률 (오늘/주간/월간/누적) from daily_log."""
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # 오늘
        cursor = await self._db.conn.execute(
            "SELECT daily_pnl, daily_pnl_pct, cumulative_pnl, account_equity, max_drawdown_pct "
            "FROM daily_log WHERE date = ?",
            (today,),
        )
        today_row = await cursor.fetchone()

        # 주간 합계
        cursor = await self._db.conn.execute(
            "SELECT SUM(daily_pnl), SUM(daily_pnl_pct) "
            "FROM daily_log WHERE date >= ?",
            (week_ago,),
        )
        week_row = await cursor.fetchone()

        # 월간 합계
        cursor = await self._db.conn.execute(
            "SELECT SUM(daily_pnl), SUM(daily_pnl_pct) "
            "FROM daily_log WHERE date >= ?",
            (month_ago,),
        )
        month_row = await cursor.fetchone()

        # 누적 (최신 row)
        cursor = await self._db.conn.execute(
            "SELECT cumulative_pnl, max_drawdown_pct, account_equity "
            "FROM daily_log ORDER BY date DESC LIMIT 1"
        )
        latest_row = await cursor.fetchone()

        def _fmt_pnl(amount: float | None, pct: float | None) -> str:
            if amount is None:
                return "데이터 없음"
            sign = "+" if amount >= 0 else ""
            pct_str = f" ({sign}{pct:.2f}%)" if pct is not None else ""
            return f"{sign}${amount:,.2f}{pct_str}"

        today_pnl = _fmt_pnl(
            today_row[0] if today_row else None,
            today_row[1] if today_row else None,
        )
        week_pnl = _fmt_pnl(
            week_row[0] if week_row else None,
            week_row[1] if week_row else None,
        )
        month_pnl = _fmt_pnl(
            month_row[0] if month_row else None,
            month_row[1] if month_row else None,
        )

        if latest_row:
            cum_pnl = latest_row[0] or 0.0
            mdd = latest_row[1] or 0.0
            equity = latest_row[2] or 0.0
            cum_sign = "+" if cum_pnl >= 0 else ""
            cum_str = f"{cum_sign}${cum_pnl:,.2f}"
            equity_str = f"${equity:,.2f}"
            mdd_str = f"{mdd:.2f}%"
        else:
            cum_str = "데이터 없음"
            equity_str = "데이터 없음"
            mdd_str = "데이터 없음"

        text = (
            "💰 <b>수익률 요약</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 오늘: {today_pnl}\n"
            f"📊 주간 (7일): {week_pnl}\n"
            f"📈 월간 (30일): {month_pnl}\n"
            f"📉 누적 P&L: {cum_str}\n"
            f"🏦 계좌 자산: {equity_str}\n"
            f"📉 MDD: {mdd_str}\n"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ── /trades ──────────────────────────────────────────────

    async def _cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/trades — 최근 N건 거래내역 (기본 10건, 인자로 변경 가능)."""
        limit = 10
        if context.args:
            try:
                limit = min(int(context.args[0]), 50)
            except (ValueError, IndexError):
                pass

        cursor = await self._db.conn.execute(
            "SELECT ticker, side, order_type, filled_shares, filled_price, "
            "filled_at, notes "
            "FROM orders "
            "WHERE status = 'FILLED' "
            "ORDER BY filled_at DESC "
            "LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()

        if not rows:
            await update.message.reply_text("📭 체결된 거래가 없습니다.", parse_mode="HTML")
            return

        lines: list[str] = [
            f"📋 <b>최근 거래</b> ({len(rows)}건)\n",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for ticker, side, order_type, shares, price, filled_at, notes in rows:
            side_emoji = "🟢" if side == "BUY" else "🔴"
            filled_short = filled_at[:16] if filled_at else ""
            price_str = f"${price:,.2f}" if price else "-"
            lines.append(
                f"{side_emoji} <b>{ticker}</b> {side} {order_type}\n"
                f"   {shares}주 @ {price_str}  {filled_short}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # ── /journal ─────────────────────────────────────────────

    async def _cmd_journal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/journal — 월간 매매일지 (승률, R:R, MDD)."""
        # 이번 달 범위
        now = datetime.now()
        month_start = now.strftime("%Y-%m-01")
        month_end = now.strftime("%Y-%m-%d")

        # 이번 달 청산된 포지션
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM positions "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at <= ?",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        total_closed = row[0] if row else 0

        # 승리 (realized_pnl > 0)
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM positions "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at <= ? "
            "AND realized_pnl > 0",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        wins = row[0] if row else 0

        # 패배 (realized_pnl <= 0)
        losses = total_closed - wins

        # 평균 수익 / 평균 손실
        cursor = await self._db.conn.execute(
            "SELECT AVG(realized_pnl) FROM positions "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at <= ? "
            "AND realized_pnl > 0",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        avg_win = row[0] if row and row[0] else 0.0

        cursor = await self._db.conn.execute(
            "SELECT AVG(realized_pnl) FROM positions "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at <= ? "
            "AND realized_pnl <= 0",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        avg_loss = row[0] if row and row[0] else 0.0

        # R:R 비율
        rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        # 월간 총 PnL
        cursor = await self._db.conn.execute(
            "SELECT SUM(realized_pnl) FROM positions "
            "WHERE status = 'CLOSED' AND closed_at >= ? AND closed_at <= ?",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        monthly_pnl = row[0] if row and row[0] else 0.0

        # MDD (daily_log 에서)
        cursor = await self._db.conn.execute(
            "SELECT MIN(max_drawdown_pct) FROM daily_log "
            "WHERE date >= ? AND date <= ?",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        mdd = row[0] if row and row[0] else 0.0

        # 손절 횟수
        cursor = await self._db.conn.execute(
            "SELECT SUM(stop_losses_count) FROM daily_log "
            "WHERE date >= ? AND date <= ?",
            (month_start, month_end),
        )
        row = await cursor.fetchone()
        stop_count = row[0] if row and row[0] else 0

        month_label = now.strftime("%Y년 %m월")
        pnl_sign = "+" if monthly_pnl >= 0 else ""

        text = (
            f"📓 <b>{month_label} 매매일지</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"총 청산: {total_closed}건 (승 {wins} / 패 {losses})\n"
            f"승률: {win_rate:.1f}%\n"
            f"평균 수익: ${avg_win:,.2f}\n"
            f"평균 손실: ${avg_loss:,.2f}\n"
            f"R:R 비율: {rr_ratio:.2f}\n"
            f"월간 P&L: {pnl_sign}${monthly_pnl:,.2f}\n"
            f"MDD: {mdd:.2f}%\n"
            f"손절 횟수: {stop_count}회\n"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # ════════════════════════════════════════════════════════════
    # Alert Methods (실시간 알림)
    # ════════════════════════════════════════════════════════════

    async def notify_entry(
        self,
        ticker: str,
        system: str,
        unit_num: int,
        shares: int,
        price: float,
        stop_price: float,
        risk_pct: float,
    ) -> None:
        """신규 진입 알림."""
        risk_amount = (price - stop_price) * shares
        text = (
            f"🟢 <b>진입 | {ticker}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"시스템: {system} | 유닛 #{unit_num}\n"
            f"수량: {shares}주 @ ${price:,.2f}\n"
            f"손절가: ${stop_price:,.2f}\n"
            f"리스크: ${risk_amount:,.2f} ({risk_pct:.1f}%)\n"
        )
        await self.send_message(text)
        logger.info("notify_entry_sent", ticker=ticker, system=system, unit=unit_num)

    async def notify_exit(
        self,
        ticker: str,
        reason: str,
        shares: int,
        price: float,
        pnl: float,
        pnl_pct: float,
    ) -> None:
        """청산 알림."""
        emoji = "🔵" if pnl >= 0 else "🟡"
        pnl_sign = "+" if pnl >= 0 else ""
        text = (
            f"{emoji} <b>청산 | {ticker}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"사유: {reason}\n"
            f"수량: {shares}주 @ ${price:,.2f}\n"
            f"실현 P&L: {pnl_sign}${pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%)\n"
        )
        await self.send_message(text)
        logger.info("notify_exit_sent", ticker=ticker, reason=reason, pnl=pnl)

    async def notify_stop_loss(
        self,
        ticker: str,
        shares: int,
        price: float,
        loss: float,
        loss_pct: float,
    ) -> None:
        """손절 알림."""
        text = (
            f"🔴 <b>손절 | {ticker}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"수량: {shares}주 @ ${price:,.2f}\n"
            f"손실: -${abs(loss):,.2f} (-{abs(loss_pct):.2f}%)\n"
        )
        await self.send_message(text)
        logger.warning("notify_stop_loss_sent", ticker=ticker, loss=loss)

    async def notify_error(self, error_type: str, message: str) -> None:
        """에러 알림."""
        text = (
            "⚠️ <b>에러 발생</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"유형: {error_type}\n"
            f"내용: {message}\n"
        )
        await self.send_message(text)
        logger.error("notify_error_sent", error_type=error_type, message=message)

    async def notify_daily_summary(self, daily_log: dict) -> None:
        """일일 요약 알림. daily_log 는 DailyLog 필드를 담은 dict."""
        date = daily_log.get("date", "")
        equity = daily_log.get("account_equity", 0.0)
        daily_pnl = daily_log.get("daily_pnl", 0.0)
        daily_pnl_pct = daily_log.get("daily_pnl_pct", 0.0)
        cumulative = daily_log.get("cumulative_pnl", 0.0)
        positions = daily_log.get("total_positions", 0)
        units = daily_log.get("total_units", 0)
        entries = daily_log.get("entries_count", 0)
        exits = daily_log.get("exits_count", 0)
        stops = daily_log.get("stop_losses_count", 0)
        mdd = daily_log.get("max_drawdown_pct", 0.0)
        market_pass = daily_log.get("market_filter_pass", False)

        market_str = "🟢 통과" if market_pass else "🔴 차단"
        pnl_sign = "+" if daily_pnl >= 0 else ""
        cum_sign = "+" if cumulative >= 0 else ""

        text = (
            f"📊 <b>일일 요약 | {date}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"시장 필터: {market_str}\n"
            f"계좌 자산: ${equity:,.2f}\n"
            f"일간 P&L: {pnl_sign}${daily_pnl:,.2f} ({pnl_sign}{daily_pnl_pct:.2f}%)\n"
            f"누적 P&L: {cum_sign}${cumulative:,.2f}\n"
            f"MDD: {mdd:.2f}%\n"
            f"보유: {positions}종목 / {units}유닛\n"
            f"진입 {entries} | 청산 {exits} | 손절 {stops}\n"
        )
        await self.send_message(text)
        logger.info("notify_daily_summary_sent", date=date)
