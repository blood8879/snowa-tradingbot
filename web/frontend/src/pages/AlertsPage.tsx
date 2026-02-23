import React, { useMemo } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useNearEntryAlerts } from '@/hooks/useAlerts';
import { useRealtimePrices } from '@/hooks/useRealtimePrices';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { NearEntryAlert, RealtimePricesResponse } from '@/types/api';

interface AlertColumn {
  key: string;
  header: string;
  render: (row: NearEntryAlert, realtimeData?: RealtimePricesResponse) => React.ReactNode;
}

function formatPrice(value: number | null): string {
  if (value == null) return '-';
  return `$${value.toFixed(2)}`;
}

function getProximityColor(alert_level: NearEntryAlert['alert_level']): string {
  switch (alert_level) {
    case 'breakout':
      return 'text-emerald-400';
    case 'imminent':
      return 'text-amber-400';
    case 'close':
      return 'text-yellow-400';
    case 'normal':
      return 'text-slate-400';
  }
}

function getAlertBadgeVariant(alert_level: NearEntryAlert['alert_level']): BadgeVariant {
  switch (alert_level) {
    case 'breakout':
      return 'buy';
    case 'imminent':
      return 'exit';
    case 'close':
      return 's2';
    case 'normal':
      return 'default';
  }
}

function getAlertBadgeLabel(alert_level: NearEntryAlert['alert_level']): string {
  switch (alert_level) {
    case 'breakout':
      return '돌파!';
    case 'imminent':
      return '임박';
    case 'close':
      return '근접';
    case 'normal':
      return '대기';
  }
}

function getRowHighlight(alert_level: NearEntryAlert['alert_level']): string {
  switch (alert_level) {
    case 'breakout':
      return 'bg-emerald-950/20';
    case 'imminent':
      return 'bg-amber-950/20';
    default:
      return '';
  }
}

/** Recompute alert_level & signal_type using a real-time price. */
function recomputeAlert(
  row: NearEntryAlert,
  realtimePrice: number | undefined,
): { alertLevel: NearEntryAlert['alert_level']; signalType: string; proximity20: number; proximity55: number | null } {
  const price = realtimePrice ?? row.latest_price;
  const d20 = row.donchian_upper_20;
  const d55 = row.donchian_upper_55;

  const proximity20 = d20 > 0 ? ((d20 - price) / d20) * 100 : row.proximity_pct_20;
  const proximity55 = d55 != null && d55 > 0 ? ((d55 - price) / d55) * 100 : null;

  const broken20 = price >= d20;
  const broken55 = d55 != null && price >= d55;

  let signalType = 'none';
  if (broken20 && broken55) signalType = 'S1+S2';
  else if (broken55) signalType = 'S2';
  else if (broken20) signalType = 'S1';
  else if (proximity20 <= 5.0) signalType = 'S1';
  else if (proximity55 != null && proximity55 <= 5.0) signalType = 'S2';

  let alertLevel: NearEntryAlert['alert_level'] = 'normal';
  if (broken20 || broken55) alertLevel = 'breakout';
  else if (proximity20 <= 2.0) alertLevel = 'imminent';
  else if (proximity20 <= 5.0) alertLevel = 'close';

  return { alertLevel, signalType, proximity20, proximity55 };
}

