"""AI stock report generation and caching.

Reports are keyed by ticker, market, latest financial period, prompt version,
and a hash of financial rows. The LLM is only used when that cache key is
missing or an explicit refresh is requested.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

import aiohttp
import structlog

from config.settings import Settings
from core.database import Database

logger = structlog.get_logger(__name__)

REPORT_TYPE = "CANSLIM_MINERVINI"


class StockReportError(RuntimeError):
    """Raised when a stock report cannot be generated."""


class StockReportService:
    """Build, cache, and retrieve Korean CANSLIM/Minervini stock reports."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    async def get_cached_report(self, ticker: str, market: str) -> dict[str, Any]:
        ticker = ticker.upper()
        eligible = await self._is_eligible(ticker, market)
        financial_context = await self._build_financial_context(ticker, market)
        cached = await self._load_cached_report(
            ticker=ticker,
            market=market,
            report_period=financial_context["report_period"],
            financial_data_hash=financial_context["financial_data_hash"],
        )
        return {
            "ticker": ticker,
            "market": market,
            "eligible": eligible,
            "report_period": financial_context["report_period"],
            "financial_data_hash": financial_context["financial_data_hash"],
            "has_financial_data": financial_context["has_financial_data"],
            "report": cached,
        }

    async def generate_report(
        self,
        ticker: str,
        market: str,
    ) -> dict[str, Any]:
        ticker = ticker.upper()
        if not await self._is_eligible(ticker, market):
            raise StockReportError("ACTIVE 관심종목 또는 OPEN 포지션 종목만 리포트를 생성할 수 있습니다.")

        financial_context = await self._build_financial_context(ticker, market)
        if not financial_context["has_financial_data"]:
            raise StockReportError("저장된 재무 데이터가 없어 리포트를 생성할 수 없습니다.")

        cached = await self._load_cached_report(
            ticker=ticker,
            market=market,
            report_period=financial_context["report_period"],
            financial_data_hash=financial_context["financial_data_hash"],
        )
        if cached is not None:
            return {
                "ticker": ticker,
                "market": market,
                "eligible": True,
                "report_period": financial_context["report_period"],
                "financial_data_hash": financial_context["financial_data_hash"],
                "has_financial_data": True,
                "report": cached,
                "cache_hit": True,
            }

        financial_context = await self._enrich_report_context(financial_context)
        report_json = await self._call_llm(financial_context)
        saved = await self._save_report(financial_context, report_json)
        return {
            "ticker": ticker,
            "market": market,
            "eligible": True,
            "report_period": financial_context["report_period"],
            "financial_data_hash": financial_context["financial_data_hash"],
            "has_financial_data": True,
            "report": saved,
            "cache_hit": False,
        }

    async def get_trade_gate_status(self, ticker: str, market: str) -> dict[str, Any]:
        """Return whether the latest financial-data report allows trading.

        This method is intentionally read-only. Intraday trading should not
        create a fresh LLM request on the signal path; screening is responsible
        for pre-generating reports.
        """
        ticker = ticker.upper()
        financial_context = await self._build_financial_context(ticker, market)
        if not financial_context["has_financial_data"]:
            return {
                "allowed": False,
                "reason": "NO_FINANCIAL_DATA",
                "report": None,
                "report_period": financial_context["report_period"],
            }

        cached = await self._load_cached_report(
            ticker=ticker,
            market=market,
            report_period=financial_context["report_period"],
            financial_data_hash=financial_context["financial_data_hash"],
        )
        if cached is None:
            return {
                "allowed": False,
                "reason": "NO_CURRENT_REPORT",
                "report": None,
                "report_period": financial_context["report_period"],
            }

        verdict = cached.get("verdict")
        return {
            "allowed": verdict == "PASS",
            "reason": "PASS" if verdict == "PASS" else f"VERDICT_{verdict or 'UNKNOWN'}",
            "report": cached,
            "report_period": financial_context["report_period"],
        }

    async def _is_eligible(self, ticker: str, market: str) -> bool:
        cursor = await self._db.conn.execute(
            """
            SELECT 1 FROM watchlist
            WHERE ticker = ? AND market = ? AND status = 'ACTIVE'
            UNION
            SELECT 1 FROM positions
            WHERE ticker = ? AND market = ? AND status = 'OPEN'
            LIMIT 1
            """,
            (ticker, market, ticker, market),
        )
        return await cursor.fetchone() is not None

    async def _build_financial_context(self, ticker: str, market: str) -> dict[str, Any]:
        q_cursor = await self._db.conn.execute(
            """
            SELECT period, report_date, eps, revenue, net_income,
                   shares_outstanding, debt_to_equity, updated_at
            FROM fundamentals
            WHERE ticker = ? AND period_type = 'quarterly'
            ORDER BY report_date DESC, period DESC
            LIMIT 8
            """,
            (ticker,),
        )
        quarterly_rows = await q_cursor.fetchall()

        a_cursor = await self._db.conn.execute(
            """
            SELECT period, report_date, eps, revenue, net_income,
                   shares_outstanding, debt_to_equity, updated_at
            FROM fundamentals
            WHERE ticker = ? AND period_type = 'annual'
            ORDER BY report_date DESC, period DESC
            LIMIT 5
            """,
            (ticker,),
        )
        annual_rows = await a_cursor.fetchall()

        wl_cursor = await self._db.conn.execute(
            """
            SELECT name, quarterly_eps_growth, annual_eps_cagr, rs_rating,
                   institutional_holders, institutional_change_pct,
                   custom_composite_score, minervini_pass, sector, industry
            FROM watchlist
            WHERE ticker = ? AND market = ?
            """,
            (ticker, market),
        )
        watchlist_row = await wl_cursor.fetchone()

        regime_cursor = await self._db.conn.execute(
            """
            SELECT regime, market_filter_pass
            FROM daily_log
            WHERE market = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (market,),
        )
        regime_row = await regime_cursor.fetchone()

        quarterly = [self._financial_row_to_dict(row, "quarterly") for row in quarterly_rows]
        annual = [self._financial_row_to_dict(row, "annual") for row in annual_rows]
        if quarterly:
            report_period = quarterly[0]["period"]
        elif annual:
            report_period = annual[0]["period"]
        else:
            report_period = "NO_FINANCIAL_DATA"
        financial_payload = {"quarterly": quarterly, "annual": annual}
        derived_financial_analysis = self._build_derived_financial_analysis(financial_payload)
        financial_data_hash = hashlib.sha256(
            json.dumps(financial_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        company_name = watchlist_row[0] if watchlist_row else None
        watchlist_metrics = {
            "quarterly_eps_growth": watchlist_row[1] if watchlist_row else None,
            "annual_eps_cagr": watchlist_row[2] if watchlist_row else None,
            "rs_rating": watchlist_row[3] if watchlist_row else None,
            "institutional_holders": watchlist_row[4] if watchlist_row else None,
            "institutional_change_pct": watchlist_row[5] if watchlist_row else None,
            "custom_composite_score": watchlist_row[6] if watchlist_row else None,
            "minervini_pass": bool(watchlist_row[7]) if watchlist_row and watchlist_row[7] is not None else None,
            "sector": watchlist_row[8] if watchlist_row else None,
            "industry": watchlist_row[9] if watchlist_row else None,
            "market_regime": regime_row[0] if regime_row else None,
            "market_filter_pass": bool(regime_row[1]) if regime_row and regime_row[1] is not None else None,
        }

        return {
            "ticker": ticker,
            "market": market,
            "company_name": company_name,
            "report_period": report_period,
            "financial_data_hash": financial_data_hash,
            "has_financial_data": bool(quarterly or annual),
            "financial_payload": financial_payload,
            "derived_financial_analysis": derived_financial_analysis,
            "watchlist_metrics": watchlist_metrics,
            "company_profile": None,
            "consensus_payload": self._empty_consensus_payload(market),
            "prompt_version": self._settings.ai_report_prompt_version,
            "report_type": REPORT_TYPE,
        }

    def _build_derived_financial_analysis(self, financial_payload: dict[str, Any]) -> dict[str, Any]:
        quarterly = financial_payload.get("quarterly") or []
        annual = financial_payload.get("annual") or []
        latest = quarterly[0] if quarterly else None
        previous_quarter = quarterly[1] if len(quarterly) > 1 else None
        yoy_quarter = self._find_prior_year_quarter(latest, quarterly) if latest else None
        return {
            "latest_quarter": latest,
            "prior_year_comparable_quarter": yoy_quarter,
            "previous_quarter": previous_quarter,
            "latest_quarter_growth": {
                "yoy": self._growth_block(latest, yoy_quarter),
                "qoq": self._growth_block(latest, previous_quarter),
            },
            "annual_eps_trend": [
                {"period": row.get("period"), "eps": row.get("eps")}
                for row in annual
                if row.get("eps") is not None
            ],
            "annual_revenue_trend": [
                {"period": row.get("period"), "revenue": row.get("revenue")}
                for row in annual
                if row.get("revenue") is not None
            ],
        }

    @staticmethod
    def _find_prior_year_quarter(
        latest: dict[str, Any] | None,
        quarterly: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not latest:
            return None
        period = str(latest.get("period") or "")
        if "Q" not in period:
            return None
        year_text, quarter_text = period.split("Q", 1)
        try:
            prior_period = f"{int(year_text) - 1}Q{quarter_text}"
        except ValueError:
            return None
        return next((row for row in quarterly if row.get("period") == prior_period), None)

    def _growth_block(
        self,
        current: dict[str, Any] | None,
        base: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "base_period": base.get("period") if base else None,
            "revenue": self._growth_value(current, base, "revenue"),
            "eps": self._growth_value(current, base, "eps"),
            "net_income": self._growth_value(current, base, "net_income"),
        }

    @staticmethod
    def _growth_value(
        current: dict[str, Any] | None,
        base: dict[str, Any] | None,
        key: str,
    ) -> dict[str, Any]:
        current_value = current.get(key) if current else None
        base_value = base.get(key) if base else None
        if current_value is None or base_value in (None, 0):
            return {
                "current": current_value,
                "base": base_value,
                "pct": None,
                "text": "비교 데이터 없음",
            }
        pct = (float(current_value) / float(base_value) - 1.0) * 100.0
        direction = "증가" if pct >= 0 else "감소"
        return {
            "current": current_value,
            "base": base_value,
            "pct": pct,
            "text": f"{abs(pct):.1f}% {direction}",
        }

    async def _enrich_report_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Add slower external research fields only when a fresh report is needed."""
        if context["market"] != "US":
            context["company_profile"] = {
                "available": False,
                "summary": "국내 종목의 사업 설명 데이터 소스가 연결되어 있지 않습니다.",
                "sector": context["watchlist_metrics"].get("sector"),
                "industry": context["watchlist_metrics"].get("industry"),
            }
            context["consensus_payload"] = self._empty_consensus_payload(context["market"])
            return context

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            enrichment = await loop.run_in_executor(None, self._fetch_yfinance_research, context["ticker"])
        except Exception:
            logger.warning("ai_report_research_enrichment_failed", ticker=context["ticker"], exc_info=True)
            enrichment = {
                "company_profile": {
                    "available": False,
                    "summary": "회사 개요 데이터를 가져오지 못했습니다.",
                    "sector": context["watchlist_metrics"].get("sector"),
                    "industry": context["watchlist_metrics"].get("industry"),
                },
                "consensus_payload": self._empty_consensus_payload(context["market"]),
            }

        context["company_profile"] = enrichment["company_profile"]
        context["consensus_payload"] = enrichment["consensus_payload"]
        return context

    @staticmethod
    def _empty_consensus_payload(market: str) -> dict[str, Any]:
        reason = "컨센서스 데이터 없음" if market == "US" else "국내 종목 컨센서스 데이터 소스가 연결되어 있지 않습니다."
        return {
            "available": False,
            "reason": reason,
            "info": {},
            "earnings_estimate": [],
            "revenue_estimate": [],
            "eps_trend": [],
            "eps_revisions": [],
            "growth_estimates": [],
            "recommendations_summary": [],
        }

    @classmethod
    def _fetch_yfinance_research(cls, ticker: str) -> dict[str, Any]:
        import yfinance as yf  # noqa: WPS433 — intentionally lazy and generation-only

        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info or {}
        company_profile = {
            "available": bool(info.get("longBusinessSummary")),
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "summary": info.get("longBusinessSummary") or "회사 개요 데이터 없음",
        }
        consensus_info_keys = [
            "targetMeanPrice",
            "targetMedianPrice",
            "recommendationMean",
            "recommendationKey",
            "numberOfAnalystOpinions",
            "forwardEps",
            "trailingEps",
            "revenueGrowth",
            "earningsGrowth",
        ]
        consensus_payload = {
            "available": False,
            "reason": "컨센서스 데이터 없음",
            "info": {key: cls._clean_external_value(info.get(key)) for key in consensus_info_keys},
            "earnings_estimate": cls._dataframe_records(getattr(ticker_obj, "earnings_estimate", None)),
            "revenue_estimate": cls._dataframe_records(getattr(ticker_obj, "revenue_estimate", None)),
            "eps_trend": cls._dataframe_records(getattr(ticker_obj, "eps_trend", None)),
            "eps_revisions": cls._dataframe_records(getattr(ticker_obj, "eps_revisions", None)),
            "growth_estimates": cls._dataframe_records(getattr(ticker_obj, "growth_estimates", None)),
            "recommendations_summary": cls._dataframe_records(getattr(ticker_obj, "recommendations_summary", None)),
        }
        consensus_payload["available"] = any(
            bool(consensus_payload[key])
            for key in [
                "earnings_estimate",
                "revenue_estimate",
                "eps_trend",
                "eps_revisions",
                "growth_estimates",
                "recommendations_summary",
            ]
        )
        if consensus_payload["available"]:
            consensus_payload["reason"] = "컨센서스 데이터 제공됨"
        return {"company_profile": company_profile, "consensus_payload": consensus_payload}

    @classmethod
    def _dataframe_records(cls, dataframe: Any) -> list[dict[str, Any]]:
        if dataframe is None or getattr(dataframe, "empty", True):
            return []
        records = dataframe.reset_index().to_dict(orient="records")
        return [cls._clean_external_value(record) for record in records]

    @classmethod
    def _clean_external_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._clean_external_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._clean_external_value(item) for item in value]
        if hasattr(value, "item"):
            try:
                return cls._clean_external_value(value.item())
            except Exception:
                pass
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                pass
        return value

    def _financial_row_to_dict(self, row: tuple, period_type: str) -> dict[str, Any]:
        return {
            "period": row[0],
            "period_type": period_type,
            "report_date": row[1],
            "eps": row[2],
            "revenue": row[3],
            "net_income": row[4],
            "shares_outstanding": row[5],
            "debt_to_equity": row[6],
        }

    async def _load_cached_report(
        self,
        *,
        ticker: str,
        market: str,
        report_period: str,
        financial_data_hash: str,
    ) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            """
            SELECT id, provider, model, report_json, summary_markdown,
                   verdict, canslim_fit_score, minervini_fit_score,
                   overall_fit_score, confidence, generated_at, updated_at
            FROM ai_stock_reports
            WHERE ticker = ? AND market = ? AND report_type = ?
              AND report_period = ? AND prompt_version = ?
              AND financial_data_hash = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                ticker,
                market,
                REPORT_TYPE,
                report_period,
                self._settings.ai_report_prompt_version,
                financial_data_hash,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._report_row_to_dict(row)

    def _report_row_to_dict(self, row: tuple) -> dict[str, Any]:
        return {
            "id": row[0],
            "provider": row[1],
            "model": row[2],
            "report_json": json.loads(row[3]),
            "summary_markdown": row[4],
            "verdict": row[5],
            "canslim_fit_score": row[6],
            "minervini_fit_score": row[7],
            "overall_fit_score": row[8],
            "confidence": row[9],
            "generated_at": row[10],
            "updated_at": row[11],
        }

    async def _save_report(self, context: dict[str, Any], report_json: dict[str, Any]) -> dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        summary_markdown = self._build_summary_markdown(report_json)
        report_json_text = json.dumps(report_json, ensure_ascii=False, sort_keys=True)
        input_snapshot = json.dumps(
            {
                "financial_payload": context["financial_payload"],
                "derived_financial_analysis": context["derived_financial_analysis"],
                "watchlist_metrics": context["watchlist_metrics"],
                "company_profile": context.get("company_profile"),
                "consensus_payload": context.get("consensus_payload"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        await self._db.conn.execute(
            """
            INSERT INTO ai_stock_reports (
                ticker, market, report_period, report_type, prompt_version,
                provider, model, financial_data_hash, input_snapshot,
                report_json, summary_markdown, verdict, canslim_fit_score,
                minervini_fit_score, overall_fit_score, confidence,
                generated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, market, report_period, report_type, prompt_version, financial_data_hash)
            DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                input_snapshot = excluded.input_snapshot,
                report_json = excluded.report_json,
                summary_markdown = excluded.summary_markdown,
                verdict = excluded.verdict,
                canslim_fit_score = excluded.canslim_fit_score,
                minervini_fit_score = excluded.minervini_fit_score,
                overall_fit_score = excluded.overall_fit_score,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
            """,
            (
                context["ticker"],
                context["market"],
                context["report_period"],
                REPORT_TYPE,
                context["prompt_version"],
                self._settings.ai_report_provider,
                self._settings.ai_report_model,
                context["financial_data_hash"],
                input_snapshot,
                report_json_text,
                summary_markdown,
                report_json.get("verdict"),
                report_json.get("canslim_fit_score"),
                report_json.get("minervini_fit_score"),
                report_json.get("overall_fit_score"),
                report_json.get("confidence"),
                now_iso,
                now_iso,
            ),
        )
        await self._db.conn.commit()
        cached = await self._load_cached_report(
            ticker=context["ticker"],
            market=context["market"],
            report_period=context["report_period"],
            financial_data_hash=context["financial_data_hash"],
        )
        if cached is None:
            raise StockReportError("리포트 저장 후 조회에 실패했습니다.")
        return cached

    def _build_summary_markdown(self, report_json: dict[str, Any]) -> str:
        lines = [
            f"판정: {report_json.get('verdict', 'UNKNOWN')}",
            f"종합점수: {report_json.get('overall_fit_score', 'N/A')}",
            "",
            "회사 개요:",
            str(report_json.get("company_profile", "")),
            "",
            "최신 분기 결산:",
            str((report_json.get("latest_quarter_report_summary") or {}).get("summary", "")),
            "",
            "컨센서스:",
            str((report_json.get("consensus_summary") or {}).get("summary", "")),
            "",
            str(report_json.get("summary", "")),
        ]
        strengths = report_json.get("strengths") or []
        weaknesses = report_json.get("weaknesses") or []
        red_flags = report_json.get("red_flags") or []
        if strengths:
            lines.extend(["", "강점:", *[f"- {item}" for item in strengths]])
        if weaknesses:
            lines.extend(["", "약점:", *[f"- {item}" for item in weaknesses]])
        if red_flags:
            lines.extend(["", "Red flags:", *[f"- {item}" for item in red_flags]])
        return "\n".join(lines)

    async def _call_llm(self, context: dict[str, Any]) -> dict[str, Any]:
        provider = self._settings.ai_report_provider.lower()
        if provider == "openai":
            return await self._call_openai(context)
        if provider == "anthropic":
            return await self._call_anthropic(context)
        raise StockReportError("AI 리포트 provider가 비활성화되어 있습니다.")

    async def _call_openai(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self._settings.openai_api_key:
            raise StockReportError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        prompt = self._build_prompt(context)
        payload = {
            "model": self._settings.ai_report_model,
            "messages": [
                {"role": "system", "content": "Return strict JSON only. All comments must be written in Korean."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.warning("openai_report_failed", status=resp.status, body=body[:500])
                    raise StockReportError(f"OpenAI 리포트 생성 실패: HTTP {resp.status}")
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        return self._parse_report_json(content)

    async def _call_anthropic(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self._settings.anthropic_api_key:
            raise StockReportError("ANTHROPIC_API_KEY가 설정되어 있지 않습니다.")
        prompt = self._build_prompt(context)
        payload = {
            "model": self._settings.ai_report_model,
            "max_tokens": 3000,
            "temperature": 0.2,
            "system": "Return strict JSON only. All comments must be written in Korean.",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
            async with session.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.warning("anthropic_report_failed", status=resp.status, body=body[:500])
                    raise StockReportError(f"Claude 리포트 생성 실패: HTTP {resp.status}")
        data = json.loads(body)
        content = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
        return self._parse_report_json(content)

    def _parse_report_json(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise StockReportError("LLM 응답이 JSON 형식이 아닙니다.") from exc
        self._normalize_report_json(parsed)
        self._validate_report_json(parsed)
        return parsed

    def _normalize_report_json(self, parsed: dict[str, Any]) -> None:
        """Fill harmless empty narrative fields before strict validation."""
        fallback = str(parsed.get("summary") or "제공된 재무 데이터 기준으로 판단 근거가 제한적입니다.").strip()
        for key in ["summary", "oneil_thesis", "minervini_thesis", "watchlist_reason", "risk_note", "company_profile"]:
            if not isinstance(parsed.get(key), str) or not parsed[key].strip():
                parsed[key] = fallback

    def _validate_report_json(self, parsed: dict[str, Any]) -> None:
        required_text_fields = [
            "company_profile",
            "summary",
            "oneil_thesis",
            "minervini_thesis",
            "watchlist_reason",
            "risk_note",
        ]
        required_score_fields = [
            "canslim_fit_score",
            "minervini_fit_score",
            "overall_fit_score",
            "confidence",
        ]
        required_fields = [
            "verdict",
            *required_score_fields,
            *required_text_fields,
            "latest_quarter_report_summary",
            "consensus_summary",
            "advisory_buy_opinion",
            "strengths",
            "weaknesses",
            "red_flags",
            "canslim_breakdown",
            "minervini_breakdown",
        ]
        missing = [key for key in required_fields if key not in parsed]
        if missing:
            raise StockReportError(f"LLM 응답 필수 필드 누락: {', '.join(missing)}")
        if parsed["verdict"] not in {"PASS", "WATCH", "FAIL"}:
            raise StockReportError("LLM 응답 verdict 값이 올바르지 않습니다.")
        for key in required_score_fields:
            self._validate_score(parsed[key], key)
        for key in required_text_fields:
            self._validate_text(parsed[key], key)
        for key in ["strengths", "weaknesses", "red_flags"]:
            self._validate_string_list(parsed[key], key)
        self._validate_latest_quarter_report_summary(parsed["latest_quarter_report_summary"])
        self._validate_consensus_summary(parsed["consensus_summary"])
        self._validate_advisory_buy_opinion(parsed["advisory_buy_opinion"])
        self._validate_canslim_breakdown(parsed["canslim_breakdown"])
        self._validate_minervini_breakdown(parsed["minervini_breakdown"])

    def _validate_score(self, value: Any, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise StockReportError(f"LLM 응답 {field_name} 값은 숫자여야 합니다.")
        if not 0 <= float(value) <= 100:
            raise StockReportError(f"LLM 응답 {field_name} 값은 0~100 범위여야 합니다.")

    def _validate_text(self, value: Any, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise StockReportError(f"LLM 응답 {field_name} 값은 비어있지 않은 문자열이어야 합니다.")

    def _validate_string_list(self, value: Any, field_name: str) -> None:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise StockReportError(f"LLM 응답 {field_name} 값은 문자열 배열이어야 합니다.")

    def _validate_text_dict(self, value: Any, field_name: str, required_keys: list[str]) -> None:
        if not isinstance(value, dict):
            raise StockReportError(f"LLM 응답 {field_name} 값은 객체여야 합니다.")
        for key in required_keys:
            self._validate_text(value.get(key), f"{field_name}.{key}")

    def _validate_latest_quarter_report_summary(self, value: Any) -> None:
        self._validate_text_dict(
            value,
            "latest_quarter_report_summary",
            ["period", "report_date", "summary", "revenue", "eps", "net_income", "recent_quarter_trend"],
        )
        self._validate_text_dict(value.get("yoy_growth"), "latest_quarter_report_summary.yoy_growth", ["revenue", "eps", "net_income"])
        self._validate_text_dict(value.get("qoq_growth"), "latest_quarter_report_summary.qoq_growth", ["revenue", "eps", "net_income"])

    def _validate_consensus_summary(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise StockReportError("LLM 응답 consensus_summary 값은 객체여야 합니다.")
        if not isinstance(value.get("available"), bool):
            raise StockReportError("LLM 응답 consensus_summary.available 값은 boolean이어야 합니다.")
        for key in ["summary", "next_quarter", "current_year", "next_year", "estimate_revisions", "analyst_rating"]:
            self._validate_text(value.get(key), f"consensus_summary.{key}")

    def _validate_advisory_buy_opinion(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise StockReportError("LLM 응답 advisory_buy_opinion 값은 객체여야 합니다.")
        if value.get("opinion") not in {"BUY_CANDIDATE", "WAIT", "NO_BUY"}:
            raise StockReportError("LLM 응답 advisory_buy_opinion.opinion 값이 올바르지 않습니다.")
        if not isinstance(value.get("reference_only"), bool):
            raise StockReportError("LLM 응답 advisory_buy_opinion.reference_only 값은 boolean이어야 합니다.")
        if not isinstance(value.get("not_included_in_trade_gate"), bool):
            raise StockReportError("LLM 응답 advisory_buy_opinion.not_included_in_trade_gate 값은 boolean이어야 합니다.")
        self._validate_score(value.get("confidence"), "advisory_buy_opinion.confidence")
        self._validate_text(value.get("reason"), "advisory_buy_opinion.reason")
        self._validate_string_list(value.get("conditions"), "advisory_buy_opinion.conditions")

    def _validate_canslim_breakdown(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise StockReportError("LLM 응답 canslim_breakdown 값은 객체여야 합니다.")
        for key in ["C", "A", "N", "S", "L", "I", "M"]:
            item = value.get(key)
            if not isinstance(item, dict):
                raise StockReportError(f"LLM 응답 canslim_breakdown.{key} 값은 객체여야 합니다.")
            self._validate_score(item.get("score"), f"canslim_breakdown.{key}.score")
            self._validate_text(item.get("comment"), f"canslim_breakdown.{key}.comment")

    def _validate_minervini_breakdown(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise StockReportError("LLM 응답 minervini_breakdown 값은 객체여야 합니다.")
        if not isinstance(value.get("trend_template_pass"), bool):
            raise StockReportError("LLM 응답 minervini_breakdown.trend_template_pass 값은 boolean이어야 합니다.")
        self._validate_score(value.get("score"), "minervini_breakdown.score")
        self._validate_text(value.get("comment"), "minervini_breakdown.comment")

    def _build_prompt(self, context: dict[str, Any]) -> str:
        input_data = {
            "ticker": context["ticker"],
            "company_name": context["company_name"],
            "market": context["market"],
            "report_period": context["report_period"],
            "company_profile_source": context.get("company_profile"),
            "consensus_source": context.get("consensus_payload"),
            "financials": context["financial_payload"],
            "precomputed_financial_analysis": context["derived_financial_analysis"],
            "screening_metrics_for_context_only": context["watchlist_metrics"],
        }
        return f"""
