import { clsx } from 'clsx';

interface StatCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: 'positive' | 'negative' | 'neutral';
}

export function StatCard({ label, value, delta, deltaType }: StatCardProps) {
  return (
    <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
      <p className="text-xs text-slate-400 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-semibold text-slate-100 mt-1">{value}</p>
      {delta && (
        <p
          className={clsx(
            'text-xs mt-1',
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
