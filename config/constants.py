"""
Strategy constants extracted from TURTLE_TRADING_STRATEGY.md §10.

Every constant has exactly ONE value — no ambiguous ranges.
These are used throughout the strategy engine, position sizing, and risk management.

Reference: TURTLE_TRADING_STRATEGY.md §10 "전체 상수 요약 (코드용)"
Reference: QUANTIFIED_STRATEGY.md §9 "전체 상수 요약" for CANSLIM thresholds
"""

# ============================================================
# ATR (N) Calculation
# ============================================================
ATR_PERIOD: int = 20                         # N calculation period (20 days)
ATR_METHOD: str = "EMA"                      # Exponential Moving Average (turtle original)
ATR_SMOOTHING_FACTOR: float = 1 / 20         # EMA smoothing factor = 0.05


# ============================================================
# Entry (Donchian Channel Breakout)
# ============================================================

# System 1 — Short-term
SYSTEM1_ENTRY_DAYS: int = 20                 # 20-day high breakout for entry
SYSTEM1_EXIT_DAYS: int = 10                  # 10-day low break for exit
SYSTEM1_FILTER_ENABLED: bool = True          # Skip if prior breakout was profitable (original rule)

# System 2 — Long-term
SYSTEM2_ENTRY_DAYS: int = 55                 # 55-day high breakout for entry
SYSTEM2_EXIT_DAYS: int = 20                  # 20-day low break for exit
SYSTEM2_FILTER_ENABLED: bool = False         # No filter — enter on every breakout

# Entry price basis
ENTRY_PRICE_BASIS: str = "CLOSE"             # "CLOSE" = closing price basis


# ============================================================
# Position Sizing (Minervini Risk-Based)
# ============================================================
RISK_PER_UNIT_PCT: float = 0.01              # Risk per unit: 1% of account equity
# actual_stop = min(STOP_LOSS_N × N, entry_price × STOP_LOSS_MAX_PCT)
# Unit (shares) = (Account × RISK_PER_UNIT_PCT) / actual_stop
MAX_SINGLE_UNIT_PCT: float = 0.30            # Single unit max weight: 30% of account
MAX_SINGLE_POSITION_PCT: float = 0.40        # Single position (4 units) max: 40% of account


# ============================================================
# Pyramiding
# ============================================================
MAX_UNITS_PER_STOCK: int = 4                 # Max 4 units per stock
PYRAMID_INTERVAL_N: float = 0.5              # Add interval: 1/2 N (= 0.5 × ATR)
# Pyramid trigger: last_entry_price + PYRAMID_INTERVAL_N × N


# ============================================================
# Stop Loss
# ============================================================
STOP_LOSS_N: float = 2.0                     # Turtle base stop distance: 2N (= 2 × ATR)
STOP_LOSS_MAX_PCT: float = 0.10              # Max stop cap: 10% from entry
# Hybrid stop = entry_price - min(2N, entry_price × 10%)
# N/P ≤ 5%: 2N applies (10% cap inactive)
# N/P > 5%: 10% cap activates (tighter than 2N)
# On pyramid: all stops = min(2N, 10%) from latest entry (can only tighten)
STOP_LOSS_MOVE_DIRECTION: str = "UP_ONLY"    # Stop can only move up, never down


# ============================================================
# Position Limits (Risk Management)
# ============================================================
MAX_UNITS_SINGLE: int = 4                    # Single stock: 4 units
MAX_UNITS_CORRELATED: int = 6                # Closely correlated (same IBD Industry): 6 units
MAX_UNITS_LOOSELY_CORRELATED: int = 10       # Loosely correlated (same GICS Sector): 10 units
MAX_UNITS_LONG: int = 12                     # Total long direction: 12 units
MAX_UNITS_SHORT: int = 12                    # Total short direction: 12 units (if short enabled)
MAX_UNITS_TOTAL: int = 24                    # Both directions combined: 24 units


# ============================================================
# Market Direction Filter
# ============================================================
MARKET_MA_PERIOD: int = 200                  # 200-day Simple Moving Average
MARKET_MA_TYPE: str = "SMA"                  # Simple Moving Average
MARKET_BENCHMARK: str = "SPY"                # S&P 500 ETF
MARKET_FILTER_RULE: str = "ABOVE_MA"         # Entry allowed when close > MA
MARKET_FILTER_BUFFER_PCT: float = 0.00       # No buffer (0% = exact MA boundary)
MARKET_FILTER_APPLIES_TO: str = "NEW_ENTRIES"  # Only applies to new entries
# Existing positions managed by turtle exit rules regardless of market filter

