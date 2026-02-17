import useSWR from 'swr';
import type { PositionsResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function usePositions() {
  return useSWR<PositionsResponse>(API.positions, fetcher, {
    refreshInterval: 30_000,
  });
}
