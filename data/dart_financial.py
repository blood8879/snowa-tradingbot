"""
DART OpenAPI financial data fetcher.

Fetches quarterly and annual net income from DART (전자공시시스템)
to support CANSLIM C/A filters for Korean stocks.

Data source: https://opendart.fss.or.kr/
API: fnlttSinglAcnt (단일회사 주요계정)

Usage:
    dart = DartFinancialFetcher(api_key="...", cache_dir="data")
    await dart.load_corp_codes()
    await dart.bulk_fetch_and_store(stock_codes, db)
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import requests
import structlog

from core.database import Database

logger = structlog.get_logger(__name__)

# ============================================================
# Constants
# ============================================================

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_FINSTATE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
_COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"

# Rate limit: DART allows ~100 requests/min
_RATE_LIMIT_CALLS_PER_SEC = 1.5  # ~90/min, safe margin
_RATE_LIMIT_DELAY = 1.0 / _RATE_LIMIT_CALLS_PER_SEC

# Report codes
_REPRT_Q1 = "11013"   # 1분기보고서
_REPRT_H1 = "11012"   # 반기보고서
_REPRT_Q3 = "11014"   # 3분기보고서
_REPRT_ANNUAL = "11011"  # 사업보고서

# Net income scale: store in 억원 (1e8) for readable numbers
_SCALE = 1e8


# ============================================================
# DART Financial Fetcher
# ============================================================

class DartFinancialFetcher:
    """DART OpenAPI를 통한 한국 주식 재무 데이터 수집."""

    def __init__(self, api_key: str, cache_dir: str = "data") -> None:
        self._api_key = api_key
        self._cache_dir = Path(cache_dir)
        self._corp_codes: dict[str, str] = {}  # stock_code → corp_code
        self._corp_names: dict[str, str] = {}  # stock_code → corp_name
        self._loaded = False
        self._last_call_time: float = 0.0

    # ── Corp Code Mapping ─────────────────────────────────────

    async def load_corp_codes(self) -> int:
        """Download and parse corp_code mapping (stock_code → corp_code).

        Caches the mapping as a CSV file for 7 days.

        Returns:
            Number of listed companies with stock codes.
        """
        cache_path = self._cache_dir / "dart_corp_codes.csv"

        # Try cache first (< 7 days old)
        if cache_path.exists():
            age_days = (time.time() - cache_path.stat().st_mtime) / 86400
            if age_days < 7:
                self._load_corp_code_cache(cache_path)
                if self._corp_codes:
                    self._loaded = True
                    logger.info(
                        "dart_corp_codes_loaded",
                        count=len(self._corp_codes),
                        source="cache",
                    )
                    return len(self._corp_codes)

        # Download fresh from DART
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._download_corp_codes, cache_path)
        self._loaded = True

        logger.info(
            "dart_corp_codes_loaded",
            count=len(self._corp_codes),
            source="api",
        )
        return len(self._corp_codes)

    def _download_corp_codes(self, cache_path: Path) -> None:
        """Synchronous: download corp code ZIP, parse XML, save cache."""
        resp = requests.get(
            _CORP_CODE_URL,
            params={"crtfc_key": self._api_key},
            timeout=30,
        )
        resp.raise_for_status()

        # ZIP contains CORPCODE.xml
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_name = zf.namelist()[0]
            xml_data = zf.read(xml_name)

        root = ET.fromstring(xml_data)
        self._corp_codes.clear()
        self._corp_names.clear()

        rows = [["stock_code", "corp_code", "corp_name"]]
        for corp in root.findall("list"):
            stock_code = (corp.findtext("stock_code") or "").strip()
            corp_code = (corp.findtext("corp_code") or "").strip()
            corp_name = (corp.findtext("corp_name") or "").strip()

            if stock_code and corp_code:
                self._corp_codes[stock_code] = corp_code
                self._corp_names[stock_code] = corp_name
                rows.append([stock_code, corp_code, corp_name])

        # Save cache
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)

    def _load_corp_code_cache(self, cache_path: Path) -> None:
        """Load corp codes from CSV cache."""
        self._corp_codes.clear()
        self._corp_names.clear()
        with cache_path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                stock_code = (row.get("stock_code") or "").strip()
                corp_code = (row.get("corp_code") or "").strip()
                corp_name = (row.get("corp_name") or "").strip()
                if stock_code and corp_code:
                    self._corp_codes[stock_code] = corp_code
                    self._corp_names[stock_code] = corp_name

    async def fetch_company_profile(self, stock_code: str) -> dict | None:
        """Fetch DART company overview metadata for a listed Korean company."""
        if not self._loaded:
            await self.load_corp_codes()

        corp_code = self._corp_codes.get(stock_code)
        if not corp_code:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._fetch_company_profile_sync,
            stock_code,
            corp_code,
        )

    def _fetch_company_profile_sync(self, stock_code: str, corp_code: str) -> dict | None:
        self._rate_limit()
        try:
            resp = requests.get(
                _COMPANY_URL,
                params={"crtfc_key": self._api_key, "corp_code": corp_code},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.debug("dart_company_profile_fetch_failed", stock_code=stock_code, exc_info=True)
            return None

        if data.get("status") != "000":
            logger.debug(
                "dart_company_profile_unavailable",
                stock_code=stock_code,
                status=data.get("status"),
                message=data.get("message"),
            )
            return None

        return {
            "corp_code": corp_code,
            "corp_name": data.get("corp_name") or self._corp_names.get(stock_code),
            "corp_name_eng": data.get("corp_name_eng"),
            "stock_name": data.get("stock_name"),
            "stock_code": data.get("stock_code") or stock_code,
            "ceo_nm": data.get("ceo_nm"),
            "corp_cls": data.get("corp_cls"),
            "jurir_no": data.get("jurir_no"),
            "bizr_no": data.get("bizr_no"),
            "address": data.get("adres"),
            "homepage": data.get("hm_url"),
            "ir_homepage": data.get("ir_url"),
            "phone": data.get("phn_no"),
            "fax": data.get("fax_no"),
            "industry_code": data.get("induty_code"),
            "established_date": data.get("est_dt"),
            "fiscal_year_end_month": data.get("acc_mt"),
        }

    # ── Financial Data Fetching ───────────────────────────────

    async def fetch_and_store(self, stock_code: str, db: Database) -> int:
        """Fetch quarterly + annual earnings from DART and store in DB.

        Args:
            stock_code: 6-digit Korean stock code (e.g., "005930").
            db: Database instance.

        Returns:
            Number of new records inserted.
        """
        corp_code = self._corp_codes.get(stock_code)
        if not corp_code:
            return 0

        loop = asyncio.get_event_loop()
        records: list[dict] = []

        # ── Quarterly: fetch latest available report ──────────
        quarterly_records = await loop.run_in_executor(
            None, self._fetch_quarterly, stock_code, corp_code
        )
        records.extend(quarterly_records)

        # ── Q4 derivation: Annual - (Q1+Q2+Q3) ───────────────
        q4_records = await self._derive_q4(stock_code, corp_code, db)
        records.extend(q4_records)

        # ── Annual: fetch 2 recent annual reports (≥3 years) ──
        annual_records = await loop.run_in_executor(
            None, self._fetch_annual, stock_code, corp_code
        )
        records.extend(annual_records)

        if not records:
            return 0

        return await self._store_records(records, db)

    async def bulk_fetch_and_store(
        self,
        stock_codes: list[str],
        db: Database,
    ) -> int:
        """Fetch DART fundamentals for multiple stocks with rate limiting.

        Args:
            stock_codes: List of 6-digit stock codes.
            db: Database instance.

        Returns:
            Total new records inserted.
        """
        if not self._loaded:
            await self.load_corp_codes()

        total_inserted = 0
        total_stocks = len(stock_codes)
        fetched_count = 0

        for idx, code in enumerate(stock_codes, start=1):
            try:
                inserted = await self.fetch_and_store(code, db)
                total_inserted += inserted
                if inserted > 0:
                    fetched_count += 1
            except Exception:
                logger.debug("dart_fetch_failed", stock_code=code, exc_info=True)

            if idx % 50 == 0:
                logger.info(
                    "dart_bulk_progress",
                    completed=idx,
                    total=total_stocks,
                    fetched=fetched_count,
                    records=total_inserted,
                )

        logger.info(
            "dart_bulk_complete",
            total_stocks=total_stocks,
            fetched=fetched_count,
            total_records=total_inserted,
        )
        return total_inserted

    # ── Internal: Quarterly Fetch ─────────────────────────────

    def _fetch_quarterly(self, stock_code: str, corp_code: str) -> list[dict]:
        """Fetch ALL available quarterly reports to build complete history.

        Fetches Q1, H1(Q2), Q3 reports for prior year (always available)
        and current year (based on report filing deadlines).
        Each report returns current quarter + same quarter prior year (frmtrm).

        All 3 reports for a year are needed for Q4 derivation:
            Q4 = Annual - Q1 - Q2 - Q3

        Report filing deadlines:
            Q1 (11013): due May 15  → available from June
            H1 (11012): due Aug 14  → available from September
            Q3 (11014): due Nov 14  → available from December

        Returns list of fundamental records.
        """
        now = datetime.now()
        current_year = now.year
        all_records: list[dict] = []

        # Prior year: all 3 reports should be available
        prev = current_year - 1
        reports: list[tuple[int, str, str]] = [
            (prev, _REPRT_Q1, "Q1"),
            (prev, _REPRT_H1, "Q2"),
            (prev, _REPRT_Q3, "Q3"),
        ]

        # Current year: only add reports past their filing deadlines
        if now.month >= 6:
            reports.append((current_year, _REPRT_Q1, "Q1"))
        if now.month >= 9:
            reports.append((current_year, _REPRT_H1, "Q2"))
        if now.month >= 12:
            reports.append((current_year, _REPRT_Q3, "Q3"))

        for year, reprt_code, quarter_label in reports:
            records = self._fetch_single_report(
                stock_code, corp_code, year, reprt_code, quarter_label,
            )
            all_records.extend(records)

        return all_records

    def _fetch_single_report(
        self,
        stock_code: str,
        corp_code: str,
        year: int,
        reprt_code: str,
        quarter_label: str,
    ) -> list[dict]:
        """Fetch one quarterly report and extract net income records.

        Returns up to 2 records: current quarter + same quarter prior year.
        """
        self._rate_limit()

        try:
            resp = requests.get(
                _FINSTATE_URL,
                params={
                    "crtfc_key": self._api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": reprt_code,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        if data.get("status") != "000":
            return []

        # Find consolidated (CFS) net income on income statement (IS)
        records = []
        for item in data.get("list", []):
            if (
                item.get("fs_div") == "CFS"
                and item.get("sj_div") == "IS"
                and "당기순이익" in item.get("account_nm", "")
            ):
                # Current period
                thstrm = self._parse_amount(item.get("thstrm_amount", ""))
                frmtrm = self._parse_amount(item.get("frmtrm_amount", ""))

                quarter_num = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(quarter_label, 0)

                if thstrm is not None:
                    period = f"{year}Q{quarter_num}"
                    records.append({
                        "ticker": stock_code,
                        "report_date": f"{year}-{quarter_num * 3:02d}-28",
                        "period": period,
                        "period_type": "quarterly",
                        "eps": thstrm / _SCALE,
                        "net_income": thstrm,
                    })

                if frmtrm is not None:
                    prior_year = year - 1
                    period = f"{prior_year}Q{quarter_num}"
                    records.append({
                        "ticker": stock_code,
                        "report_date": f"{prior_year}-{quarter_num * 3:02d}-28",
                        "period": period,
                        "period_type": "quarterly",
                        "eps": frmtrm / _SCALE,
                        "net_income": frmtrm,
                    })

                break  # Only take first CFS entry

        return records

    # ── Internal: Q4 Derivation ──────────────────────────────

    async def _derive_q4(
        self, stock_code: str, corp_code: str, db: Database
    ) -> list[dict]:
        """Derive Q4 net income from annual report minus Q1+Q2+Q3.

        Tries the 2 most recent fiscal years (year-1, year-2) so that
        stocks screened for the first time in any month get complete data.

        Q4 = Annual - (Q1 + Q2 + Q3).  Requires ALL THREE quarters
        (Q1, Q2, Q3) to be present before deriving.  Always recalculates
        to handle the case where Q1/Q2/Q3 data was updated after initial
        Q4 derivation.

        Annual reports (사업보고서) are due by March 31 of the following year,
        but many large companies file in March.

        Returns list of Q4 fundamental record dicts (0-2 records).
        """
        now = datetime.now()
        loop = asyncio.get_event_loop()
        results: list[dict] = []

        for target_year in [now.year - 1, now.year - 2]:
            # Require ALL 3 quarters (Q1, Q2, Q3) to be present individually
            cursor = await db.conn.execute(
                """
                SELECT period, net_income
                FROM fundamentals
                WHERE ticker = ? AND period_type = 'quarterly'
                  AND period IN (?, ?, ?)
                  AND net_income IS NOT NULL
                """,
                (
                    stock_code,
                    f"{target_year}Q1",
                    f"{target_year}Q2",
                    f"{target_year}Q3",
                ),
            )
            rows = await cursor.fetchall()

            if len(rows) < 3:
                logger.debug(
                    "dart_q4_missing_quarters",
                    stock_code=stock_code,
                    year=target_year,
                    found=len(rows),
                )
                continue

            q123_sum = sum(r[1] for r in rows)

            # Fetch annual report from DART
            annual_net_income = await loop.run_in_executor(
                None, self._fetch_annual_net_income, corp_code, target_year
            )
            if annual_net_income is None:
                continue  # Annual report not yet filed

            q4_net_income = annual_net_income - q123_sum
            q4_eps = q4_net_income / _SCALE

            logger.info(
                "dart_q4_derived",
                stock_code=stock_code,
                year=target_year,
                annual=annual_net_income,
                q123=q123_sum,
                q4=q4_net_income,
            )

            results.append({
                "ticker": stock_code,
                "report_date": f"{target_year}-12-28",
                "period": f"{target_year}Q4",
                "period_type": "quarterly",
                "eps": q4_eps,
                "net_income": q4_net_income,
            })

        return results

    def _fetch_annual_net_income(self, corp_code: str, year: int) -> float | None:
        """Fetch annual net income (당기순이익) from 사업보고서.

        Returns raw net income amount (not scaled), or None if unavailable.
        """
        self._rate_limit()

        try:
            resp = requests.get(
                _FINSTATE_URL,
                params={
                    "crtfc_key": self._api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": _REPRT_ANNUAL,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        if data.get("status") != "000":
            return None

        for item in data.get("list", []):
            if (
                item.get("fs_div") == "CFS"
                and item.get("sj_div") == "IS"
                and "당기순이익" in item.get("account_nm", "")
            ):
                return self._parse_amount(item.get("thstrm_amount", ""))

        return None

    # ── Internal: Annual Fetch ────────────────────────────────

    def _fetch_annual(self, stock_code: str, corp_code: str) -> list[dict]:
        """Fetch annual net income from 2 annual reports (≥3 years of data).

        Returns list of fundamental records with period_type='annual'.
        """
        now = datetime.now()
        records = []
        seen_periods: set[str] = set()

        # Try recent annual reports: each gives current year + prior year
        # Start from most recent likely available, then go back for CAGR depth
        # Annual reports are due by March 31, but many large companies file
        # in March.  Always try year-1 first (DART returns error if not filed).
        latest_annual = now.year - 1
        for year in [latest_annual, latest_annual - 2]:
            self._rate_limit()

            try:
                resp = requests.get(
                    _FINSTATE_URL,
                    params={
                        "crtfc_key": self._api_key,
                        "corp_code": corp_code,
                        "bsns_year": str(year),
                        "reprt_code": _REPRT_ANNUAL,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue

            if data.get("status") != "000":
                continue

            for item in data.get("list", []):
                if (
                    item.get("fs_div") == "CFS"
                    and item.get("sj_div") == "IS"
                    and "당기순이익" in item.get("account_nm", "")
                ):
                    thstrm = self._parse_amount(item.get("thstrm_amount", ""))
                    frmtrm = self._parse_amount(item.get("frmtrm_amount", ""))

                    if thstrm is not None:
                        period = f"FY{year}"
                        if period not in seen_periods:
                            seen_periods.add(period)
                            records.append({
                                "ticker": stock_code,
                                "report_date": f"{year}-12-31",
                                "period": period,
                                "period_type": "annual",
                                "eps": thstrm / _SCALE,
                                "net_income": thstrm,
                            })

                    if frmtrm is not None:
                        prior_year = year - 1
                        period = f"FY{prior_year}"
                        if period not in seen_periods:
                            seen_periods.add(period)
                            records.append({
                                "ticker": stock_code,
                                "report_date": f"{prior_year}-12-31",
                                "period": period,
                                "period_type": "annual",
                                "eps": frmtrm / _SCALE,
                                "net_income": frmtrm,
                            })

                    break  # Only first CFS entry

        return records

    # ── Internal: DB Storage ──────────────────────────────────

    async def _store_records(self, records: list[dict], db: Database) -> int:
        """Store DART financial records in the fundamentals table.

        Uses INSERT OR REPLACE to update existing records.
        """
        inserted = 0
        for rec in records:
            cursor = await db.conn.execute(
                """
                INSERT OR REPLACE INTO fundamentals
                    (ticker, report_date, period, period_type,
                     eps, revenue, net_income, shares_outstanding,
                     debt_to_equity, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, NULL, datetime('now'))
                """,
                (
                    rec["ticker"],
                    rec["report_date"],
                    rec["period"],
                    rec["period_type"],
                    rec["eps"],
                    rec["net_income"],
                ),
            )
            inserted += cursor.rowcount

        await db.conn.commit()
        return inserted

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_amount(amount_str: str) -> float | None:
        """Parse DART amount string (e.g., '12,225,747,000,000') to float."""
        if not amount_str or amount_str.strip() == "":
            return None
        try:
            return float(amount_str.replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < _RATE_LIMIT_DELAY:
            time.sleep(_RATE_LIMIT_DELAY - elapsed)
        self._last_call_time = time.monotonic()
