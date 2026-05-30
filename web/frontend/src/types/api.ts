// ═══════════════════════════════════════════════
// API Response Types — matches Python route responses exactly
// ═══════════════════════════════════════════════

// ── GET /api/status ──────────────────────────────

export interface StatusResponse {
  mode: string;
  market_filter: string;
  market_filter_pass: boolean;
  regime?: string;
  regime_scale?: number;
  breadth_pct?: number | null;
  roc?: number | null;
  benchmark: {
    name: string;
    close: number | null;
    sma200: number | null;
  };
  positions: number;
  units: number;
  account_equity: number;
  cash_balance: number;
  positions_value: number;
  ws_status: string;
  market?: string;
}

// ── GET /api/positions ───────────────────────────

export interface Unit {
  id: number;
  unit_number: number;
  entry_price: number;
  shares: number;
  entry_stop_price: number;
  current_stop_price: number;
  entered_at: string;
}

export interface Position {
  id: number;
  ticker: string;
  name: string | null;
  system: string;
  status: string;
  total_shares: number;
  total_cost: number;
  avg_entry_price: number;
  current_stop_price: number;
  donchian_lower_10: number | null;
  donchian_lower_20: number | null;
  n_at_entry: number;
  sector: string | null;
  industry: string | null;
  opened_at: string;
  closed_at: string | null;
  close_reason: string | null;
  realized_pnl: number | null;
  current_price: number | null;
  eval_amount: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  units: Unit[];
  market?: string;
}

export interface BrokerPosition {
  ticker: string;
  name: string | null;
  exchange: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  eval_amount: number;
  pnl_amount: number;
  pnl_pct: number;
  currency: string;
}

export interface PositionsResponse {
  positions: Position[];
  broker_positions: BrokerPosition[];
  count: number;
  broker_count: number;
}

// ── GET /api/watchlist ───────────────────────────

export interface WatchlistStock {
  ticker: string;
  name: string | null;
  added_date: string;
  last_screened: string;
  quarterly_eps_growth: number | null;
  annual_eps_cagr: number | null;
  rs_rating: number | null;
  institutional_holders: number | null;
  institutional_change_pct: number | null;
  custom_composite_score: number | null;
  minervini_pass: boolean;
  sector: string | null;
  industry: string | null;
  avg_daily_volume: number | null;
  market_cap: number | null;
  status: string;
  latest_price: number | null;
  latest_financial_date: string | null;
  n_value: number | null;
  avg_volume_50d: number | null;
  unit_shares: number | null;
  unit_value: number | null;
  unit_stop_price: number | null;
  max_position_value: number | null;
  market?: string;
}

export interface WatchlistResponse {
  watchlist: WatchlistStock[];
  count: number;
  market?: string;
}

export interface WatchlistHistoryEntry {
  id: number;
  ticker: string;
  name: string | null;
  market: string;
  action: 'ADDED' | 'REMOVED';
  reason: string | null;
  quarterly_eps_growth: number | null;
  annual_eps_cagr: number | null;
  rs_rating: number | null;
  composite_score: number | null;
  minervini_pass: boolean | null;
  recorded_at: string;
}

export interface WatchlistHistoryResponse {
  history: WatchlistHistoryEntry[];
  total: number;
  market: string;
}

// ── GET /api/stock-reports/{ticker} ──────────────

export interface StockReportBreakdownItem {
  score: number;
  comment: string;
}

export interface StockReportJson {
  verdict: 'PASS' | 'WATCH' | 'FAIL';
  company_profile?: string;
  latest_quarter_report_summary?: {
    period: string;
    report_date: string;
    summary: string;
    revenue: string;
    eps: string;
    net_income: string;
    yoy_growth: {
      revenue: string;
      eps: string;
      net_income: string;
    };
    qoq_growth: {
      revenue: string;
      eps: string;
      net_income: string;
    };
    recent_quarter_trend: string;
  };
  consensus_summary?: {
    available: boolean;
    summary: string;
    next_quarter: string;
    current_year: string;
    next_year: string;
    estimate_revisions: string;
    analyst_rating: string;
  };
  advisory_buy_opinion?: {
    reference_only: boolean;
    opinion: 'BUY_CANDIDATE' | 'WAIT' | 'NO_BUY';
    confidence: number;
    reason: string;
    conditions: string[];
    not_included_in_trade_gate: boolean;
  };
  canslim_fit_score: number;
  minervini_fit_score: number;
  overall_fit_score: number;
  confidence: number;
  summary: string;
  oneil_thesis: string;
  minervini_thesis: string;
  watchlist_reason: string;
  risk_note: string;
  strengths: string[];
  weaknesses: string[];
  red_flags: string[];
  canslim_breakdown: Record<string, StockReportBreakdownItem>;
  minervini_breakdown: {
    trend_template_pass: boolean;
    score: number;
    comment: string;
  };
}

