import { useState, useMemo } from 'react';
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
import { useMarket } from '@/hooks/useMarket';
import { formatPrice, formatCurrency, formatPnlValue, currencySymbol } from '@/lib/format';
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

function getJournalColumns(market: string): Column<JournalTrade>[] {
  return [
    {
      key: 'ticker',
      header: '종목',
      render: (row) => (
        <span className="font-medium text-slate-100">
          {row.ticker}
          {row.name && (
            <span className="ml-1.5 text-xs font-normal text-slate-400">{row.name}</span>
          )}
        </span>
      ),
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
        <span className="text-slate-300 tabular-nums">{formatPrice(row.avg_entry_price, market)}</span>
      ),
    },
    {
      key: 'stop_price',
      header: '손절가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatPrice(row.stop_price, market)}</span>
      ),
    },
    {
      key: 'exit_price',
      header: '체결가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatPrice(row.exit_price, market)}</span>
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
      key: 'holding_days',
      header: '보유일',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">
          {row.holding_days != null ? `${row.holding_days.toFixed(1)}일` : '—'}
        </span>
      ),
    },
    {
      key: 'realized_pnl',
      header: '손익',
      render: (row) => <PnlText value={row.realized_pnl} prefix={currencySymbol(market)} />,
    },
    {
      key: 'realized_pnl_pct',
      header: '수익률',
      render: (row) => {
        const v = row.realized_pnl_pct;
        const sign = v > 0 ? '+' : '';
        const color =
          v > 0 ? 'text-profit' : v < 0 ? 'text-loss' : 'text-slate-400';
        return (
          <span className={`tabular-nums font-medium ${color}`}>
            {`${sign}${v.toFixed(2)}%`}
          </span>
        );
      },
    },
  ];
}

type RangeMode = 'month' | 'range' | 'all';

export function JournalPage() {
  const { market } = useMarket();
  const [rangeMode, setRangeMode] = useState<RangeMode>('month');
  const [selectedMonth, setSelectedMonth] = useState(currentMonth);
  const [startMonth, setStartMonth] = useState(currentMonth);
  const [endMonth, setEndMonth] = useState(currentMonth);

  const journalParams = useMemo(() => {
    if (rangeMode === 'all') return { allTime: true };
    if (rangeMode === 'range') return { startMonth, endMonth };
    return { month: selectedMonth };
  }, [rangeMode, selectedMonth, startMonth, endMonth]);

  const { data, isLoading, error } = useJournal(journalParams, market);
  const journalCols = useMemo(() => getJournalColumns(market), [market]);

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
    ? formatPnlValue(stats.monthly_pnl, market)
    : '—';

  const rangeLabel =
    rangeMode === 'all'
      ? data?.start_month && data?.end_month
        ? `${data.start_month} ~ ${data.end_month} (전체)`
        : '전체 기간'
      : rangeMode === 'range'
        ? `${startMonth} ~ ${endMonth}`
        : selectedMonth;

  const modeBtnClass = (active: boolean) =>
    `px-3 py-1.5 text-sm rounded-lg border transition ${
      active
        ? 'bg-blue-500/20 border-blue-500 text-blue-200'
        : 'bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700'
    }`;

  const periodPnlLabel = rangeMode === 'month' ? '월간 손익' : '기간 손익';

  return (
    <div className="space-y-6">
      <PageHeader title="매매일지" subtitle={`매매 성과 분석 · ${rangeLabel}`}>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setRangeMode('month')}
              className={modeBtnClass(rangeMode === 'month')}
            >
              월별
            </button>
            <button
              type="button"
              onClick={() => setRangeMode('range')}
              className={modeBtnClass(rangeMode === 'range')}
            >
              기간
            </button>
            <button
              type="button"
              onClick={() => setRangeMode('all')}
              className={modeBtnClass(rangeMode === 'all')}
            >
              전체
            </button>
          </div>
          {rangeMode === 'month' && (
            <input
              type="month"
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200"
            />
          )}
          {rangeMode === 'range' && (
            <div className="flex items-center gap-1.5">
              <input
                type="month"
                value={startMonth}
                max={endMonth}
                onChange={(e) => setStartMonth(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200"
              />
              <span className="text-slate-500 text-sm">~</span>
              <input
                type="month"
                value={endMonth}
                min={startMonth}
                onChange={(e) => setEndMonth(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200"
              />
            </div>
          )}
        </div>
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
          value={stats ? `${currencySymbol(market)}${stats.avg_win.toFixed(2)}` : '—'}
        />
        <StatCard
          label="평균 손실"
          value={stats ? `${currencySymbol(market)}${stats.avg_loss.toFixed(2)}` : '—'}
        />
        <StatCard
          label="손익비"
          value={stats ? stats.risk_reward_ratio.toFixed(2) : '—'}
        />
        <StatCard
          label={periodPnlLabel}
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
        <StatCard
          label="평균 보유일"
          value={stats ? `${stats.avg_holding_days.toFixed(1)}일` : '—'}
        />
        <StatCard
          label="승리 평균 보유일"
          value={stats ? `${stats.avg_win_holding_days.toFixed(1)}일` : '—'}
          deltaType="positive"
        />
        <StatCard
          label="패배 평균 보유일"
          value={stats ? `${stats.avg_loss_holding_days.toFixed(1)}일` : '—'}
          deltaType="negative"
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
                {stats ? formatCurrency(stats.min_equity, market) : '—'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">최대 자산</span>
              <span className="text-lg font-semibold text-slate-100 tabular-nums">
                {stats ? formatCurrency(stats.max_equity, market) : '—'}
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
          columns={journalCols}
          data={trades}
          rowKey={(row) => `${row.ticker}-${row.opened_at}`}
          emptyMessage="해당 기간의 매매 기록이 없습니다"
        />
      </div>
    </div>
  );
}
