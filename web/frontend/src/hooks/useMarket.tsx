import { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';

type Market = 'US' | 'KR' | 'ALL';

interface MarketContextType {
  market: Market;
  setMarket: (market: Market) => void;
  isUS: boolean;
  isKR: boolean;
  isAll: boolean;
  currencySymbol: string;
}

const MarketContext = createContext<MarketContextType | null>(null);

export function MarketProvider({ children }: { children: ReactNode }) {
  const [market, setMarketState] = useState<Market>('US');

  const setMarket = useCallback((m: Market) => {
    setMarketState(m);
  }, []);

  const value: MarketContextType = {
    market,
    setMarket,
    isUS: market === 'US' || market === 'ALL',
    isKR: market === 'KR' || market === 'ALL',
    isAll: market === 'ALL',
    currencySymbol: market === 'KR' ? '₩' : '$',
  };

  return (
    <MarketContext.Provider value={value}>
      {children}
    </MarketContext.Provider>
  );
}

export function useMarket(): MarketContextType {
  const ctx = useContext(MarketContext);
  if (!ctx) {
    throw new Error('useMarket must be used within a MarketProvider');
  }
  return ctx;
}
