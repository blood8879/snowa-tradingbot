import { useState, useMemo, useCallback } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useWatchlist } from '@/hooks/useWatchlist';
import { useRealtimePrices } from '@/hooks/useRealtimePrices';
import type { Column } from '@/components/ui/DataTable';
import type { WatchlistStock, RealtimePricesResponse } from '@/types/api';

function formatPct(value: number | null): string {
  if (value == null) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

function formatPrice(value: number | null): string {
  if (value == null) return '—';
  return `$${value.toFixed(2)}`;
}

function formatVolume(value: number | null): string {
  if (value == null) return '—';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return value.toLocaleString();
}

function getPctColorClass(value: number | null): string {
  if (value == null) return 'text-slate-400';
  if (value >= 0.5) return 'text-emerald-400';
  if (value >= 0.25) return 'text-green-400';
  return 'text-slate-300';
}

function getColumns(realtimeData?: RealtimePricesResponse): Column<WatchlistStock>[] {
  return [
    {
      key: 'ticker',
      header: '종목',
      sortable: true,
      render: (row) => <span className="font-semibold text-slate-100">{row.ticker}</span>,
    },
    {
      key: 'latest_price',
      header: '현재가',
      sortable: true,
      render: (row) => {
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
      key: 'quarterly_eps_growth',
      header: 'EPS성장(Q)',
      sortable: true,
      render: (row) => (
        <span className={`tabular-nums font-medium ${getPctColorClass(row.quarterly_eps_growth)}`}>
          {formatPct(row.quarterly_eps_growth)}
        </span>
      ),
    },
    {
      key: 'annual_eps_cagr',
      header: 'EPS CAGR(Y)',
      sortable: true,
      render: (row) => (
        <span className={`tabular-nums font-medium ${getPctColorClass(row.annual_eps_cagr)}`}>
          {formatPct(row.annual_eps_cagr)}
        </span>
      ),
    },
    {
      key: 'rs_rating',
      header: 'RS등급',
      sortable: true,
      render: (row) => {
        const rs = row.rs_rating;
        const color = rs != null && rs >= 90 ? 'text-emerald-400' : rs != null && rs >= 80 ? 'text-green-400' : 'text-slate-300';
        return <span className={`tabular-nums font-medium ${color}`}>{rs ?? '—'}</span>;
      },
    },
    {
      key: 'n_value',
      header: 'N값',
      sortable: true,
      render: (row) => (
        <span className="text-amber-300 tabular-nums font-medium">
          {row.n_value != null ? `$${row.n_value.toFixed(2)}` : '—'}
        </span>
      ),
    },
    {
      key: 'custom_composite_score',
      header: '점수',
      sortable: true,
      render: (row) => (
        <span className="text-slate-200 tabular-nums font-medium">
          {row.custom_composite_score?.toFixed(0) ?? '—'}
        </span>
      ),
    },
    {
      key: 'realtime_volume',
      header: '실시간 거래량',
      sortable: false,
      render: (row) => {
        const rt = realtimeData?.prices[row.ticker];
        const vol = rt?.volume;
        const avg50 = row.avg_volume_50d;
        const ratio = vol != null && avg50 != null && avg50 > 0 ? vol / avg50 : null;
        const ratioColor = ratio != null && ratio >= 1.5 ? 'text-emerald-400' : ratio != null && ratio >= 1.0 ? 'text-green-400' : 'text-slate-300';
        return (
          <span className="tabular-nums">
            <span className="text-slate-200">{vol != null ? formatVolume(vol) : '—'}</span>
            {ratio != null && (
              <span className={`ml-1 text-xs ${ratioColor}`}>
                ({ratio.toFixed(1)}x)
              </span>
            )}
          </span>
        );
      },
    },
    {
      key: 'avg_volume_50d',
      header: '50일 평균',
      sortable: true,
      render: (row) => (
        <span className="text-slate-400 tabular-nums">
          {formatVolume(row.avg_volume_50d)}
        </span>
      ),
    },
    {
      key: 'minervini_pass',
      header: '미너비니',
      render: (row) => (
        <Badge variant={row.minervini_pass ? 'success' : 'danger'}>
          {row.minervini_pass ? 'PASS' : 'FAIL'}
        </Badge>
      ),
    },
  ];
}

type SortDir = 'asc' | 'desc';

interface SortState {
  key: string;
  dir: SortDir;
}

function sortWatchlist(
  list: WatchlistStock[],
  sortState: SortState | null,
): WatchlistStock[] {
  if (!sortState) return list;

  const sorted = [...list];
  const { key, dir } = sortState;

  sorted.sort((a, b) => {
    let aVal: string | number | null;
    let bVal: string | number | null;

    switch (key) {
      case 'ticker':
        aVal = a.ticker;
        bVal = b.ticker;
        break;
      case 'latest_price':
        aVal = a.latest_price;
        bVal = b.latest_price;
        break;
      case 'quarterly_eps_growth':
        aVal = a.quarterly_eps_growth;
        bVal = b.quarterly_eps_growth;
        break;
      case 'annual_eps_cagr':
        aVal = a.annual_eps_cagr;
        bVal = b.annual_eps_cagr;
        break;
      case 'rs_rating':
        aVal = a.rs_rating;
        bVal = b.rs_rating;
        break;
      case 'custom_composite_score':
        aVal = a.custom_composite_score;
        bVal = b.custom_composite_score;
        break;
      case 'n_value':
        aVal = a.n_value;
        bVal = b.n_value;
        break;
      case 'avg_volume_50d':
        aVal = a.avg_volume_50d;
        bVal = b.avg_volume_50d;
        break;
      default:
        return 0;
    }

    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;

    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return dir === 'asc'
        ? aVal.localeCompare(bVal)
        : bVal.localeCompare(aVal);
    }

    const numA = aVal as number;
    const numB = bVal as number;
    return dir === 'asc' ? numA - numB : numB - numA;
  });

  return sorted;
}

export function WatchlistPage() {
  const { data, isLoading, error } = useWatchlist();
  const [sortState, setSortState] = useState<SortState | null>(null);
  const watchlistTickers = useMemo(() => (data?.watchlist ?? []).map((s) => s.ticker), [data]);
  const { data: realtimeData } = useRealtimePrices(watchlistTickers);

  const handleSort = useCallback((key: string) => {
    setSortState((prev) => {
      if (prev?.key === key) {
        return { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' };
      }
      return { key, dir: 'desc' };
    });
  }, []);

  const watchlist = data?.watchlist ?? [];

  const sortedData = useMemo(
    () => sortWatchlist(watchlist, sortState),
    [watchlist, sortState],
  );

  const minerviniCount = useMemo(
    () => watchlist.filter((s) => s.minervini_pass).length,
    [watchlist],
  );

  const avgRs = useMemo(() => {
    const valid = watchlist.filter((s) => s.rs_rating != null);
    if (valid.length === 0) return '—';
    const sum = valid.reduce((acc, s) => acc + (s.rs_rating ?? 0), 0);
    return (sum / valid.length).toFixed(0);
  }, [watchlist]);

  const avgScore = useMemo(() => {
    const valid = watchlist.filter((s) => s.custom_composite_score != null);
    if (valid.length === 0) return '—';
    const sum = valid.reduce((acc, s) => acc + (s.custom_composite_score ?? 0), 0);
    return (sum / valid.length).toFixed(1);
  }, [watchlist]);

  const columns = useMemo(() => getColumns(realtimeData), [realtimeData]);

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">관심종목 데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="관심종목" subtitle="CANSLIM 스크리닝 결과" />

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="총 종목" value={watchlist.length} />
        <StatCard label="미너비니 통과" value={minerviniCount} />
        <StatCard label="평균 RS" value={avgRs} />
        <StatCard label="평균 점수" value={avgScore} />
      </div>

      {/* Watchlist Table */}
      <div className="bg-panel rounded-xl border border-slate-700/50 overflow-hidden">
        <DataTable<WatchlistStock>
          columns={columns}
          data={sortedData}
          onSort={handleSort}
          sortKey={sortState?.key}
          sortDir={sortState?.dir}
          rowKey={(row) => row.ticker}
          emptyMessage="관심종목이 없습니다"
        />
      </div>
    </div>
  );
}
