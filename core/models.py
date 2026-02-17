"""
Data models for the trading bot.

Uses Python dataclasses for lightweight, immutable data containers.
These models represent the core domain objects used across all modules.

Note: These are NOT ORM models — they are plain data structures.
SQLite interaction is handled by core/database.py using raw SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================
# Enums
# ============================================================

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    ENTRY = "ENTRY"
    PYRAMID = "PYRAMID"
    STOP_LOSS = "STOP_LOSS"
    EXIT = "EXIT"             # Donchian channel exit
    MANUAL = "MANUAL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    SYSTEM1_EXIT = "SYSTEM1_EXIT"
    SYSTEM2_EXIT = "SYSTEM2_EXIT"
    MANUAL = "MANUAL"


class TradingSystem(str, Enum):
    S1 = "S1"  # System 1 (20-day breakout)
    S2 = "S2"  # System 2 (55-day breakout)


class WatchlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    SUSPENDED = "SUSPENDED"


class SignalType(str, Enum):
    ENTRY_LONG = "ENTRY_LONG"
    PYRAMID_ADD = "PYRAMID_ADD"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    DONCHIAN_EXIT = "DONCHIAN_EXIT"
    GAP_DOWN_EXIT = "GAP_DOWN_EXIT"


class WebSocketStatus(str, Enum):
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FALLBACK_REST = "FALLBACK_REST"
    DISCONNECTED = "DISCONNECTED"


class ExchangeCode(str, Enum):
    """KIS exchange codes for US stocks."""
    NASD = "NASD"  # NASDAQ
    NYSE = "NYSE"  # New York Stock Exchange
    AMEX = "AMEX"  # American Stock Exchange


# ============================================================
# Data Models
# ============================================================

@dataclass(frozen=True)
class OHLCV:
    """Single candlestick (daily bar)."""
    date: str               # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class WatchlistStock:
    """A stock in the CANSLIM watchlist."""
    ticker: str
    added_date: str
    last_screened: str

    # CANSLIM scores
    quarterly_eps_growth: Optional[float] = None
    annual_eps_cagr: Optional[float] = None
    rs_rating: Optional[float] = None
    institutional_holders: Optional[int] = None
    institutional_change_pct: Optional[float] = None
    custom_composite_score: Optional[float] = None

    # Minervini Trend Template
    minervini_pass: bool = False

    # Meta
    sector: Optional[str] = None
    industry: Optional[str] = None
    avg_daily_volume: Optional[int] = None
    market_cap: Optional[float] = None

    status: WatchlistStatus = WatchlistStatus.ACTIVE


@dataclass
class Unit:
    """A single entry unit within a position."""
    id: Optional[int] = None
    position_id: Optional[int] = None
    unit_number: int = 1

    entry_price: float = 0.0
    shares: int = 0
    entry_stop_price: float = 0.0
    current_stop_price: float = 0.0

    entered_at: str = ""


@dataclass
class Position:
    """An open or closed trading position."""
    id: Optional[int] = None
    ticker: str = ""
    system: TradingSystem = TradingSystem.S1
    status: PositionStatus = PositionStatus.OPEN

    # Aggregates
    total_shares: int = 0
    total_cost: float = 0.0
    avg_entry_price: float = 0.0
    current_stop_price: float = 0.0
    n_at_entry: float = 0.0  # ATR(N) at time of first entry

    # Limits tracking
    sector: Optional[str] = None
    industry: Optional[str] = None

    # Timestamps
    opened_at: str = ""
    closed_at: Optional[str] = None
    close_reason: Optional[CloseReason] = None
    realized_pnl: Optional[float] = None

    # Units within this position
    units: list[Unit] = field(default_factory=list)

    @property
    def unit_count(self) -> int:
        return len(self.units)

    @property
    def can_add_unit(self) -> bool:
        from config.constants import MAX_UNITS_PER_STOCK
        return self.unit_count < MAX_UNITS_PER_STOCK


@dataclass
class Order:
    """A buy or sell order."""
    id: Optional[int] = None
    broker_order_id: Optional[str] = None
    ticker: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.ENTRY

    requested_shares: int = 0
    requested_price: float = 0.0

    filled_shares: int = 0
    filled_price: Optional[float] = None

    status: OrderStatus = OrderStatus.PENDING

    created_at: str = ""
    updated_at: str = ""
    filled_at: Optional[str] = None

    notes: Optional[str] = None


@dataclass(frozen=True)
class TradeSignal:
    """A signal generated by the strategy engine."""
    signal_type: SignalType
    ticker: str
    price: float
    timestamp: datetime

    # Context depends on signal type
    system: Optional[TradingSystem] = None
    stop_price: Optional[float] = None
    shares: Optional[int] = None
    unit_number: Optional[int] = None

    # For entry signals
    breakout_level: Optional[float] = None
    n_value: Optional[float] = None

    # For pyramid signals
    pyramid_entry_price: Optional[float] = None


@dataclass(frozen=True)
class DonchianLevels:
    """Pre-calculated Donchian channel levels for a ticker."""
    ticker: str
    upper_20: float       # 20-day high (System 1 entry)
    upper_55: float       # 55-day high (System 2 entry)
    lower_10: float       # 10-day low (System 1 exit)
    lower_20: float       # 20-day low (System 2 exit)
    calculated_at: str    # ISO 8601 timestamp


@dataclass
class PrecomputedSignals:
    """
    Pre-market computed values for a single ticker.
    Calculated daily before market open.
    """
    ticker: str
    n_value: float                     # Current ATR(N)
    donchian: DonchianLevels

    # Pre-calculated trigger prices
    s1_entry_price: Optional[float] = None    # System 1 breakout level
    s2_entry_price: Optional[float] = None    # System 2 breakout level
    stop_price: Optional[float] = None        # Current stop (for open positions)
    pyramid_price: Optional[float] = None     # Next pyramid trigger (for open positions)

    # Market filter
    market_filter_pass: bool = False


@dataclass
class DailyLog:
    """Daily trading summary."""
    date: str

    # Market state
    spy_close: Optional[float] = None
    spy_sma200: Optional[float] = None
    market_filter_pass: bool = False

    # Portfolio
    account_equity: float = 0.0
    cash_balance: float = 0.0
    total_positions: int = 0
    total_units: int = 0

    # Performance
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    cumulative_pnl: float = 0.0
    max_drawdown_pct: float = 0.0

    # Activity
    entries_count: int = 0
    exits_count: int = 0
    stop_losses_count: int = 0


@dataclass(frozen=True)
class BreakoutRecord:
    """Historical breakout record for System 1 filter."""
    id: Optional[int] = None
    ticker: str = ""
    system: TradingSystem = TradingSystem.S1
    breakout_date: str = ""
    breakout_price: float = 0.0

    # Hypothetical outcome tracking
    would_have_been_winner: Optional[bool] = None
    hypothetical_exit_price: Optional[float] = None
    hypothetical_exit_date: Optional[str] = None

    was_actually_entered: bool = False


@dataclass
class AccountInfo:
    """Current account state from broker."""
    total_equity: float = 0.0
    cash_balance: float = 0.0
    total_positions_value: float = 0.0
    currency: str = "USD"

    # Derived
    @property
    def buying_power(self) -> float:
        return self.cash_balance