You are an equity screening analyst specializing in William O'Neil CANSLIM and Mark Minervini SEPA-style growth stock selection.

Your task is NOT to predict stock price.
Your task is to produce a concise Korean financial report and judge whether the provided company data supports inclusion in a CANSLIM/Minervini-style watchlist.

Use ONLY the data provided below.
Do not invent facts, news, products, guidance, institutional activity, or chart patterns.
If a field is missing, mark it as unknown and reduce confidence.
All narrative comments must be written in Korean.
Return strict JSON only. No markdown outside JSON.
Every string field in the returned JSON must be non-empty. If evidence is limited, write a short Korean explanation instead of an empty string.

Report requirements:
- Start from what the company does. Use company_profile_source when available. If it is unavailable, say the company description source is unavailable and infer only from company_name/sector/industry if provided.
- Always summarize the latest-quarter reported financial results in latest_quarter_report_summary.
- In latest_quarter_report_summary, calculate and explain revenue, EPS, and net income changes versus the prior-year comparable quarter when available and versus the immediately previous quarter when available.
- Use precomputed_financial_analysis.latest_quarter_growth for YoY/QoQ percentages. Do not recalculate those percentages or choose a different comparison quarter.
- For YoY, use precomputed_financial_analysis.prior_year_comparable_quarter as the comparison period. If it is missing, write "비교 데이터 없음".
- For QoQ, use precomputed_financial_analysis.previous_quarter as the comparison period. If it is missing, write "비교 데이터 없음".
- Always summarize consensus in consensus_summary. If consensus_source.available is false, set available=false and clearly write that consensus data is unavailable; never fabricate estimates.
- advisory_buy_opinion is a reference-only human-readable opinion. It must never be used as the automated trade gate.

