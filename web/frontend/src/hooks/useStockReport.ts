import useSWR from 'swr';
import { API } from '@/lib/api';
import { fetcher } from '@/lib/fetcher';
import type { StockReportResponse } from '@/types/api';

export function useStockReport(ticker: string | null, market = 'US') {
  const key = ticker ? API.stockReport(ticker, market) : null;
  return useSWR<StockReportResponse>(key, fetcher);
}

export async function generateStockReport(
  ticker: string,
  market = 'US',
): Promise<StockReportResponse> {
  const res = await fetch(API.generateStockReport(ticker, market), {
    method: 'POST',
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? res.statusText);
  }
  return (await res.json()) as StockReportResponse;
}
