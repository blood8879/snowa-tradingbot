import { useState } from 'react';
import type { ReactNode } from 'react';
import { useTrades } from '@/hooks/useTrades';
import { PageHeader } from '@/components/ui/PageHeader';
import { DataTable } from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import type { BadgeVariant } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import type { Trade } from '@/types/api';

const PAGE_SIZE = 20;

const CONTEXT_LABELS: Record<string, string> = {
  type: '유형',
  system: '시스템',
  breakout_level: '돌파가',
  atr: 'ATR(N)',
  stop_price: '스톱가',
  risk_per_share: '리스크/주',
  market_filter: '시장필터',
  rs_rating: 'RS등급',
  composite_score: '종합점수',
  account_equity: '계좌자산',
  position_size_pct: '포지션비중',
  unit_number: '유닛번호',
  new_stop: '신규스톱',
  prev_stop: '이전스톱',
  pyramid_interval: '피라미드간격',
  trigger_price: '트리거가',
  avg_entry_price: '평균단가',
  atr_at_entry: '진입ATR',
  units_held: '보유유닛',
  total_shares: '총수량',
  loss_pct: '손실률',
  exit_level: '청산수준',
  exit_reason: '청산사유',
  pnl_pct: '수익률',
  error: '오류',
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function getSideVariant(side: string): BadgeVariant {
  const s = side.toUpperCase();
  if (s === 'BUY') return 'buy';
  if (s === 'SELL') return 'sell';
  return 'default';
}

function getStatusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase();
  if (s === 'filled') return 'success';
  if (s === 'rejected') return 'danger';
  if (s === 'cancelled') return 'exit';
  return 'default';
}

function renderExpanded(row: Trade): ReactNode {
  if (!row.notes) return null;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(row.notes) as Record<string, unknown>;
  } catch {
    return <p className="text-xs text-slate-400">{row.notes}</p>;
  }

  const entries = Object.entries(parsed);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
      {entries.map(([key, val]) => (
        <div key={key}>
          <span className="text-xs text-slate-500">
            {CONTEXT_LABELS[key] ?? key}
          </span>
          <p className="text-xs text-slate-300">{String(val)}</p>
        </div>
      ))}
    </div>
  );
}

const columns: Column<Trade>[] = [
  {
    key: 'created_at',
    header: '시간',
    render: (row) => (
      <span className="text-slate-400">{formatTime(row.created_at)}</span>
    ),
  },
  {
    key: 'ticker',
    header: '종목',
    render: (row) => (
      <span className="font-medium text-slate-100">{row.ticker}</span>
    ),
  },
  {
    key: 'side',
    header: '매매',
    render: (row) => (
      <Badge variant={getSideVariant(row.side)}>{row.side}</Badge>
    ),
  },
  {
    key: 'order_type',
    header: '유형',
    render: (row) => <span className="text-slate-300">{row.order_type}</span>,
  },
  {
    key: 'requested_shares',
    header: '주문수량',
    render: (row) => (
      <span className="text-slate-300">
        {row.requested_shares.toLocaleString()}
      </span>
    ),
  },
  {
    key: 'requested_price',
    header: '주문가',
    render: (row) => (
      <span className="text-slate-300">
        ${row.requested_price.toFixed(2)}
      </span>
    ),
  },
  {
    key: 'filled_shares',
    header: '체결수량',
    render: (row) => (
      <span className="text-slate-300">
        {row.filled_shares.toLocaleString()}
      </span>
    ),
  },
  {
    key: 'filled_price',
    header: '체결가',
    render: (row) => (
      <span className="text-slate-300">
        {row.filled_price != null ? `$${row.filled_price.toFixed(2)}` : '—'}
      </span>
    ),
  },
  {
    key: 'status',
    header: '상태',
    render: (row) => (
      <Badge variant={getStatusVariant(row.status)}>{row.status}</Badge>
    ),
  },
];

export function TradesPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useTrades(PAGE_SIZE, offset);

  if (isLoading) return <LoadingSpinner />;

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-loss">
        데이터를 불러오는 중 오류가 발생했습니다.
      </div>
    );
  }

  const trades = data?.trades ?? [];
  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeader title="매매내역" subtitle="주문 실행 이력" />

      <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
        <DataTable<Trade>
          columns={columns}
          data={trades}
          rowKey={(row) => row.id}
          expandable
          renderExpanded={renderExpanded}
          emptyMessage="매매내역이 없습니다"
        />
      </div>

      {total > 0 && (
        <div className="flex justify-between items-center mt-4">
          <span className="text-sm text-slate-400">
            총 {total}건 중 {offset + 1}~{Math.min(offset + PAGE_SIZE, total)}건
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
              className="px-3 py-1.5 text-sm rounded-lg bg-slate-700/50 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
            >
              이전
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
              className="px-3 py-1.5 text-sm rounded-lg bg-slate-700/50 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
            >
              다음
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
