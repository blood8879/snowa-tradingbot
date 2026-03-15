import useSWR from 'swr';
import type { JournalResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useJournal(month?: string, market = 'US') {
  return useSWR<JournalResponse>(API.journal(month, market), fetcher);
}
