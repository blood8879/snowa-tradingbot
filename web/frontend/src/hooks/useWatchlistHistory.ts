import useSWR from 'swr';
import type { WatchlistHistoryResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useWatchlistHistory(market: string, limit = 100) {
  return useSWR<WatchlistHistoryResponse>(
    API.watchlistHistory(market, limit),
    fetcher,
    {
      refreshInterval: 0,
      revalidateOnFocus: false,
    },
  );
}
