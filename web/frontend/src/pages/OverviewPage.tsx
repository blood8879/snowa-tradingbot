import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useStatus } from '@/hooks/useStatus';
import { useTrades } from '@/hooks/useTrades';
import type { Column } from '@/components/ui/DataTable';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { Trade } from '@/types/api';

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function mapTradeStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'filled':
      return 'success';
    case 'pending':
    case 'submitted':
      return 'default';
    case 'cancelled':
    case 'rejected':
      return 'danger';
    default:
      return 'default';
  }
}

const tradeColumns: Column<Trade>[] = [
  {
    key: 'time',
    header: '시간',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{formatTime(row.created_at)}</span>
    ),
  },
  {
    key: 'ticker',
    header: '종목',
    render: (row) => <span className="font-medium text-slate-100">{row.ticker}</span>,
  },
  {
    key: 'side',
    header: '매매',
    render: (row) => (
      <Badge variant={row.side.toLowerCase() === 'buy' ? 'buy' : 'sell'}>
        {row.side}
      </Badge>
    ),
  },
  {
    key: 'shares',
    header: '수량',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{row.requested_shares.toLocaleString()}</span>
    ),
  },
  {
    key: 'price',
    header: '가격',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.requested_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'status',
    header: '상태',
    render: (row) => (
      <Badge variant={mapTradeStatusVariant(row.status)}>{row.status}</Badge>
    ),
  },
];

export function OverviewPage() {
  const { data: status, isLoading: statusLoading, error: statusError } = useStatus();
  const { data: trades, isLoading: tradesLoading, error: tradesError } = useTrades(5, 0);

  const chartData = useMemo(() => {
    if (!status) return [];
    return [
      { label: '현재', equity: status.account_equity },
    ];
  }, [status]);

  if (statusLoading || tradesLoading) {
    return <LoadingSpinner />;
  }

  if (statusError || tradesError) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="대시보드" subtitle="SNOWA 트레이딩 봇 실시간 현황" />

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="계좌 자산"
          value={status ? `$${status.account_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
          delta={
            status
              ? `현금 $${status.cash_balance.toLocaleString(undefined, { maximumFractionDigits: 0 })} / 주식 $${status.positions_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              : undefined
          }
          deltaType="neutral"
        />
        <StatCard
          label="포지션"
          value={status ? `${status.positions}개` : '—'}
        />
        <StatCard
          label="유닛"
          value={status ? `${status.units}개` : '—'}
        />
        <StatCard
          label="시장 필터"
          value={status?.market_filter ?? '—'}
          delta={
            status?.spy?.close && status?.spy?.sma200
              ? `SPY $${status.spy.close.toFixed(0)} / SMA200 $${status.spy.sma200.toFixed(0)}`
              : status?.market_filter_pass ? '통과' : '미통과'
          }
          deltaType={status?.market_filter_pass ? 'positive' : 'negative'}
        />
        <StatCard
          label="모드"
          value={status?.mode?.toUpperCase() ?? '—'}
        />
      </div>

      {/* Equity Curve */}
      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">자산 곡선</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="label"
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
              />
              <YAxis
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  color: '#f1f5f9',
                }}
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="url(#equityGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Trades */}
      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">최근 거래</h3>
        <DataTable<Trade>
          columns={tradeColumns}
          data={trades?.trades ?? []}
          rowKey={(row) => row.id}
          emptyMessage="최근 거래가 없습니다"
        />
      </div>
    </div>
  );
}
