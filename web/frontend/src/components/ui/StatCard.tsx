import { clsx } from 'clsx';
import type { ReactNode } from 'react';

interface StatCardProps {
  label: string;
  value: string | number;
  delta?: ReactNode;
  deltaType?: 'positive' | 'negative' | 'neutral';
}

export function StatCard({ label, value, delta, deltaType }: StatCardProps) {
  return (
    <div className="bg-panel rounded-xl p-3 sm:p-4 border border-slate-700/50 min-w-0">
      <p className="text-[10px] sm:text-xs text-slate-400 uppercase tracking-wide truncate">{label}</p>
      <p className="text-lg sm:text-2xl font-semibold text-slate-100 mt-1 tabular-nums break-all">{value}</p>
      {delta && (
        <p
          className={clsx(
            'text-xs mt-1 break-words',
            deltaType === 'positive' && 'text-profit',
            deltaType === 'negative' && 'text-loss',
            deltaType === 'neutral' && 'text-slate-400',
            !deltaType && 'text-slate-400',
          )}
        >
          {delta}
        </p>
      )}
    </div>
  );
}