Evaluation principles:
- The upstream screener has already passed CANSLIM/Minervini numeric filters before this report is generated.
- Use the financial data to decide whether that screened candidate is tradable now, not whether it deserves a perfect research report.
- PASS means the provided data supports automated trading eligibility after the first-stage filters.
- WATCH means the company is promising but has a core growth-quality problem that should block automated trading for now.
- FAIL means the provided data contradicts CANSLIM/Minervini suitability.
- Prioritize current-quarter EPS growth, annual EPS growth, revenue growth when available, RS rating, composite score, and Minervini pass.
- CANSLIM PASS requires sustained growth from a positive earnings base. A loss-to-profit turnaround is not enough for PASS.
- Treat prior-year loss to current-year profit, recent annual loss, or EPS growth caused mainly by moving from negative to positive as WATCH unless there are multiple consecutive profitable years and recent quarters confirm durable growth.
- Prefer companies with at least 3 consecutive profitable annual EPS records and positive year-over-year quarterly EPS growth from a positive prior-year comparable period.
- If the most recent annual EPS is positive but the immediately preceding annual EPS was negative, classify as WATCH for turnaround confirmation, not PASS.
- Missing non-core fields such as institutional ownership, product/news narrative, sector context, or detailed market leadership should lower confidence, but must not by itself block PASS.
- Missing revenue should not by itself block PASS when EPS growth, RS rating, and Minervini/composite context are strong. This is especially important for KR names where revenue fields can be unavailable in the stored DART data.
- Market regime YELLOW or an unknown market regime should be mentioned as a risk, but must not by itself block PASS.
- Use WATCH/FAIL for real blocking issues: recent EPS contraction versus the prior-year period, weak or decelerating annual EPS trend, severe debt risk, repeated losses, large unexplained volatility, or insufficient core EPS history.
- Red flags should be explicit, but do not list mere absence of institutional/product/sector data as a red flag unless it is the primary available evidence.
- Consensus is supporting evidence only. Positive revisions can strengthen confidence; weak, missing, or stale consensus should not override strong reported earnings by itself.
- The advisory buy opinion must consider reported growth, consensus, market regime, and the fact that actual entry still requires the system's price/signal/risk rules.

