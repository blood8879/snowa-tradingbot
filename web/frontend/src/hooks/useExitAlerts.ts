import useSWR from 'swr';
import type { ExitAlertsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useExitAlerts(market = 'US') {
  return useSWR<ExitAlertsResponse>(API.nearExitAlerts(market), fetcher, {
    refreshInterval: 30_000,
  });
}
