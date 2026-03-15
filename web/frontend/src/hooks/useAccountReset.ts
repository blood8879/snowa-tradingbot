import { useState } from 'react';
import { useSWRConfig } from 'swr';
import type { AccountResetResponse } from '@/types/api';
import { API } from '@/lib/api';

export function useAccountReset() {
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { mutate } = useSWRConfig();

  const resetAccount = async (): Promise<AccountResetResponse | null> => {
    setIsResetting(true);
    setError(null);
    try {
      const res = await fetch(API.accountReset, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? res.statusText);
      }
      const data: AccountResetResponse = await res.json();

      // Revalidate all cached data
      await mutate(() => true, undefined, { revalidate: true });

      return data;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setError(msg);
      return null;
    } finally {
      setIsResetting(false);
    }
  };

  return { resetAccount, isResetting, error };
}
