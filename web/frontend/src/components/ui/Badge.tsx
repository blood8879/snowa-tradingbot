import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export type BadgeVariant =
  | 'buy'
  | 'sell'
  | 's1'
  | 's2'
  | 'entry'
  | 'pyramid'
  | 'stop'
  | 'exit'
  | 'success'
  | 'danger'
  | 'default';

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  buy: 'bg-emerald-900/50 text-emerald-400 border-emerald-700',
  sell: 'bg-red-900/50 text-red-400 border-red-700',
  s1: 'bg-blue-900/50 text-blue-400 border-blue-700',
  s2: 'bg-purple-900/50 text-purple-400 border-purple-700',
  entry: 'bg-blue-900/50 text-blue-400 border-blue-700',
  pyramid: 'bg-purple-900/50 text-purple-400 border-purple-700',
  stop: 'bg-red-900/50 text-red-400 border-red-700',
  exit: 'bg-amber-900/50 text-amber-400 border-amber-700',
  success: 'bg-emerald-900/50 text-emerald-400 border-emerald-700',
  danger: 'bg-red-900/50 text-red-400 border-red-700',
  default: 'bg-slate-700/50 text-slate-300 border-slate-600',
};

interface BadgeProps {
  variant: BadgeVariant;
  children: ReactNode;
}

export function Badge({ variant, children }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex px-2 py-0.5 rounded-full text-xs font-medium border',
        VARIANT_CLASSES[variant],
      )}
    >
      {children}
    </span>
  );
}
