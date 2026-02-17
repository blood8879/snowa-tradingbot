import useSWR from 'swr';
import type { LogsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useLogs(limit = 100, level = 'ALL') {
  return useSWR<LogsResponse>(API.logs(limit, level), fetcher, {
    refreshInterval: 15_000,
  });
}