export interface StockReportRecord {
  id: number;
  provider: string;
  model: string;
  report_json: StockReportJson;
  summary_markdown: string;
  verdict: 'PASS' | 'WATCH' | 'FAIL';
  canslim_fit_score: number;
  minervini_fit_score: number;
  overall_fit_score: number;
  confidence: number;
  generated_at: string;
  updated_at: string;
}

export interface StockReportResponse {
  ticker: string;
  market: string;
  eligible: boolean;
  report_period: string;
  financial_data_hash: string;
  has_financial_data: boolean;
  report: StockReportRecord | null;
  cache_hit?: boolean;
}

export interface AIReportStatusResponse {
  provider: string;
  model: string;
  configured: boolean;
  usage_supported: boolean;
  available: boolean;
  status: string;
  message: string;
  current_month_cost_usd: number | null;
  monthly_budget_usd: number | null;
  remaining_budget_usd: number | null;
  min_remaining_usd: number | null;
  checked_at: string | null;
}

// ── GET /api/trades ──────────────────────────────

export interface Trade {
  id: number | string;
  broker_order_id: string | null;
  ticker: string;
  name?: string | null;
  side: string;
  order_type: string;
  trade_type?: string;
  trade_system?: string;
  requested_shares: number;
  requested_price: number;
  filled_shares: number;
  filled_price: number | null;
  status: string;
  created_at: string;
  updated_at: string;
  filled_at: string | null;
  notes: string | null;
  source?: string;
}

export interface TradesResponse {
  trades: Trade[];
  broker_trades?: Trade[];
  total: number;
  broker_total?: number;
  limit: number;
  offset: number;
  market?: string;
}

// ── GET /api/pnl ─────────────────────────────────

export interface PnlDataPoint {
  period: string;
  start: string;
  end: string;
  pnl: number;
  equity: number;
  max_drawdown_pct: number;
  entries: number;
  exits: number;
  stop_losses: number;
}

export interface PnlResponse {
  period: string;
  data: PnlDataPoint[];
  summary: {
    total_pnl: number;
    max_equity: number;
    max_drawdown_pct: number;
    data_points: number;
  };
  market?: string;
}

// ── GET /api/journal ─────────────────────────────

export interface JournalTrade {
  ticker: string;
  name?: string | null;
  system: string;
  realized_pnl: number;
  realized_pnl_pct: number;
  opened_at: string;
  closed_at: string;
  close_reason: string;
  avg_entry_price: number;
  stop_price: number;
  exit_price: number;
  total_shares: number;
  risk_per_share: number;
  holding_days: number | null;
}

export interface JournalResponse {
  month: string;
  start_month: string;
  end_month: string;
  stats: {
    total_trades: number;
    winners: number;
    losers: number;
    win_rate_pct: number;
    avg_win: number;
    avg_loss: number;
    risk_reward_ratio: number;
    max_drawdown_pct: number;
    monthly_pnl: number;
    min_equity: number;
    max_equity: number;
    avg_holding_days: number;
    avg_win_holding_days: number;
    avg_loss_holding_days: number;
  };
  trades: JournalTrade[];
}

// ── GET /api/diary ───────────────────────────────

export interface JournalContext {
  type?: string;
  system?: string;
  breakout_level?: number | null;
  atr?: number;
  stop_price?: number;
  risk_per_share?: number;
  market_filter?: boolean;
  rs_rating?: number | null;
  composite_score?: number | null;
  account_equity?: number;
  position_size_pct?: number;
  unit_number?: number;
  new_stop?: number;
  prev_stop?: number;
  pyramid_interval?: number;
  trigger_price?: number;
  avg_entry_price?: number;
  atr_at_entry?: number;
  units_held?: number;
  total_shares?: number;
  loss_pct?: number;
  exit_level?: number | null;
  exit_reason?: string;
  pnl_pct?: number;
  error?: string;
  raw?: string;
}

