import { useMemo } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { PnlText } from '@/components/ui/PnlText';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { usePositions } from '@/hooks/usePositions';
import { useMarket } from '@/hooks/useMarket';
import { formatPrice, formatCurrency, currencySymbol } from '@/lib/format';
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

function getPositionColumns(market: string): Column<Position>[] {
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
        <span className="text-slate-300 tabular-nums">{formatPrice(row.avg_entry_price, market)}</span>
      ),
    },
    {
      key: 'current_price',
      header: '현재가',
      render: (row) =>
        row.current_price != null ? (
          <span className="text-slate-300 tabular-nums">{formatPrice(row.current_price, market)}</span>
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    {
      key: 'eval_amount',
      header: '평가금액',
      render: (row) =>
        row.eval_amount != null ? (
          <span className="text-slate-300 tabular-nums">{formatCurrency(row.eval_amount, market)}</span>
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    {
      key: 'current_stop_price',
      header: '손절가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatPrice(row.current_stop_price, market)}</span>
      ),
    },
    {
      key: 'donchian_lower_10',
      header: 'S1청산가',
      render: (row) =>
        row.donchian_lower_10 != null ? (
          <span className="text-slate-300 tabular-nums">{formatPrice(row.donchian_lower_10, market)}</span>
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    {
      key: 'donchian_lower_20',
      header: 'S2청산가',
      render: (row) =>
        row.donchian_lower_20 != null ? (
          <span className="text-slate-300 tabular-nums">{formatPrice(row.donchian_lower_20, market)}</span>
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    {
      key: 'unrealized_pnl',
      header: '손익',
      render: (row) =>
        row.unrealized_pnl != null ? (
          <PnlText value={row.unrealized_pnl} prefix={currencySymbol(market)} />
        ) : row.realized_pnl != null ? (
          <PnlText value={row.realized_pnl} prefix={currencySymbol(market)} />
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
    {
      key: 'unrealized_pnl_pct',
      header: '수익률',
      render: (row) =>
        row.unrealized_pnl_pct != null ? (
          <PnlText value={row.unrealized_pnl_pct} suffix="%" />
        ) : (
          <span className="text-slate-500">—</span>
        ),
    },
  ];
}

function ExpandedUnits({ position, market }: { position: Position; market: string }) {
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
              <th className="px-3 py-1.5 text-left font-medium">진입손절가</th>
              <th className="px-3 py-1.5 text-left font-medium">현재손절가</th>
              <th className="px-3 py-1.5 text-left font-medium">진입일</th>
            </tr>
          </thead>
          <tbody>
            {position.units.map((unit) => (
              <tr key={unit.id} className="border-t border-slate-700/20">
                <td className="px-3 py-1.5 text-slate-300">#{unit.unit_number}</td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  {formatPrice(unit.entry_price, market)}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  {unit.shares.toLocaleString()}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  {formatPrice(unit.entry_stop_price, market)}
                </td>
                <td className="px-3 py-1.5 text-slate-300 tabular-nums">
                  {formatPrice(unit.current_stop_price, market)}
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

function ExpandedBroker({ position, market }: { position: BrokerPosition; market: string }) {
  const costBasis = position.avg_price * position.quantity;
  return (
    <div className="bg-slate-800/30 rounded-lg p-3">
      <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
        보유 상세
      </h4>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <span className="text-slate-500">거래소</span>
          <p className="text-slate-300 mt-0.5">{position.exchange || '—'}</p>
        </div>
        <div>
          <span className="text-slate-500">보유수량</span>
          <p className="text-slate-300 tabular-nums mt-0.5">{position.quantity.toLocaleString()}주</p>
        </div>
        <div>
          <span className="text-slate-500">평균매입가</span>
          <p className="text-slate-300 tabular-nums mt-0.5">{formatPrice(position.avg_price, market)}</p>
        </div>
        <div>
          <span className="text-slate-500">현재가</span>
          <p className="text-slate-300 tabular-nums mt-0.5">{formatPrice(position.current_price, market)}</p>
        </div>
        <div>
          <span className="text-slate-500">매입금액</span>
          <p className="text-slate-300 tabular-nums mt-0.5">{formatCurrency(costBasis, market)}</p>
        </div>
        <div>
          <span className="text-slate-500">평가금액</span>
          <p className="text-slate-300 tabular-nums mt-0.5">{formatCurrency(position.eval_amount, market)}</p>
        </div>
        <div>
          <span className="text-slate-500">평가손익</span>
          <p className="mt-0.5"><PnlText value={position.pnl_amount} prefix={currencySymbol(market)} /></p>
        </div>
        <div>
          <span className="text-slate-500">수익률</span>
          <p className="mt-0.5"><PnlText value={position.pnl_pct} suffix="%" /></p>
        </div>
      </div>
      <p className="text-[10px] text-slate-600 mt-2">* 봇 미추적 포지션 — 유닛/손절가 정보 없음</p>
    </div>
  );
}

function getBrokerColumns(market: string): Column<BrokerPosition>[] {
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
        <span className="text-slate-300 tabular-nums">{formatPrice(row.avg_price, market)}</span>
      ),
    },
    {
      key: 'current_price',
      header: '현재가',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatPrice(row.current_price, market)}</span>
      ),
    },
    {
      key: 'eval_amount',
      header: '평가금액',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatCurrency(row.eval_amount, market)}</span>
      ),
    },
    {
      key: 'pnl_amount',
      header: '손익',
      render: (row) => <PnlText value={row.pnl_amount} prefix={currencySymbol(market)} />,
    },
    {
      key: 'pnl_pct',
      header: '수익률',
      render: (row) => <PnlText value={row.pnl_pct} suffix="%" />,
    },
  ];
}

export function PositionsPage() {
  const { market } = useMarket();
  const { data, isLoading, error } = usePositions(market);

  const positionCols = useMemo(() => getPositionColumns(market), [market]);
  const brokerCols = useMemo(() => getBrokerColumns(market), [market]);

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
          columns={positionCols}
          data={botPositions}
          rowKey={(row) => row.id}
          expandable={true}
          renderExpanded={(row) => <ExpandedUnits position={row} market={market} />}
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
              columns={brokerCols}
              data={brokerPositions}
              rowKey={(row) => row.ticker}
              expandable={true}
              renderExpanded={(row) => <ExpandedBroker position={row} market={market} />}
              emptyMessage="브로커 보유 종목이 없습니다"
            />
          </div>
        </>
      )}
    </div>
  );
}
