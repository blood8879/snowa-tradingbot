export const API = {
  status: (market = 'US') => `/api/status?market=${market}`,
  positions: (market = 'US') => `/api/positions?market=${market}`,
  watchlist: (market = 'US') => `/api/watchlist?market=${market}`,
  trades: (limit = 50, offset = 0, market = 'US') =>
    `/api/trades?limit=${limit}&offset=${offset}&market=${market}`,
  pnl: (period = 'daily', market = 'US') => `/api/pnl?period=${period}&market=${market}`,
  journal: (month?: string, market = 'US') => {
    const params = new URLSearchParams();
    if (month) params.set('month', month);
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
};