export interface DiaryEntry {
  order_id: number;
  ticker: string;
  name?: string | null;
  side: string;
  order_type: string;
  requested_shares: number;
  requested_price: number;
  filled_shares: number;
  filled_price: number | null;
  status: string;
  created_at: string;
  filled_at: string | null;
  context: JournalContext | null;
  position_system: string | null;
  position_avg_entry: number | null;
  position_pnl: number | null;
  close_reason: string | null;
  position_opened: string | null;
  position_closed: string | null;
}

export interface DiaryResponse {
  entries: DiaryEntry[];
  total: number;
  limit: number;
  offset: number;
  available_tickers: string[];
}

// ── GET /api/logs ───────────────────────────────

export interface LogEntry {
  event: string;
  level?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface BotEvent {
  id: number;
  timestamp: string;
  level: string;
  event: string;
  module: string | null;
  ticker: string | null;
  details: string | null;
}

export interface LogsResponse {
  logs: LogEntry[];
  bot_events: BotEvent[];
  total_log_lines: number;
  log_file: string;
  log_file_exists: boolean;
}

// ── GET /api/bot-health ─────────────────────────

export interface DailyLogSummary {
  date: string;
  account_equity: number | null;
  daily_pnl: number | null;
  daily_pnl_pct: number | null;
  total_positions: number | null;
  total_units: number | null;
  entries_count: number | null;
  exits_count: number | null;
  stop_losses_count: number | null;
}

export interface BotHealthResponse {
  health_status: 'running' | 'stopped' | 'degraded';
  mode: string;
  ws_status: string;
  market_filter: string;
  bot_started_at: string | null;
  last_heartbeat: string | null;
  last_screening: string | null;
  last_error: string | null;
  open_positions: number;
  active_watchlist: number;
  pending_orders: number;
  recent_error_count: number;
  last_daily_log: DailyLogSummary | null;
  latest_price_date: string | null;
  latest_fundamental_date: string | null;
  latest_screening_date: string | null;
  live_equity: number | null;
  live_cash: number | null;
}

// ── GET /api/alerts/near-entry ──────────────────

export interface NearEntryAlert {
  ticker: string;
  name: string | null;
  latest_price: number;
  donchian_upper_20: number;
  donchian_upper_55: number | null;
  donchian_lower_20: number;
  proximity_pct_20: number;
  proximity_pct_55: number | null;
  already_broken_20: boolean;
  already_broken_55: boolean;
  signal_type: 'S1' | 'S2' | 'S1+S2' | 'none';
  alert_level: 'breakout' | 'imminent' | 'close' | 'normal';
  rs_rating: number | null;
  composite_score: number | null;
  sma_20: number;
  latest_financial_date: string | null;
}

export interface NearEntryAlertsResponse {
  alerts: NearEntryAlert[];
  total: number;
  imminent_count: number;
  breakout_count: number;
}

// ── GET /api/prices/realtime ────────────────────

export interface RealtimePriceData {
  price: number;
  change_pct: number;
  volume: number | null;
  updated_at: string;
}

export interface RealtimePricesResponse {
  prices: Record<string, RealtimePriceData>;
  cached: boolean;
}

// ── GET /api/alerts/near-exit ──────────────────

export interface ExitAlert {
  ticker: string;
  name: string | null;
  position_side: string;
  entry_price: number;
  current_price: number;
  unrealized_pnl_pct: number;
  system: string;
  donchian_lower_10: number;
  donchian_lower_20: number;
  current_stop_price: number | null;
  exit_proximity_pct: number;
  exit_level: 'critical' | 'warning' | 'safe';
}

export interface ExitAlertsResponse {
  alerts: ExitAlert[];
  total: number;
  critical_count: number;
  warning_count: number;
}

// ── Market Status ─────────────────────────────────

export interface MarketInfo {
  market_id: string;
  display_name: string;
  enabled: boolean;
  currency: string;
  exchanges: string[];
}

export interface MarketStatusResponse {
  markets: MarketInfo[];
}

export interface MarketToggleResponse {
  market_id: string;
  enabled: boolean;
  success: boolean;
}

// ── POST /api/account/reset ─────────────────────

export interface AccountResetResponse {
  success: boolean;
  mode: string;
  reset_at: string;
  closed_positions: number;
  cancelled_orders: number;
  cleared_state_keys: number;
  account_equity: number | null;
  cash_balance: number | null;
  currency: string;
}
