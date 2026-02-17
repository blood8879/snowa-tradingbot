import useSWR from 'swr';
import type { StatusResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useStatus() {
  return useSWR<StatusResponse>(API.status, fetcher, {
    refreshInterval: 10_000,
  });
}
