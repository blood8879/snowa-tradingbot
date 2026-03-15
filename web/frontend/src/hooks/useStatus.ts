import useSWR from 'swr';
import type { StatusResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useStatus(market = 'US') {
  return useSWR<StatusResponse>(API.status(market), fetcher, {
    refreshInterval: 10_000,
  });
}
