import { useState, useMemo } from 'react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { usePnl } from '@/hooks/usePnl';
import { useMarket } from '@/hooks/useMarket';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { DataTable } from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import { PnlText } from '@/components/ui/PnlText';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import type { PnlDataPoint } from '@/types/api';
import { formatCurrency, formatPnlValue, currencySymbol } from '@/lib/format';

const PERIODS = [
  { key: 'daily', label: '일간' },
  { key: 'weekly', label: '주간' },
  { key: 'monthly', label: '월간' },
] as const;

const TOOLTIP_STYLE = {
  backgroundColor: '#1e293b',
  border: '1px solid #334155',
  borderRadius: '8px',
};

function getColumns(market: string): Column<PnlDataPoint>[] {
  return [
    {
      key: 'period',
      header: '기간',
      render: (row) => <span className="text-slate-100">{row.period}</span>,
    },
    {
      key: 'start',
      header: '시작',
      render: (row) => <span className="text-slate-400">{row.start}</span>,
    },
    {
      key: 'end',
      header: '종료',
      render: (row) => <span className="text-slate-400">{row.end}</span>,
    },
    {
      key: 'pnl',
      header: '손익',
      render: (row) => <PnlText value={row.pnl} prefix={currencySymbol(market)} />,
    },
    {
      key: 'equity',
      header: '자산',
      render: (row) => (
        <span className="text-slate-300">
          {formatCurrency(row.equity, market)}
        </span>
      ),
    },
    {
      key: 'max_drawdown_pct',
      header: '최대낙폭',
      render: (row) => (
        <span className="text-loss">{row.max_drawdown_pct.toFixed(2)}%</span>
      ),
    },
    {
      key: 'entries',
      header: '진입',
      render: (row) => <span className="text-slate-300">{row.entries}</span>,
    },
    {
      key: 'exits',
      header: '청산',
      render: (row) => <span className="text-slate-300">{row.exits}</span>,
    },
    {
      key: 'stop_losses',
      header: '스톱',
      render: (row) => <span className="text-slate-300">{row.stop_losses}</span>,
    },
  ];
}

export function PnlPage() {
  const { market } = useMarket();
  const [period, setPeriod] = useState('daily');
  const { data, error, isLoading } = usePnl(period, market);
  const cols = useMemo(() => getColumns(market), [market]);

  if (isLoading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-loss">
        데이터를 불러오는 중 오류가 발생했습니다.
      </div>
    );
  }

  const summary = data?.summary;
  const points = data?.data ?? [];

  return (
    <div>
      <PageHeader title="손익분석" subtitle="기간별 손익 현황" />

      {/* Period Tabs */}
      <div className="flex gap-2 mb-6">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPeriod(p.key)}
            className={
              period === p.key
                ? 'px-4 py-1.5 text-sm rounded-lg transition-colors bg-blue-600 text-white'
                : 'px-4 py-1.5 text-sm rounded-lg transition-colors bg-slate-700/50 text-slate-400 hover:text-slate-200'
            }
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Stat Cards */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <StatCard
            label="총 손익"
            value={formatPnlValue(summary.total_pnl, market)}
            deltaType={
              summary.total_pnl > 0
                ? 'positive'
                : summary.total_pnl < 0
                  ? 'negative'
                  : 'neutral'
            }
          />
          <StatCard
            label="최대 자산"
            value={formatCurrency(summary.max_equity, market)}
          />
          <StatCard
            label="최대 낙폭"
            value={`${summary.max_drawdown_pct.toFixed(2)}%`}
            deltaType={summary.max_drawdown_pct > 0 ? 'negative' : 'neutral'}
          />
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {/* Equity Curve */}
        <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
          <h3 className="text-sm font-medium text-slate-300 mb-3">자산 곡선</h3>
          <ResponsiveContainer width="100%" height={256}>
            <AreaChart data={points}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis
                dataKey="period"
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#3b82f6"
                fill="url(#equityGradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* PnL Bars */}
        <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
          <h3 className="text-sm font-medium text-slate-300 mb-3">기간별 손익</h3>
          <ResponsiveContainer width="100%" height={256}>
            <BarChart data={points}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis
                dataKey="period"
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                {points.map((entry) => (
                  <Cell
                    key={entry.period}
                    fill={entry.pnl >= 0 ? '#10B981' : '#EF4444'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Data Table */}
      <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
        <DataTable<PnlDataPoint>
          columns={cols}
          data={points}
          rowKey={(row) => row.period}
          emptyMessage="손익 데이터가 없습니다"
        />
      </div>
    </div>
  );
}
