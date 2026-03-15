import useSWR from 'swr';
import type { TradesResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useTrades(limit = 50, offset = 0, market = 'US') {
  return useSWR<TradesResponse>(API.trades(limit, offset, market), fetcher);
}