Verdict policy:
- Choose PASS only when the candidate has at least 3 consecutive profitable annual EPS records, strong current/annual EPS growth, and no clear core financial contradiction, especially if rs_rating >= 80, minervini_pass is true, or custom_composite_score is strong.
- Do not choose PASS for pure turnarounds. Require evidence of sustained positive earnings growth, not merely recovery from losses.
- Choose WATCH when growth exists but the core evidence is mixed, unstable, very incomplete, or materially risky.
- Choose FAIL when core earnings/revenue evidence is weak or contradicts growth-stock suitability.

Advisory buy opinion policy:
- opinion must be one of BUY_CANDIDATE, WAIT, or NO_BUY.
- BUY_CANDIDATE means the report supports a human reference view that this is a buy candidate if, and only if, the separate system entry signal and risk checks trigger.
- WAIT means the stock may remain watchable, but current reported/consensus/market evidence argues for patience.
- NO_BUY means even as a reference opinion the setup is unattractive.
- If verdict is WATCH or FAIL, advisory opinion should normally be WAIT or NO_BUY unless you explain a narrow exception.
- Always set reference_only=true and not_included_in_trade_gate=true.

Scoring:
- 90-100: exceptional CANSLIM/Minervini fit
- 80-89: strong fit
- 70-79: tradable PASS candidate with caveats when core growth is strong
- 65-69: acceptable WATCH candidate with caveats
- 50-64: weak/uncertain fit
- below 50: not suitable

