import { useMarket } from '@/hooks/useMarket';
import { clsx } from 'clsx';

const MARKETS = [
  { id: 'US' as const, label: 'US', flag: '🇺🇸' },
  { id: 'KR' as const, label: 'KR', flag: '🇰🇷' },
  { id: 'ALL' as const, label: '전체', flag: '🌐' },
] as const;

export function MarketSelector() {
  const { market, setMarket } = useMarket();

  return (
    <div className="px-3 py-2">
      <div className="flex rounded-lg bg-slate-800/50 p-0.5">
        {MARKETS.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMarket(m.id)}
            className={clsx(
              'flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md text-xs font-medium transition-colors',
              market === m.id
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'text-slate-400 hover:text-slate-300',
            )}
          >
            <span>{m.flag}</span>
            <span>{m.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
