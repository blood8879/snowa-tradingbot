import useSWR from 'swr';
import type { NearEntryAlertsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useNearEntryAlerts() {
  return useSWR<NearEntryAlertsResponse>(API.nearEntryAlerts, fetcher, {
    refreshInterval: 15_000,
  });
}
