import { useState, useEffect } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { PnlText } from '@/components/ui/PnlText';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { useDiary } from '@/hooks/useDiary';
import { useMarket } from '@/hooks/useMarket';
import { currencySymbol } from '@/lib/format';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { DiaryEntry, JournalContext } from '@/types/api';

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

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const date = `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`;
  const time = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  return `${date} ${time}`;
}

function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'filled':
      return 'success';
    case 'cancelled':
    case 'rejected':
      return 'danger';
    default:
      return 'default';
  }
}

function formatContextValue(key: string, value: unknown, market: string): string {
  if (typeof value === 'boolean') return value ? '✓' : '✗';
  if (typeof value === 'number') {
    if (key === 'position_size_pct' || key === 'loss_pct' || key === 'pnl_pct') {
      return `${value.toFixed(2)}%`;
    }
    if (key === 'account_equity') {
      return `${currencySymbol(market)}${value.toLocaleString()}`;
    }
    if (
      key === 'breakout_level' ||
      key === 'stop_price' ||
      key === 'risk_per_share' ||
      key === 'new_stop' ||
      key === 'prev_stop' ||
      key === 'trigger_price' ||
      key === 'avg_entry_price' ||
      key === 'exit_level'
    ) {
      return `${currencySymbol(market)}${value.toFixed(2)}`;
    }
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(2);
  }
  return String(value);
}

function ContextGrid({ context, market }: { context: JournalContext; market: string }) {
  const entries = Object.entries(context).filter(
    ([key, value]) => key !== 'raw' && value != null && key in CONTEXT_LABELS,
  );

  if (entries.length === 0) return null;

  return (
    <div className="border-t border-slate-700/30 pt-3 mt-2">
      <h4 className="text-xs font-medium text-slate-500 uppercase mb-2">매매 컨텍스트</h4>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <p className="text-xs text-slate-500">{CONTEXT_LABELS[key]}</p>
            <p className={`text-sm ${key === 'error' ? 'text-loss' : 'text-slate-300'}`}>
              {formatContextValue(key, value, market)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function DiaryCard({ entry, market }: { entry: DiaryEntry; market: string }) {
  return (
    <div className="bg-panel rounded-xl p-4 border border-slate-700/50 mb-3">
      {/* Header */}
      <div className="flex justify-between items-center mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold text-slate-100">
            {entry.ticker}
            {entry.name && (
              <span className="ml-1.5 text-sm font-normal text-slate-400">{entry.name}</span>
            )}
          </span>
          <Badge variant={entry.side.toLowerCase() === 'buy' ? 'buy' : 'sell'}>
            {entry.side}
          </Badge>
          <span className="text-sm text-slate-400">{entry.order_type}</span>
        </div>
        <span className="text-sm text-slate-400">{formatDateTime(entry.created_at)}</span>
      </div>

      {/* Info row */}
      <div className="flex flex-wrap gap-6 text-sm mb-3">
        <span className="text-slate-300">
          주문: {entry.requested_shares}주 × {currencySymbol(market)}{entry.requested_price.toFixed(2)}
        </span>
        <span className="text-slate-300">
          체결: {entry.filled_shares}주 × {entry.filled_price != null ? `${currencySymbol(market)}${entry.filled_price.toFixed(2)}` : '—'}
        </span>
        <span className="text-slate-300 inline-flex items-center gap-1">
          상태: <Badge variant={statusVariant(entry.status)}>{entry.status}</Badge>
        </span>
      </div>

      {/* Position info */}
      {entry.position_system && (
        <div className="flex flex-wrap gap-6 text-sm text-slate-400 mb-3">
          <span className="inline-flex items-center gap-1">
            시스템:{' '}
            <Badge variant={entry.position_system.toLowerCase() === 's1' ? 's1' : 's2'}>
              {entry.position_system}
            </Badge>
          </span>
          {entry.position_avg_entry != null && (
            <span>평균단가: {currencySymbol(market)}{entry.position_avg_entry.toFixed(2)}</span>
          )}
          {entry.position_pnl != null && (
            <span className="inline-flex items-center gap-1">
              손익: <PnlText value={entry.position_pnl} prefix={currencySymbol(market)} />
            </span>
          )}
          {entry.close_reason && <span>청산사유: {entry.close_reason}</span>}
        </div>
      )}

      {/* Context */}
      {entry.context && <ContextGrid context={entry.context} market={market} />}
    </div>
  );
}

export function DiaryPage() {
  const { market } = useMarket();
  const [ticker, setTicker] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useDiary(ticker, PAGE_SIZE, offset, market);

  useEffect(() => {
    setOffset(0);
  }, [ticker]);

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

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;
  const tickers = data?.available_tickers ?? [];
  const endIndex = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-6">
      <PageHeader title="종목일기" subtitle="종목별 매매 기록 상세" />

      {/* Controls */}
      <div className="flex gap-4 mb-6">
        <select
          value={ticker ?? ''}
          onChange={(e) => setTicker(e.target.value || undefined)}
          className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200"
        >
          <option value="">전체 종목</option>
          {tickers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Diary Cards */}
      {entries.length === 0 ? (
        <EmptyState message="매매 기록이 없습니다" />
      ) : (
        <>
          {entries.map((entry) => (
            <DiaryCard key={entry.order_id} entry={entry} market={market} />
          ))}

          {/* Pagination */}
          <div className="flex justify-between items-center mt-4">
            <span className="text-sm text-slate-400">
              총 {total}건 중 {offset + 1}~{endIndex}건
            </span>
            <div className="flex gap-2">
              <button
                disabled={offset === 0}
                onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                이전
              </button>
              <button
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
                className="px-3 py-1.5 text-sm rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                다음
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
