import useSWR from 'swr';
import { fetcher } from '../lib/fetcher';

interface IBDIndexState {
  index_ticker: string;
  display_name?: string;
  date: string;
  status: string;
  distribution_count: number;
  rally_day_count: number;
  ftd_date: string | null;
  ftd_low: number | null;
  notes: string | null;
}

interface IBDStatusResponse {
  overall_status: string;
  indexes: IBDIndexState[];
}

interface IBDDistDay {
  index_ticker: string;
  display_name?: string;
  date: string;
  day_type: string;
  close_price: number;
  price_change_pct: number;
  volume: number;
  prior_volume: number;
  expired: boolean;
  expiry_reason: string | null;
  expiry_date: string | null;
}

interface IBDDistDaysResponse {
  distribution_days: IBDDistDay[];
}

interface IBDHistoryEntry {
  date: string;
  index_ticker: string;
  status: string;
  distribution_count: number;
  rally_day_count: number;
}

interface IBDHistoryResponse {
  history: IBDHistoryEntry[];
}

export function useIBDStatus(market = 'US') {
  return useSWR<IBDStatusResponse>(`/api/ibd/status?market=${market}`, fetcher, { refreshInterval: 60000 });
}

export function useIBDDistributionDays(market = 'US', activeOnly = true) {
  return useSWR<IBDDistDaysResponse>(
    `/api/ibd/distribution-days?market=${market}&active_only=${activeOnly}`,
    fetcher,
    { refreshInterval: 60000 },
  );
}

export function useIBDHistory(market = 'US', days = 30) {
  return useSWR<IBDHistoryResponse>(
    `/api/ibd/history?market=${market}&days=${days}`,
    fetcher,
    { refreshInterval: 60000 },
  );
}