# ── Market Breadth & ROC (3-tier regime) ──
MARKET_BREADTH_GREEN: float = 0.55   # >55% of universe above 200 SMA = healthy
MARKET_BREADTH_RED: float = 0.35     # <35% = deteriorating
MARKET_ROC_PERIOD: int = 125         # 125-day (≈6 month) rate of change
MARKET_ROC_WARNING: float = -0.05    # ROC < -5% = momentum broken
MARKET_REGIME_YELLOW_SCALE: float = 0.5  # YELLOW regime: half unit sizing


# ============================================================
# IBD Market Direction (Standalone Logging)
# ============================================================
IBD_INDEXES_US: list[str] = ["SPY", "QQQ"]
IBD_INDEXES_KR: list[str] = ["069500", "229200"]  # KODEX200, KODEX KOSDAQ150
IBD_DISTRIBUTION_MIN_DECLINE: float = -0.002
IBD_DISTRIBUTION_WINDOW: int = 25
IBD_DISTRIBUTION_RALLY_EXPIRE: float = 0.05
IBD_STALL_MAX_GAIN: float = 0.004
IBD_STALL_MIN_GAIN: float = 0.0
IBD_STALL_CLOSE_RANGE_MAX: float = 0.50
IBD_STALL_VOLUME_RATIO: float = 0.95
IBD_STALL_MAX_COUNT: int = 2
IBD_FTD_MIN_GAIN: float = 0.0125
IBD_FTD_EARLIEST_DAY: int = 4
IBD_FTD_LATEST_DAY: int = 10
IBD_PRESSURE_THRESHOLD: int = 3
IBD_CORRECTION_THRESHOLD: int = 5
IBD_FTD_FRAGILE_DAYS: int = 2
IBD_LOOKBACK_DAYS: int = 60


# ============================================================
# Short Selling — Disabled by Default
# ============================================================
SHORT_ENABLED: bool = False                  # Default: shorts disabled
SHORT_SYSTEM1_ENTRY_DAYS: int = 20           # 20-day low breakdown
SHORT_SYSTEM2_ENTRY_DAYS: int = 55           # 55-day low breakdown
SHORT_SYSTEM1_EXIT_DAYS: int = 10            # 10-day high breakout to cover
SHORT_SYSTEM2_EXIT_DAYS: int = 20            # 20-day high breakout to cover
SHORT_MARKET_CONDITION: str = "BELOW_MA"     # Short only when SPY < 200MA


# ============================================================
# CANSLIM Stock Selection Thresholds
# (Detail in QUANTIFIED_STRATEGY.md)
# ============================================================
CANSLIM_MIN_QUARTERLY_EPS_GROWTH: float = 0.25    # C: +25% YoY minimum
CANSLIM_MIN_ANNUAL_EPS_CAGR: float = 0.25         # A: +25% 5-year CAGR
CANSLIM_MIN_RS_RATING: int = 80                    # L: RS Rating ≥ 80
CANSLIM_MIN_EPS_RATING: int = 80                   # EPS Rating ≥ 80
CANSLIM_MIN_COMPOSITE_RATING: int = 90             # Composite Rating ≥ 90
CANSLIM_MIN_INSTITUTIONAL_HOLDERS: int = 5         # I: Minimum 5 institutional holders
CANSLIM_MIN_INSTITUTIONAL_CHANGE_PCT: float = 0.10 # I: QoQ +10% increase
CANSLIM_MIN_ADV: int = 500_000                     # S: Minimum 500K avg daily volume
CANSLIM_BREAKOUT_VOLUME_RATIO: float = 1.50        # S: Breakout volume ≥ 1.5x ADV
CANSLIM_MIN_UP_DOWN_RATIO: float = 1.5             # S: Up/Down volume ratio ≥ 1.5
CANSLIM_MAX_DEBT_TO_EQUITY: float = 2.0            # D/E ratio ≤ 2.0
CANSLIM_MIN_PRICE: float = 10.0                    # Minimum stock price $10
CANSLIM_INDUSTRY_RANK_MAX: int = 40                # Top 40 industry rank


# ============================================================
# RS Rating Calculation (IBD approximation)
# ============================================================
RS_WEIGHT_3M: float = 0.40                  # 3-month return weight (2x)
RS_WEIGHT_6M: float = 0.20                  # 6-month return weight
RS_WEIGHT_9M: float = 0.20                  # 9-month return weight
RS_WEIGHT_12M: float = 0.20                 # 12-month return weight

RS_TRADING_DAYS_3M: int = 63                # Trading days in 3 months
RS_TRADING_DAYS_6M: int = 126               # Trading days in 6 months
RS_TRADING_DAYS_9M: int = 189               # Trading days in 9 months
RS_TRADING_DAYS_12M: int = 252              # Trading days in 12 months


