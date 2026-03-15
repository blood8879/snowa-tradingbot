import useSWR from 'swr';
import type { NearEntryAlertsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useNearEntryAlerts(market = 'US') {
  return useSWR<NearEntryAlertsResponse>(API.nearEntryAlerts(market), fetcher, {
    refreshInterval: 15_000,
  });
}
