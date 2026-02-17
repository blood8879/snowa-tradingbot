import { useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { PnlText } from '@/components/ui/PnlText';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useJournal } from '@/hooks/useJournal';
import type { Column } from '@/components/ui/DataTable';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { JournalTrade } from '@/types/api';

function currentMonth(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = (d.getMonth() + 1).toString().padStart(2, '0');
  return `${y}-${m}`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`;
}

function closeReasonVariant(reason: string): BadgeVariant {
  switch (reason) {
    case 'stop_loss':
      return 'stop';
    case 'exit_signal':
      return 'exit';
    default:
      return 'default';
  }
}

const PIE_COLORS = ['#10B981', '#EF4444'];

const journalColumns: Column<JournalTrade>[] = [
  {
    key: 'ticker',
    header: '종목',
    render: (row) => <span className="font-medium text-slate-100">{row.ticker}</span>,
  },
  {
    key: 'system',
    header: '시스템',
    render: (row) => (
      <Badge variant={row.system.toLowerCase() === 's1' ? 's1' : 's2'}>
        {row.system}
      </Badge>
    ),
  },
  {
    key: 'opened_at',
    header: '진입일',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{formatDate(row.opened_at)}</span>
    ),
  },
  {
    key: 'closed_at',
    header: '청산일',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{formatDate(row.closed_at)}</span>
    ),
  },
  {
    key: 'close_reason',
    header: '청산사유',
    render: (row) => (
      <Badge variant={closeReasonVariant(row.close_reason)}>
        {row.close_reason}
      </Badge>
    ),
  },
  {
    key: 'avg_entry_price',
    header: '평균단가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.avg_entry_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'stop_price',
    header: '스톱가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.stop_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'total_shares',
    header: '수량',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{row.total_shares.toLocaleString()}</span>
    ),
  },
  {
    key: 'realized_pnl',
    header: '손익',
    render: (row) => <PnlText value={row.realized_pnl} />,
  },
];

export function JournalPage() {
  const [selectedMonth, setSelectedMonth] = useState(currentMonth);
  const { data, isLoading, error } = useJournal(selectedMonth);

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  const stats = data?.stats;
  const trades = data?.trades ?? [];

  const pieData = stats
    ? [
        { name: '승리', value: stats.winners },
        { name: '패배', value: stats.losers },
      ]
    : [];

  const monthlyPnlStr = stats
    ? `${stats.monthly_pnl >= 0 ? '+' : ''}$${stats.monthly_pnl.toLocaleString()}`
    : '—';

  return (
    <div className="space-y-6">
      <PageHeader title="매매일지" subtitle="월별 매매 성과 분석">
        <input
          type="month"
          value={selectedMonth}
          onChange={(e) => setSelectedMonth(e.target.value)}
          className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200"
        />
      </PageHeader>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <StatCard label="총 거래" value={stats?.total_trades ?? 0} />
        <StatCard
          label="승리"
          value={stats?.winners ?? 0}
          deltaType="positive"
        />
        <StatCard
          label="패배"
          value={stats?.losers ?? 0}
          deltaType="negative"
        />
        <StatCard
          label="승률"
          value={stats ? `${stats.win_rate_pct.toFixed(1)}%` : '—'}
        />
        <StatCard
          label="평균 수익"
          value={stats ? `$${stats.avg_win.toFixed(2)}` : '—'}
        />
        <StatCard
          label="평균 손실"
          value={stats ? `$${stats.avg_loss.toFixed(2)}` : '—'}
        />
        <StatCard
          label="손익비"
          value={stats ? stats.risk_reward_ratio.toFixed(2) : '—'}
        />
        <StatCard
          label="월간 손익"
          value={monthlyPnlStr}
          deltaType={
            stats
              ? stats.monthly_pnl > 0
                ? 'positive'
                : stats.monthly_pnl < 0
                  ? 'negative'
                  : 'neutral'
              : 'neutral'
          }
        />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {/* Win/Loss Pie */}
        <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
          <h3 className="text-sm font-medium text-slate-400 mb-4">승패 비율</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  strokeWidth={0}
                >
                  {pieData.map((_entry, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Legend
                  verticalAlign="bottom"
                  formatter={(value: string) => (
                    <span className="text-sm text-slate-300">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Equity Range */}
        <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
          <h3 className="text-sm font-medium text-slate-400 mb-4">자산 현황</h3>
          <div className="flex flex-col gap-6 mt-4">
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">최소 자산</span>
              <span className="text-lg font-semibold text-slate-100 tabular-nums">
                ${stats?.min_equity.toLocaleString() ?? '—'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">최대 자산</span>
              <span className="text-lg font-semibold text-slate-100 tabular-nums">
                ${stats?.max_equity.toLocaleString() ?? '—'}
              </span>
            </div>
            {/* Visual equity range bar */}
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>MIN</span>
                <span>MAX</span>
              </div>
              <div className="h-3 rounded-full bg-slate-700/60 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400"
                  style={{
                    width: stats && stats.max_equity > 0
                      ? `${Math.max(10, (stats.min_equity / stats.max_equity) * 100)}%`
                      : '0%',
                  }}
                />
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">최대 낙폭</span>
              <span className="text-lg font-semibold text-loss tabular-nums">
                {stats ? `${stats.max_drawdown_pct.toFixed(2)}%` : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Trades Table */}
      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">매매 내역</h3>
        <DataTable<JournalTrade>
          columns={journalColumns}
          data={trades}
          rowKey={(row) => `${row.ticker}-${row.opened_at}`}
          emptyMessage="이 달의 매매 기록이 없습니다"
        />
      </div>
    </div>
  );
}
