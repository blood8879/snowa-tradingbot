import { clsx } from 'clsx';

interface PnlTextProps {
  value: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function PnlText({
  value,
  prefix = '$',
  suffix = '',
  className,
}: PnlTextProps) {
  const sign = value > 0 ? '+' : '';
  const formatted = `${prefix}${sign}${value.toLocaleString()}${suffix}`;

  return (
    <span
      className={clsx(
        value > 0 && 'text-profit',
        value < 0 && 'text-loss',
        value === 0 && 'text-slate-400',
        className,
      )}
    >
      {formatted}
    </span>
  );
}
