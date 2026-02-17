import React, { useMemo } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useExitAlerts } from '@/hooks/useExitAlerts';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { ExitAlert } from '@/types/api';

interface ExitAlertColumn {
  key: string;
  header: string;
  render: (row: ExitAlert) => React.ReactNode;
}

function formatPrice(value: number | null): string {
  if (value == null) return '-';
  return `$${value.toFixed(2)}`;
}

function getExitLevelBadgeVariant(level: ExitAlert['exit_level']): BadgeVariant {
  switch (level) {
    case 'critical':
      return 'danger';
    case 'warning':
      return 'exit';
    case 'safe':
      return 'success';
  }
}

function getExitLevelLabel(level: ExitAlert['exit_level']): string {
  switch (level) {
    case 'critical':
      return '위험';
    case 'warning':
      return '경고';
    case 'safe':
      return '안전';
  }
}

function getRowHighlight(level: ExitAlert['exit_level']): string {
  switch (level) {
    case 'critical':
      return 'bg-red-950/20';
    case 'warning':
      return 'bg-amber-950/20';
    default:
      return '';
  }
}

function getProximityColor(level: ExitAlert['exit_level']): string {
  switch (level) {
    case 'critical':
      return 'text-red-400';
    case 'warning':
      return 'text-amber-400';
    case 'safe':
      return 'text-emerald-400';
  }
}

function getColumns(): ExitAlertColumn[] {
  return [
    {
      key: 'ticker',
      header: '종목',
      render: (row) => (
        <span className="font-semibold text-slate-100">{row.ticker}</span>
      ),
    },
    {
      key: 'entry_price',
      header: '매입가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {formatPrice(row.entry_price)}
        </span>
      ),
    },
    {
      key: 'current_price',
      header: '현재가',
      render: (row) => (
        <span className="text-slate-200 tabular-nums font-medium">
          {formatPrice(row.current_price)}
        </span>
      ),
    },
    {
      key: 'unrealized_pnl_pct',
      header: '손익률',
      render: (row) => {
        const color = row.unrealized_pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400';
        return (
          <span className={`tabular-nums font-medium ${color}`}>
            {row.unrealized_pnl_pct >= 0 ? '+' : ''}{row.unrealized_pnl_pct.toFixed(2)}%
          </span>
        );
      },
    },
    {
      key: 'system',
      header: '시스템',
      render: (row) => {
        const variant: BadgeVariant = row.system === 'S1' ? 's1' : 's2';
        return <Badge variant={variant}>{row.system}</Badge>;
      },
    },
    {
      key: 'donchian_lower_10',
      header: 'S1 청산가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {formatPrice(row.donchian_lower_10)}
        </span>
      ),
    },
    {
      key: 'donchian_lower_20',
      header: 'S2 청산가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {formatPrice(row.donchian_lower_20)}
        </span>
      ),
    },
    {
      key: 'exit_proximity_pct',
      header: '근접도',
      render: (row) => (
        <span className={`tabular-nums font-medium ${getProximityColor(row.exit_level)}`}>
          {row.exit_proximity_pct.toFixed(2)}%
        </span>
      ),
    },
    {
      key: 'exit_level',
      header: '상태',
      render: (row) => (
        <Badge variant={getExitLevelBadgeVariant(row.exit_level)}>
          {getExitLevelLabel(row.exit_level)}
        </Badge>
      ),
    },
  ];
}

export function ExitAlertsPage() {
  const { data, isLoading, error } = useExitAlerts();

  const columns = useMemo(() => getColumns(), []);

  const alerts = data?.alerts ?? [];

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">청산 알림 데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="청산 알림" subtitle="보유 종목 청산 근접도 모니터링" />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="보유 종목"
          value={data?.total ?? 0}
        />
        <StatCard
          label="청산 경고"
          value={data?.warning_count ?? 0}
          delta={
            data && data.warning_count > 0
              ? `${data.warning_count}개 종목`
              : undefined
          }
          deltaType={
            data && data.warning_count > 0 ? 'negative' : 'neutral'
          }
        />
        <StatCard
          label="청산 위험"
          value={data?.critical_count ?? 0}
          delta={
            data && data.critical_count > 0
              ? `${data.critical_count}개 종목`
              : undefined
          }
          deltaType={
            data && data.critical_count > 0 ? 'negative' : 'neutral'
          }
        />
      </div>

      <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-800/50">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wide"
                  >
                    {col.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-12 text-center text-sm text-slate-400">
                    보유 중인 포지션이 없습니다
                  </td>
                </tr>
              ) : (
                alerts.map((row) => (
                  <tr
                    key={row.ticker}
                    className={`border-b border-slate-700/30 hover:bg-slate-800/30 transition-colors ${getRowHighlight(row.exit_level)}`}
                  >
                    {columns.map((col) => (
                      <td key={col.key} className="px-4 py-3 text-sm">
                        {col.render(row)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