function getColumns(): AlertColumn[] {
  return [
    {
      key: 'ticker',
      header: '종목',
      render: (row) => (
        <span className="font-semibold text-slate-100">{row.ticker}</span>
      ),
    },
    {
      key: 'latest_price',
      header: '현재가',
      render: (row, realtimeData) => {
        const rt = realtimeData?.prices[row.ticker];
        const price = rt?.price ?? row.latest_price;
        return (
          <span className="text-slate-200 tabular-nums font-medium">
            {formatPrice(price)}
          </span>
        );
      },
    },
    {
      key: 'signal_type',
      header: '신호',
      render: (row, realtimeData) => {
        const rt = realtimeData?.prices[row.ticker];
        const { signalType } = recomputeAlert(row, rt?.price);
        const color =
          signalType === 'S1+S2'
            ? 'text-emerald-400'
            : signalType === 'S2'
              ? 'text-cyan-400'
              : signalType === 'S1'
                ? 'text-amber-400'
                : 'text-slate-500';
        return (
          <span className={`font-semibold text-xs ${color}`}>
            {signalType === 'none' ? '-' : signalType}
          </span>
        );
      },
    },
    {
      key: 'donchian_upper_20',
      header: 'S1 돌파가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {formatPrice(row.donchian_upper_20)}
        </span>
      ),
    },
    {
      key: 'donchian_upper_55',
      header: 'S2 돌파가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {row.donchian_upper_55 != null ? formatPrice(row.donchian_upper_55) : '-'}
        </span>
      ),
    },
    {
      key: 'proximity_pct_20',
      header: '근접도',
      render: (row, realtimeData) => {
        const rt = realtimeData?.prices[row.ticker];
        const { alertLevel, proximity20 } = recomputeAlert(row, rt?.price);
        return (
          <span className={`tabular-nums font-medium ${getProximityColor(alertLevel)}`}>
            {proximity20.toFixed(2)}%
          </span>
        );
      },
    },
    {
      key: 'alert_level',
      header: '알림',
      render: (row, realtimeData) => {
        const rt = realtimeData?.prices[row.ticker];
        const { alertLevel } = recomputeAlert(row, rt?.price);
        return (
          <Badge variant={getAlertBadgeVariant(alertLevel)}>
            {getAlertBadgeLabel(alertLevel)}
          </Badge>
        );
      },
    },
    {
      key: 'rs_rating',
      header: 'RS등급',
      render: (row) => {
        const rs = row.rs_rating;
        const color =
          rs != null && rs >= 90
            ? 'text-emerald-400'
            : rs != null && rs >= 80
              ? 'text-green-400'
              : 'text-slate-300';
        return (
          <span className={`tabular-nums font-medium ${color}`}>
            {rs ?? '-'}
          </span>
        );
      },
    },
    {
      key: 'sma_20',
      header: 'SMA20',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {formatPrice(row.sma_20)}
        </span>
      ),
    },
    {
      key: 'latest_financial_date',
      header: '재무 기준일',
      render: (row) => {
        if (!row.latest_financial_date) return <span className="text-slate-500">—</span>;
        const parts = row.latest_financial_date.split('-');
        const formatted = `${parts[0].slice(2)}/${parts[1]}/${parts[2]}`;
        return <span className="text-slate-400 text-xs tabular-nums">{formatted}</span>;
      },
    },
  ];
}

export function AlertsPage() {
  const { data, isLoading, error } = useNearEntryAlerts();

  const columns = useMemo(() => getColumns(), []);

  const alerts = data?.alerts ?? [];
  const tickers = useMemo(() => alerts.map((a) => a.ticker), [alerts]);
  const { data: realtimeData } = useRealtimePrices(tickers);

  // Recompute counts using real-time prices
  const { imminentCount, breakoutCount } = useMemo(() => {
    let imm = 0;
    let brk = 0;
    for (const a of alerts) {
      const rt = realtimeData?.prices[a.ticker];
      const { alertLevel } = recomputeAlert(a, rt?.price);
      if (alertLevel === 'imminent') imm++;
      if (alertLevel === 'breakout') brk++;
    }
    return { imminentCount: imm, breakoutCount: brk };
  }, [alerts, realtimeData]);

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">알림 데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="진입 알림" subtitle="돌파 근접 종목 모니터링" />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="감시 종목"
          value={data?.total ?? 0}
        />
        <StatCard
          label="돌파 임박"
          value={imminentCount}
          delta={
            imminentCount > 0
              ? `${imminentCount}개 종목`
              : undefined
          }
          deltaType={
            imminentCount > 0 ? 'positive' : 'neutral'
          }
        />
        <StatCard
          label="돌파 발생"
          value={breakoutCount}
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
                    감시 중인 알림 종목이 없습니다
                  </td>
                </tr>
              ) : (
                alerts.map((row) => {
                  const rt = realtimeData?.prices[row.ticker];
                  const { alertLevel: rowAlertLevel } = recomputeAlert(row, rt?.price);
                  return (
                  <tr
                    key={row.ticker}
                    className={`border-b border-slate-700/30 hover:bg-slate-800/30 transition-colors ${getRowHighlight(rowAlertLevel)}`}
                  >
                    {columns.map((col) => (
                      <td key={col.key} className="px-4 py-3 text-sm">
                        {col.render(row, realtimeData)}
                      </td>
                    ))}
                  </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
