import useSWR from 'swr';
import type { PnlResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function usePnl(period = 'daily', market = 'US') {
  return useSWR<PnlResponse>(API.pnl(period, market), fetcher);
}
