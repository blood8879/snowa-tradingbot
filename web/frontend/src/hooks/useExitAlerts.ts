import useSWR from 'swr';
import type { ExitAlertsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useExitAlerts() {
  return useSWR<ExitAlertsResponse>(API.nearExitAlerts, fetcher, {
    refreshInterval: 30_000,
  });
}
