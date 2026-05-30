"""AI stock report generation and caching.

Reports are keyed by ticker, market, latest financial period, prompt version,
and a hash of financial rows. The LLM is only used when that cache key is
missing or an explicit refresh is requested.
"""
from __future__ import annotations

import hashlib
import json
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
            "watchlist_metrics": watchlist_metrics,
            "prompt_version": self._settings.ai_report_prompt_version,
            "report_type": REPORT_TYPE,
        }

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
                "watchlist_metrics": context["watchlist_metrics"],
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
            "max_tokens": 1800,
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
        self._validate_report_json(parsed)
        return parsed

    def _validate_report_json(self, parsed: dict[str, Any]) -> None:
        required_text_fields = ["summary", "oneil_thesis", "minervini_thesis", "watchlist_reason", "risk_note"]
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
            "financials": context["financial_payload"],
            "screening_metrics_for_context_only": context["watchlist_metrics"],
        }
        return f"""
You are an equity screening analyst specializing in William O'Neil CANSLIM and Mark Minervini SEPA-style growth stock selection.

Your task is NOT to predict stock price.
Your task is to judge whether the provided company financial data supports inclusion in a CANSLIM/Minervini-style watchlist.

Use ONLY the data provided below.
Do not invent facts, news, products, guidance, institutional activity, or chart patterns.
If a field is missing, mark it as unknown and reduce confidence.
All narrative comments must be written in Korean.
Return strict JSON only. No markdown outside JSON.

Important cache rule: this report is based on financial data only. Screening metrics are provided only as context; do not claim they are refreshed by this report.

Evaluation principles:
- CANSLIM fit should prioritize genuine earnings growth quality, acceleration, leadership context, institutional context, and market direction.
- Minervini fit should acknowledge trend-template context when provided, but the main written assessment must be conservative when financial data is incomplete.
- A company may pass numeric filters but still receive WATCH or FAIL if the quality of growth is weak, inconsistent, or unsupported.
- Red flags should be explicit and conservative.

Scoring:
- 90-100: exceptional CANSLIM/Minervini fit
- 80-89: strong fit
- 65-79: acceptable watchlist candidate with caveats
- 50-64: weak/uncertain fit
- below 50: not suitable

Input data:
{json.dumps(input_data, ensure_ascii=False, indent=2)}

Return this exact JSON schema:
{{
  "verdict": "PASS | WATCH | FAIL",
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
