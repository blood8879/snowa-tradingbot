import useSWR from 'swr';
import type { MarketStatusResponse } from '@/types/api';
import { fetcher } from '@/lib/fetcher';
import { API } from '@/lib/api';

export function useMarketControl() {
  const { data, isLoading, mutate } = useSWR<MarketStatusResponse>(
    API.marketStatus,
    fetcher,
    { refreshInterval: 10_000 },
  );

  const toggleMarket = async (marketId: string, enabled: boolean) => {
    const res = await fetch(API.marketToggle(marketId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (!res.ok) throw new Error(res.statusText);
    await mutate();
  };

  return {
    markets: data?.markets ?? [],
    isLoading,
    toggleMarket,
  };
}
