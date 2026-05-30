import useSWR from 'swr';
import { API } from '@/lib/api';
import { fetcher } from '@/lib/fetcher';
import type { AIReportStatusResponse } from '@/types/api';

export function useAIReportStatus() {
  return useSWR<AIReportStatusResponse>(API.aiReportStatus, fetcher, {
    refreshInterval: 60_000,
  });
}
