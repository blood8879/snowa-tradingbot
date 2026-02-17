import { PageHeader } from '@/components/ui/PageHeader';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { PnlText } from '@/components/ui/PnlText';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { usePositions } from '@/hooks/usePositions';
import type { Column } from '@/components/ui/DataTable';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { Position, BrokerPosition } from '@/types/api';

function mapStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'open':
      return 'success';
    case 'closed':
      return 'default';
    default:
      return 'default';
  }
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`;
}

const positionColumns: Column<Position>[] = [
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
        {row.system.toUpperCase()}
      </Badge>
    ),
  },
  {
    key: 'status',
    header: '상태',
    render: (row) => (
      <Badge variant={mapStatusVariant(row.status)}>{row.status}</Badge>
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
    key: 'avg_entry_price',
    header: '평균단가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.avg_entry_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'total_cost',
    header: '총 비용',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.total_cost.toLocaleString()}</span>
    ),
  },
  {
    key: 'current_stop_price',
    header: '스톱가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.current_stop_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'realized_pnl',
    header: '손익',
    render: (row) =>
      row.realized_pnl != null ? (
        <PnlText value={row.realized_pnl} />
      ) : (
        <span className="text-slate-500">—</span>
      ),
  },
];

function ExpandedUnits({ position }: { position: Position }) {
  return (
    <div className="bg-slate-800/30 rounded-lg p-3">
      <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
        유닛 상세 ({position.units.length}개)
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500">
              <th className="px-3 py-1.5 text-left font-medium">유닛#</th>
              <th className="px-3 py-1.5 text-left font-medium">진입가</th>
              <th className="px-3 py-1.5 text-left font-medium">수량</th>
              <th className="px-3 py-1.5 text-left font-medium">진입스톱</th>
              <th className="px-3 py-1.5 text-left font-medium">현재스톱</th>
              <th className="px-3 py-1.5 text-left font-medium">진입일</th>
            </tr>
          </thead>
          <tbody>
            {position.units.map((unit) => (
              <tr key={unit.id} className="border-t border-slate-700/20">
                <td className="px-3 py-1.5 text-slate-300">#{unit.unit_number}</td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  ${unit.entry_price.toFixed(2)}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  {unit.shares.toLocaleString()}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  ${unit.entry_stop_price.toFixed(2)}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  ${unit.current_stop_price.toFixed(2)}
                </td>
                <td className="px-3 py-1.5 text-slate-400">
                  {formatDate(unit.entered_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const brokerColumns: Column<BrokerPosition>[] = [
  {
    key: 'ticker',
    header: '종목',
    render: (row) => <span className="font-medium text-slate-100">{row.ticker}</span>,
  },
  {
    key: 'exchange',
    header: '거래소',
    render: (row) => (
      <Badge variant="default">{row.exchange || '—'}</Badge>
    ),
  },
  {
    key: 'quantity',
    header: '수량',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">{row.quantity.toLocaleString()}</span>
    ),
  },
  {
    key: 'avg_price',
    header: '평균단가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.avg_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'current_price',
    header: '현재가',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.current_price.toFixed(2)}</span>
    ),
  },
  {
    key: 'eval_amount',
    header: '평가금액',
    render: (row) => (
      <span className="text-slate-300 tabular-nums">${row.eval_amount.toLocaleString()}</span>
    ),
  },
  {
    key: 'pnl_amount',
    header: '손익',
    render: (row) => <PnlText value={row.pnl_amount} />,
  },
  {
    key: 'pnl_pct',
    header: '수익률',
    render: (row) => <PnlText value={row.pnl_pct} suffix="%" />,
  },
];

export function PositionsPage() {
  const { data, isLoading, error } = usePositions();

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">포지션 데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  const botPositions = data?.positions ?? [];
  const brokerPositions = data?.broker_positions ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="포지션" subtitle="현재 보유 중인 포지션" />

      <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
        <DataTable<Position>
          columns={positionColumns}
          data={botPositions}
          rowKey={(row) => row.id}
          expandable={true}
          renderExpanded={(row) => <ExpandedUnits position={row} />}
          emptyMessage={brokerPositions.length > 0
            ? "봇에서 추적 중인 포지션이 없습니다"
            : "보유 중인 포지션이 없습니다"}
        />
      </div>

      {brokerPositions.length > 0 && (
        <>
          <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wide">
            브로커 보유 종목 (봇 미추적)
          </h3>
          <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
            <DataTable<BrokerPosition>
              columns={brokerColumns}
              data={brokerPositions}
              rowKey={(row) => row.ticker}
              emptyMessage="브로커 보유 종목이 없습니다"
            />
          </div>
        </>
      )}
    </div>
  );
}
