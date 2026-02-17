export const API = {
  status: '/api/status',
  positions: '/api/positions',
  watchlist: '/api/watchlist',
  trades: (limit = 50, offset = 0) =>
    `/api/trades?limit=${limit}&offset=${offset}`,
  pnl: (period = 'daily') => `/api/pnl?period=${period}`,
  journal: (month?: string) =>
    month ? `/api/journal?month=${month}` : '/api/journal',
  diary: (ticker?: string, limit = 50, offset = 0) => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    if (ticker) params.set('ticker', ticker);
    return `/api/diary?${params.toString()}`;
  },
  logs: (limit = 100, level = 'ALL') =>
    `/api/logs?limit=${limit}&level=${level}`,
  botHealth: '/api/bot-health',
  nearEntryAlerts: '/api/alerts/near-entry',
  nearExitAlerts: '/api/alerts/near-exit',
  realtimePrices: (tickers: string[]) =>
    `/api/prices/realtime?tickers=${tickers.join(',')}`,
};
