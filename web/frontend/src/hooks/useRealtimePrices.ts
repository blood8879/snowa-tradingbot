import useSWR from 'swr';
import type { RealtimePricesResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useRealtimePrices(tickers: string[]) {
  const key = tickers.length > 0 ? API.realtimePrices(tickers) : null;

  return useSWR<RealtimePricesResponse>(key, fetcher, {
    refreshInterval: 15_000,
  });
}
