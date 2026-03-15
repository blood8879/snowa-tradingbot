import useSWR from 'swr';
import type { DiaryResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useDiary(ticker?: string, limit = 50, offset = 0, market = 'US') {
  return useSWR<DiaryResponse>(API.diary(ticker, limit, offset, market), fetcher);
}
