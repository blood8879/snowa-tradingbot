#!/usr/bin/env python3
"""
yfinance 벌크 수집 Production Code Examples

CANSLIM x Turtle Trading Bot을 위한 실전 코드 패턴
8000종목 재무/가격 데이터 수집
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import pickle
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import requests.exceptions

# ============================================================================
# 설정
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limiting 설정
BATCH_SIZE = 100              # 가격 데이터 배치 크기
DELAY_BETWEEN_BATCHES = 2.0   # 배치 간 대기 (초)
DELAY_PER_TICKER = 0.5        # 재무 데이터 수집 간 대기 (초)
MAX_RETRIES = 3               # 최대 재시도 횟수

# 데이터 저장 경로
DATA_DIR = Path("data/cache")
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 1. 종목 리스트 가져오기
# ============================================================================

def get_ticker_list_nasdaq_ftp() -> List[str]:
    """
    NASDAQ FTP 서버에서 NYSE + NASDAQ 종목 리스트 가져오기
    
    Returns:
        List of ticker symbols (~8000개)
    """
    import ftplib
    import io
    
    logger.info("Downloading ticker list from NASDAQ FTP...")
    
    ftp = ftplib.FTP("ftp.nasdaqtrader.com")
    ftp.login()
    ftp.cwd("SymbolDirectory")
    
    # NASDAQ 종목
    nasdaq_buffer = io.BytesIO()
    ftp.retrbinary("RETR nasdaqlisted.txt", nasdaq_buffer.write)
    nasdaq_buffer.seek(0)
    nasdaq_df = pd.read_csv(nasdaq_buffer, sep='|')
    nasdaq_df = nasdaq_df[nasdaq_df['Test Issue'] == 'N']
    nasdaq_tickers = nasdaq_df['Symbol'].tolist()
    
    # NYSE, AMEX 종목
    other_buffer = io.BytesIO()
    ftp.retrbinary("RETR otherlisted.txt", other_buffer.write)
    other_buffer.seek(0)
    other_df = pd.read_csv(other_buffer, sep='|')
    other_df = other_df[other_df['Test Issue'] == 'N']
    other_tickers = other_df['ACT Symbol'].tolist()
    
    ftp.quit()
    
    all_tickers = nasdaq_tickers + other_tickers
    
    # 클린업: 잘못된 심볼 제거
    all_tickers = [t for t in all_tickers if isinstance(t, str) and len(t) <= 5]
    
    logger.info(f"Found {len(all_tickers)} valid tickers")
    return all_tickers


def get_ticker_list_simple() -> List[str]:
    """
    간단한 방법: get-all-tickers 라이브러리 사용
    
    pip install get-all-tickers
    
    Returns:
        List of ticker symbols
    """
    try:
        from get_all_tickers import get_tickers
        tickers = get_tickers(NYSE=True, NASDAQ=True)
        logger.info(f"Found {len(tickers)} tickers via get-all-tickers")
        return tickers
    except ImportError:
        logger.error("get-all-tickers not installed. Run: pip install get-all-tickers")
        return []


# ============================================================================
# 2. 가격 데이터 벌크 다운로드
# ============================================================================

def download_price_data_bulk(
    tickers: List[str],
    period: str = "300d",
    interval: str = "1d",
    batch_size: int = BATCH_SIZE,
    delay_between_batches: float = DELAY_BETWEEN_BATCHES,
    max_retries: int = MAX_RETRIES
) -> pd.DataFrame:
    """
    여러 종목의 가격 데이터를 배치로 다운로드
    
    Args:
        tickers: 종목 리스트
        period: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
        interval: "1d" (일봉), "1wk" (주봉), "1mo" (월봉)
        batch_size: 한 번에 다운로드할 종목 수
        delay_between_batches: 배치 간 대기 시간
        max_retries: 재시도 횟수
    
    Returns:
        MultiIndex DataFrame with columns (OHLCV, Ticker)
    """
    all_data = []
    failed_tickers = []
    total_batches = (len(tickers) - 1) // batch_size + 1
    
    logger.info(f"Starting bulk download: {len(tickers)} tickers in {total_batches} batches")
    
    for batch_idx in range(0, len(tickers), batch_size):
        batch = tickers[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1
        
        logger.info(f"Processing batch {batch_num}/{total_batches}: {len(batch)} tickers")
        
        retries = 0
        success = False
        
        while retries < max_retries and not success:
            try:
                data = yf.download(
                    tickers=batch,
                    period=period,
                    interval=interval,
                    group_by='ticker',
                    auto_adjust=True,  # 배당/분할 조정
                    threads=True,      # 병렬 다운로드
                    progress=False
                )
                
                if not data.empty:
                    all_data.append(data)
                    success = True
                    logger.info(f"  ✓ Batch {batch_num} downloaded successfully")
                else:
                    logger.warning(f"  Empty data for batch {batch_num}, retrying...")
                    retries += 1
                    
            except requests.exceptions.HTTPError as e:
                if e.response.status_code in [429, 403, 999]:
                    wait_time = delay_between_batches * (2 ** retries)
                    logger.warning(f"  Rate limited (HTTP {e.response.status_code}). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    retries += 1
                else:
                    logger.error(f"  HTTP Error {e.response.status_code}: {e}")
                    break
                    
            except Exception as e:
                logger.error(f"  Error downloading batch {batch_num}: {e}")
                retries += 1
                time.sleep(delay_between_batches * retries)
        
        if not success:
            logger.error(f"  ✗ Failed to download batch {batch_num} after {max_retries} retries")
            failed_tickers.extend(batch)
        
        # Rate limiting
        if batch_idx + batch_size < len(tickers):
            time.sleep(delay_between_batches)
    
    # 결과 병합
    if all_data:
        result = pd.concat(all_data, axis=1)
        logger.info(f"\n=== BULK DOWNLOAD SUMMARY ===")
        logger.info(f"Total tickers: {len(tickers)}")
        logger.info(f"Successful: {len(tickers) - len(failed_tickers)}")
        logger.info(f"Failed: {len(failed_tickers)}")
        
        if failed_tickers:
            logger.warning(f"Failed tickers: {failed_tickers[:20]}...")
            # 실패한 티커 저장
            with open(DATA_DIR / "failed_tickers_price.txt", "w") as f:
                f.write("\n".join(failed_tickers))
        
        return result
    else:
        raise ValueError("No data downloaded successfully")


# ============================================================================
# 3. 재무 데이터 벌크 수집
# ============================================================================

def download_fundamental_data_bulk(
    tickers: List[str],
    delay_per_ticker: float = DELAY_PER_TICKER,
    max_retries: int = MAX_RETRIES,
    checkpoint_every: int = 500
) -> Dict[str, Dict]:
    """
    개별 종목의 재무 데이터를 순차적으로 수집
    
    WARNING: 8000종목 * 0.5초 = 약 1시간 소요
    
    Args:
        tickers: 종목 리스트
        delay_per_ticker: 종목당 대기 시간
        max_retries: 재시도 횟수
        checkpoint_every: N개마다 체크포인트 저장
    
    Returns:
        {ticker: {'info': {...}, 'quarterly_earnings': DataFrame, ...}}
    """
    results = {}
    failed_tickers = []
    start_time = time.time()
    
    logger.info(f"Starting fundamental data collection for {len(tickers)} tickers")
    logger.info(f"Estimated time: {len(tickers) * delay_per_ticker / 60:.1f} minutes")
    
    for idx, symbol in enumerate(tickers):
        # 진행상황 로깅
        if idx % 100 == 0 and idx > 0:
            elapsed = time.time() - start_time
            eta = (elapsed / idx) * (len(tickers) - idx)
            logger.info(f"Progress: {idx}/{len(tickers)} ({idx/len(tickers)*100:.1f}%) | "
                       f"ETA: {eta/60:.1f}min | Success: {len(results)} | Failed: {len(failed_tickers)}")
        
        retries = 0
        success = False
        
        while retries < max_retries and not success:
            try:
                ticker = yf.Ticker(symbol)
                
                # CANSLIM 지표 계산에 필요한 데이터만 수집
                data = {
                    'info': ticker.info,
                    'quarterly_earnings': ticker.quarterly_earnings,
                    'quarterly_income_stmt': ticker.quarterly_income_stmt,
                    'quarterly_balance_sheet': ticker.quarterly_balance_sheet,
                    'institutional_holders': ticker.institutional_holders,
                }
                
                # 데이터 유효성 검증
                if data['info'] and len(data['info']) > 5:
                    results[symbol] = data
                    success = True
                else:
                    logger.warning(f"  {symbol}: Insufficient data")
                    retries += 1
                    
            except requests.exceptions.HTTPError as e:
                if e.response.status_code in [429, 403, 999]:
                    wait_time = delay_per_ticker * (2 ** retries)
                    logger.warning(f"  {symbol}: Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    retries += 1
                else:
                    logger.error(f"  {symbol}: HTTP {e.response.status_code}")
                    break
                    
            except Exception as e:
                logger.error(f"  {symbol}: {type(e).__name__} - {e}")
                retries += 1
                time.sleep(delay_per_ticker * retries)
        
        if not success:
            failed_tickers.append(symbol)
        
        # Rate limiting
        time.sleep(delay_per_ticker)
        
        # 체크포인트 저장 (중간에 중단되어도 복구 가능)
        if (idx + 1) % checkpoint_every == 0:
            checkpoint_path = DATA_DIR / f"checkpoint_fundamental_{idx+1}.pkl"
            with open(checkpoint_path, "wb") as f:
                pickle.dump(results, f)
            logger.info(f"  Checkpoint saved: {checkpoint_path}")
    
    # 최종 요약
    elapsed = time.time() - start_time
    logger.info(f"\n=== FUNDAMENTAL DATA COLLECTION SUMMARY ===")
    logger.info(f"Total time: {elapsed/60:.1f} minutes")
    logger.info(f"Total tickers: {len(tickers)}")
    logger.info(f"Successful: {len(results)}")
    logger.info(f"Failed: {len(failed_tickers)}")
    
    if failed_tickers:
        with open(DATA_DIR / "failed_tickers_fundamental.txt", "w") as f:
            f.write("\n".join(failed_tickers))
        logger.warning(f"Failed tickers saved to failed_tickers_fundamental.txt")
    
    return results


# ============================================================================
# 4. 안전한 데이터 접근 헬퍼
# ============================================================================

def safe_get_info(ticker_data: Dict, key: str, default=None):
    """
    info dict에서 안전하게 값 가져오기
    
    Args:
        ticker_data: download_fundamental_data_bulk()의 반환값 중 하나
        key: info dict 키 (예: 'trailingEps')
        default: 기본값
    
    Returns:
        값 또는 default
    """
    try:
        info = ticker_data.get('info', {})
        value = info.get(key, default)
        
        # 유효하지 않은 값 처리
        if value in [None, 'None', '', 'N/A', np.nan]:
            return default
        
        # 숫자 타입이어야 하는데 문자열인 경우
        if key in ['trailingEps', 'forwardEps', 'returnOnEquity', 'revenueGrowth']:
            try:
                return float(value)
            except (ValueError, TypeError):
                return default
        
        return value
    except Exception:
        return default


def extract_canslim_metrics(ticker_data: Dict, symbol: str) -> Dict:
    """
    CANSLIM 지표 추출
    
    Args:
        ticker_data: download_fundamental_data_bulk()의 반환값 중 하나
        symbol: 티커 심볼
    
    Returns:
        {
            'eps_ttm': float,
            'eps_growth_yoy': float,
            'revenue_growth': float,
            'roe': float,
            'institutional_ownership': float,
            'market_cap': float,
            ...
        }
    """
    info = ticker_data.get('info', {})
    
    metrics = {
        'symbol': symbol,
        
        # E - Earnings (현재 분기 EPS)
        'eps_ttm': safe_get_info(ticker_data, 'trailingEps', 0.0),
        'eps_forward': safe_get_info(ticker_data, 'forwardEps', 0.0),
        'eps_growth_yoy': safe_get_info(ticker_data, 'earningsGrowth', 0.0),
        
        # A - Annual Earnings Increase (매출 증가)
        'revenue_growth': safe_get_info(ticker_data, 'revenueGrowth', 0.0),
        'revenue': safe_get_info(ticker_data, 'totalRevenue', 0.0),
        
        # N - New (신고가, 별도 계산 필요)
        'fifty_two_week_high': safe_get_info(ticker_data, 'fiftyTwoWeekHigh', 0.0),
        'current_price': safe_get_info(ticker_data, 'currentPrice', 0.0),
        
        # S - Supply & Demand (거래량, 유동주식)
        'volume': safe_get_info(ticker_data, 'volume', 0),
        'avg_volume': safe_get_info(ticker_data, 'averageVolume', 0),
        'float_shares': safe_get_info(ticker_data, 'floatShares', 0),
        
        # L - Leader or Laggard (ROE, 마진)
        'roe': safe_get_info(ticker_data, 'returnOnEquity', 0.0),
        'profit_margin': safe_get_info(ticker_data, 'profitMargins', 0.0),
        'operating_margin': safe_get_info(ticker_data, 'operatingMargins', 0.0),
        
        # I - Institutional Sponsorship
        'institutional_ownership': safe_get_info(ticker_data, 'heldPercentInstitutions', 0.0),
        'num_institutions': 0,  # institutional_holders DataFrame에서 추출
        
        # M - Market Direction (별도 계산)
        'market_cap': safe_get_info(ticker_data, 'marketCap', 0.0),
        
        # 기타
        'sector': safe_get_info(ticker_data, 'sector', ''),
        'industry': safe_get_info(ticker_data, 'industry', ''),
        'exchange': safe_get_info(ticker_data, 'exchange', ''),
    }
    
    # Institutional holders 수 계산
    inst_holders = ticker_data.get('institutional_holders')
    if inst_holders is not None and not inst_holders.empty:
        metrics['num_institutions'] = len(inst_holders)
    
    return metrics


# ============================================================================
# 5. 메인 실행 스크립트
# ============================================================================

def main():
    """
    전체 데이터 수집 파이프라인
    """
    logger.info("=== CANSLIM Trading Bot - Data Collection Pipeline ===")
    
    # 1. 종목 리스트 가져오기
    logger.info("\n[Step 1/3] Fetching ticker list...")
    try:
        tickers = get_ticker_list_nasdaq_ftp()
    except Exception as e:
        logger.error(f"FTP method failed: {e}. Trying alternative method...")
        tickers = get_ticker_list_simple()
    
    if not tickers:
        logger.error("Failed to fetch ticker list. Exiting.")
        return
    
    # 디버그 모드: 소수 종목만 테스트
    DEBUG = False
    if DEBUG:
        tickers = tickers[:100]
        logger.warning(f"DEBUG MODE: Using only {len(tickers)} tickers")
    
    # 2. 가격 데이터 다운로드 (300일)
    logger.info(f"\n[Step 2/3] Downloading price data for {len(tickers)} tickers...")
    try:
        price_data = download_price_data_bulk(
            tickers=tickers,
            period="300d",  # Turtle Trading은 300일 필요
            interval="1d"
        )
        
        # 저장
        price_data_path = DATA_DIR / "price_data_300d.pkl"
        price_data.to_pickle(price_data_path)
        logger.info(f"Price data saved to {price_data_path}")
        logger.info(f"Shape: {price_data.shape}")
        
    except Exception as e:
        logger.error(f"Price data download failed: {e}")
        return
    
    # 3. 재무 데이터 수집
    logger.info(f"\n[Step 3/3] Downloading fundamental data...")
    logger.info("WARNING: This will take ~1-2 hours for 8000 tickers")
    
    try:
        fundamental_data = download_fundamental_data_bulk(
            tickers=tickers,
            delay_per_ticker=0.5,
            checkpoint_every=500
        )
        
        # 저장
        fundamental_data_path = DATA_DIR / "fundamental_data.pkl"
        with open(fundamental_data_path, "wb") as f:
            pickle.dump(fundamental_data, f)
        logger.info(f"Fundamental data saved to {fundamental_data_path}")
        
        # CANSLIM 지표 추출 및 저장
        logger.info("\nExtracting CANSLIM metrics...")
        canslim_metrics = []
        for symbol, data in fundamental_data.items():
            metrics = extract_canslim_metrics(data, symbol)
            canslim_metrics.append(metrics)
        
        canslim_df = pd.DataFrame(canslim_metrics)
        canslim_df_path = DATA_DIR / "canslim_metrics.csv"
        canslim_df.to_csv(canslim_df_path, index=False)
        logger.info(f"CANSLIM metrics saved to {canslim_df_path}")
        logger.info(f"Shape: {canslim_df.shape}")
        
    except Exception as e:
        logger.error(f"Fundamental data collection failed: {e}")
        return
    
    logger.info("\n=== DATA COLLECTION COMPLETED ===")
    logger.info(f"Files saved in: {DATA_DIR}")
    logger.info("Next steps:")
    logger.info("1. Implement data/fundamental_data.py to load fundamental_data.pkl")
    logger.info("2. Implement data/price_cache.py to load price_data_300d.pkl")
    logger.info("3. Use canslim_metrics.csv for screening")


if __name__ == "__main__":
    main()
