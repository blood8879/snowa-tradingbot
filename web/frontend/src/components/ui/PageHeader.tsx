import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}

export function PageHeader({ title, subtitle, children }: PageHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
      <div className="min-w-0">
        <h1 className="text-xl sm:text-2xl font-bold truncate">{title}</h1>
        {subtitle && <p className="text-xs sm:text-sm text-slate-400 mt-1 break-words">{subtitle}</p>}
      </div>
      {children && <div className="w-full sm:w-auto">{children}</div>}
    </div>
  );
}
