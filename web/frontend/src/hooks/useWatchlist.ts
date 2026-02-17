import useSWR from 'swr';
import type { WatchlistResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useWatchlist() {
  return useSWR<WatchlistResponse>(API.watchlist, fetcher);
}
