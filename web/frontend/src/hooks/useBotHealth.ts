import useSWR from 'swr';
import type { BotHealthResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useBotHealth() {
  return useSWR<BotHealthResponse>(API.botHealth, fetcher, {
    refreshInterval: 10_000,
  });
}