Input data:
{json.dumps(input_data, ensure_ascii=False, indent=2)}

Return this exact JSON schema:
{{
  "verdict": "PASS | WATCH | FAIL",
  "company_profile": "한국어 2-3문장 회사/사업 설명",
  "latest_quarter_report_summary": {{
    "period": "최신 분기",
    "report_date": "결산 기준일 또는 데이터 없음",
    "summary": "최신 분기 결산보고서 핵심 요약",
    "revenue": "매출 수치 또는 데이터 없음",
    "eps": "EPS 수치 또는 데이터 없음",
    "net_income": "순이익 수치 또는 데이터 없음",
    "yoy_growth": {{
      "revenue": "전년동기 대비 매출 변화 또는 비교 데이터 없음",
      "eps": "전년동기 대비 EPS 변화 또는 비교 데이터 없음",
      "net_income": "전년동기 대비 순이익 변화 또는 비교 데이터 없음"
    }},
    "qoq_growth": {{
      "revenue": "직전분기 대비 매출 변화 또는 비교 데이터 없음",
      "eps": "직전분기 대비 EPS 변화 또는 비교 데이터 없음",
      "net_income": "직전분기 대비 순이익 변화 또는 비교 데이터 없음"
    }},
    "recent_quarter_trend": "최근 분기 흐름 요약"
  }},
  "consensus_summary": {{
    "available": boolean,
    "summary": "컨센서스 핵심 요약 또는 데이터 없음",
    "next_quarter": "다음 분기 EPS/매출 컨센서스 요약 또는 데이터 없음",
    "current_year": "현재 연도 EPS/매출 컨센서스 요약 또는 데이터 없음",
    "next_year": "다음 연도 EPS/매출 컨센서스 요약 또는 데이터 없음",
    "estimate_revisions": "추정치 상향/하향 리비전 요약 또는 데이터 없음",
    "analyst_rating": "애널리스트 투자의견 요약 또는 데이터 없음"
  }},
  "advisory_buy_opinion": {{
    "reference_only": true,
    "opinion": "BUY_CANDIDATE | WAIT | NO_BUY",
    "confidence": number,
    "reason": "한국어 참고용 매수 의견 설명",
    "conditions": ["한국어 조건"],
    "not_included_in_trade_gate": true
  }},
  "canslim_fit_score": number,
  "minervini_fit_score": number,
  "overall_fit_score": number,
  "confidence": number,
  "summary": "한국어 2-4문장 요약",
  "oneil_thesis": "한국어 설명",
  "minervini_thesis": "한국어 설명",
  "watchlist_reason": "한국어 설명",
  "risk_note": "한국어 설명",
  "strengths": ["한국어 항목"],
  "weaknesses": ["한국어 항목"],
  "red_flags": ["한국어 항목"],
  "canslim_breakdown": {{
    "C": {{"score": number, "comment": "한국어 코멘트"}},
    "A": {{"score": number, "comment": "한국어 코멘트"}},
    "N": {{"score": number, "comment": "한국어 코멘트"}},
    "S": {{"score": number, "comment": "한국어 코멘트"}},
    "L": {{"score": number, "comment": "한국어 코멘트"}},
    "I": {{"score": number, "comment": "한국어 코멘트"}},
    "M": {{"score": number, "comment": "한국어 코멘트"}}
  }},
  "minervini_breakdown": {{
    "trend_template_pass": boolean,
    "score": number,
    "comment": "한국어 코멘트"
  }}
}}
""".strip()