# ============================================================
# Custom Composite Score Weights (IBD Composite replacement)
# ============================================================
COMPOSITE_WEIGHT_EPS: float = 0.30           # EPS growth score: 30%
COMPOSITE_WEIGHT_RS: float = 0.30            # RS Rating: 30%
COMPOSITE_WEIGHT_INSTITUTIONAL: float = 0.15 # Institutional accumulation: 15%
COMPOSITE_WEIGHT_SUPPLY_DEMAND: float = 0.15 # Supply/demand score: 15%
COMPOSITE_WEIGHT_FINANCIAL: float = 0.10     # Financial health: 10%


# ============================================================
# Liquidity & Execution Limits
# ============================================================
MAX_POSITION_PCT_OF_ADV: float = 0.05        # Unit size ≤ 5% of avg daily volume
EXECUTION_PRICE_BASIS: str = "CLOSE"         # Entry/exit: closing price basis
STOP_EXECUTION: str = "INTRADAY"             # Stop-loss: intraday immediate execution
GAP_DOWN_HANDLING: str = "MARKET_OPEN"       # Gap down: sell at market open price


# ============================================================
# Order Execution (Software Stop Implementation)
# ============================================================
STOP_SELL_BUFFER_PCT: float = 0.005          # 0.5% below current price for stop sell
BUY_BUFFER_PCT: float = 0.003               # 0.3% above current price for breakout buy
MAX_CHASE_PCT: float = 0.05                 # 5% — skip entry if price is >5% above breakout level (CANSLIM rule)
STOP_RETRY_DELAY_SECONDS: int = 5            # Retry unfilled stop after 5 seconds
STOP_MAX_RETRIES: int = 3                    # Max 3 retries for stop orders


# ============================================================
# System Operation Parameters
# ============================================================
LOOKBACK_DATA_DAYS: int = 300                # Minimum price data: 300 days (200MA + margin)
REBALANCE_FREQUENCY: str = "DAILY"           # Check signals daily after market close
ACCOUNT_EQUITY_BASIS: str = "TOTAL"          # Account equity = cash + position value


# ============================================================
# Minervini Trend Template (8 conditions)
# ============================================================
MINERVINI_MIN_PRICE_VS_150MA: float = 1.0    # Price > 150-day MA
MINERVINI_MIN_PRICE_VS_200MA: float = 1.0    # Price > 200-day MA
MINERVINI_MIN_150MA_VS_200MA: float = 1.0    # 150-day MA > 200-day MA
MINERVINI_200MA_UPTREND_DAYS: int = 22       # 200MA rising for at least 1 month (~22 days)
MINERVINI_MIN_PRICE_VS_52W_LOW: float = 1.30 # Price ≥ 130% of 52-week low
MINERVINI_MAX_PRICE_VS_52W_HIGH: float = 0.75  # Price within 25% of 52-week high (≥75%)
MINERVINI_MIN_RS_RATING_TREND: int = 70      # RS Rating ≥ 70 (preferably ≥ 80)


# ============================================================
# WebSocket Reliability
# ============================================================
WS_RECONNECT_DELAYS: list[int] = [1, 2, 4, 8, 16, 30, 30, 30]  # Exponential backoff (seconds)
WS_HEARTBEAT_TIMEOUT: int = 60              # Reconnect after 60s of silence
WS_REST_FALLBACK_INTERVAL: int = 10         # REST polling interval when WS is down (seconds)


# ============================================================
# Donchian Exit Timing
# ============================================================
DONCHIAN_EXIT_MINUTES_BEFORE_CLOSE: int = 15  # Check Donchian exit 15 min before close
# US market close = KST 06:00, so check at KST 05:45


# ============================================================
# Data Collection
# ============================================================
YFINANCE_BATCH_SIZE: int = 50                # Stocks per batch for yfinance download
YFINANCE_BATCH_DELAY: float = 2.0            # Seconds between batches (rate limit avoidance)
SCREENING_FREQUENCY: str = "DAILY"           # CANSLIM rescreening frequency
FUNDAMENTAL_UPDATE_MONTHS: list[int] = [1, 4, 7, 10]  # Earnings season months (fallback)

# ── yfinance Rate Limit ──
YFINANCE_RATE_LIMIT_MAX_RETRIES: int = 3     # Max retries on YFRateLimitError
YFINANCE_RATE_LIMIT_BASE_DELAY: float = 5.0  # Initial backoff delay (seconds)
YFINANCE_RATE_LIMIT_BACKOFF_MULT: float = 2.0  # Exponential multiplier
YFINANCE_RATE_LIMIT_MAX_DELAY: float = 60.0  # Max single delay cap (seconds)

# ── Daily Screening Pipeline ──
EARNINGS_CALENDAR_LOOKBACK_DAYS: int = 3     # Check last N days of earnings reports
DAILY_SCREENING_HOUR: int = 20               # KST 20:00 (2h before pre_market)
DAILY_SCREENING_MINUTE: int = 0
