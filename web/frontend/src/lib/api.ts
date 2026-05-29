export const API = {
  status: (market = 'US') => `/api/status?market=${market}`,
  positions: (market = 'US') => `/api/positions?market=${market}`,
  watchlist: (market = 'US') => `/api/watchlist?market=${market}`,
  watchlistHistory: (market = 'US', limit = 100) => `/api/watchlist/history?market=${market}&limit=${limit}`,
  trades: (limit = 50, offset = 0, market = 'US') =>
    `/api/trades?limit=${limit}&offset=${offset}&market=${market}`,
  pnl: (period = 'daily', market = 'US') => `/api/pnl?period=${period}&market=${market}`,
  journal: (
    opts: { month?: string; startMonth?: string; endMonth?: string; allTime?: boolean } | string = {},
    market = 'US',
  ) => {
    const params = new URLSearchParams();
    const o = typeof opts === 'string' ? { month: opts } : opts;
    if (o.allTime) {
      params.set('all_time', 'true');
    } else if (o.startMonth || o.endMonth) {
      if (o.startMonth) params.set('start_month', o.startMonth);
      if (o.endMonth) params.set('end_month', o.endMonth);
    } else if (o.month) {
      params.set('month', o.month);
    }
    params.set('market', market);
    return `/api/journal?${params.toString()}`;
  },
  diary: (ticker?: string, limit = 50, offset = 0, market = 'US') => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    if (ticker) params.set('ticker', ticker);
    params.set('market', market);
    return `/api/diary?${params.toString()}`;
  },
  logs: (limit = 100, level = 'ALL') =>
    `/api/logs?limit=${limit}&level=${level}`,
  botHealth: '/api/bot-health',
  nearEntryAlerts: (market = 'US') => `/api/alerts/near-entry?market=${market}`,
  nearExitAlerts: (market = 'US') => `/api/alerts/near-exit?market=${market}`,
  realtimePrices: (tickers: string[]) =>
    `/api/prices/realtime?tickers=${tickers.join(',')}`,
  marketStatus: '/api/market/status',
  marketToggle: (marketId: string) => `/api/market/${marketId}/toggle`,
  accountReset: '/api/account/reset',
  stockReport: (ticker: string, market = 'US') => `/api/stock-reports/${ticker}?market=${market}`,
  generateStockReport: (ticker: string, market = 'US') =>
    `/api/stock-reports/${ticker}/generate?market=${market}`,
};
