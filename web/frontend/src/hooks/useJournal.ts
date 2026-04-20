import useSWR from 'swr';
import type { JournalResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export interface JournalRangeParams {
  month?: string;
  startMonth?: string;
  endMonth?: string;
  allTime?: boolean;
}

export function useJournal(params?: JournalRangeParams | string, market = 'US') {
  const opts: JournalRangeParams =
    typeof params === 'string' ? { month: params } : params ?? {};
  return useSWR<JournalResponse>(API.journal(opts, market), fetcher);
}
