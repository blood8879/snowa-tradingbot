import { useState } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useBotHealth } from '@/hooks/useBotHealth';
import { useLogs } from '@/hooks/useLogs';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { BotHealthResponse, LogEntry } from '@/types/api';

type LogLevel = 'ALL' | 'ERROR' | 'WARNING' | 'INFO';

const LOG_LEVELS: LogLevel[] = ['ALL', 'ERROR', 'WARNING', 'INFO'];

function getHealthLabel(status: BotHealthResponse['health_status']): string {
  switch (status) {
    case 'running':
      return 'Running';
    case 'stopped':
      return 'Stopped';
    case 'degraded':
      return 'Degraded';
  }
}

function getLogBadgeVariant(level: string | undefined): BadgeVariant {
  switch ((level ?? '').toLowerCase()) {
    case 'error':
      return 'danger';
    case 'warning':
      return 'sell';
    default:
      return 'default';
  }
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
}

function formatDetailValue(value: string | null): string {
  if (value == null) return '-';
  return value;
}

export function LogsPage() {
  const [selectedLevel, setSelectedLevel] = useState<LogLevel>('ALL');
  const { data: health, isLoading: healthLoading, error: healthError } = useBotHealth();
  const { data: logsData, isLoading: logsLoading, error: logsError } = useLogs(100, selectedLevel);

  if (healthLoading || logsLoading) {
    return <LoadingSpinner />;
  }

  if (healthError || logsError) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="로그" subtitle="봇 상태 및 실시간 로그 뷰어" />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="봇 상태"
          value={health ? getHealthLabel(health.health_status) : '-'}
          delta={health ? health.health_status : undefined}
          deltaType={
            health?.health_status === 'running'
              ? 'positive'
              : health?.health_status === 'stopped'
                ? 'negative'
                : 'neutral'
          }
        />
        <StatCard
          label="계좌 자산"
          value={health?.live_equity != null ? `$${health.live_equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '-'}
          delta={health?.live_cash != null ? `현금 $${health.live_cash.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : undefined}
          deltaType="neutral"
        />
        <StatCard
          label="WS 연결"
          value={health?.ws_status ?? '-'}
        />
        <StatCard
          label="관심종목"
          value={health ? `${health.active_watchlist}개` : '-'}
        />
        <StatCard
          label="미체결 주문"
          value={health ? `${health.pending_orders}개` : '-'}
        />
      </div>

      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">데이터 최신성</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-8 gap-y-3">
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">가격 데이터</span>
            <span className="text-sm text-slate-100">
              {health?.latest_price_date ?? '-'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">재무 데이터</span>
            <span className="text-sm text-slate-100">
              {health?.latest_fundamental_date ? formatTimestamp(health.latest_fundamental_date) : '-'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">스크리닝</span>
            <span className="text-sm text-slate-100">
              {health?.latest_screening_date ? formatTimestamp(health.latest_screening_date) : '-'}
            </span>
          </div>
        </div>
      </div>

      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">봇 상세 정보</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-3">
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">모드</span>
            <span className="text-sm text-slate-100">{health?.mode ?? '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">시장 필터</span>
            <span className="text-sm text-slate-100">{health?.market_filter ?? '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">마지막 하트비트</span>
            <span className="text-sm text-slate-100">
              {formatDetailValue(health?.last_heartbeat ?? null)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">마지막 스크리닝</span>
            <span className="text-sm text-slate-100">
              {formatDetailValue(health?.last_screening ?? null)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">마지막 오류</span>
            <span className="text-sm text-slate-100">
              {formatDetailValue(health?.last_error ?? null)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-slate-400">최근 오류 수</span>
            <span className="text-sm text-slate-100">
              {health?.recent_error_count ?? '-'}
            </span>
          </div>
        </div>
      </div>

      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-slate-400">로그 뷰어</h3>
          <div className="flex gap-1">
            {LOG_LEVELS.map((level) => (
              <button
                key={level}
                onClick={() => setSelectedLevel(level)}
                className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                  selectedLevel === level
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700/50 text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>

        {logsData && !logsData.log_file_exists ? (
          <div className="flex items-center justify-center h-40">
            <p className="text-slate-400 text-sm">로그 파일이 아직 생성되지 않았습니다</p>
          </div>
        ) : (
          <div className="max-h-[600px] overflow-y-auto space-y-1">
            {(logsData?.logs ?? []).map((entry: LogEntry, idx: number) => (
              <div
                key={`${entry.timestamp ?? ''}-${idx}`}
                className="flex items-start gap-3 px-3 py-2 rounded-md hover:bg-slate-800/30 transition-colors"
              >
                <span className="text-slate-500 text-xs tabular-nums whitespace-nowrap pt-0.5">
                  {entry.timestamp ? formatTimestamp(entry.timestamp) : '--/-- --:--:--'}
                </span>
                <Badge variant={getLogBadgeVariant(entry.level)}>
                  {(entry.level ?? 'log').toUpperCase()}
                </Badge>
                <span className="text-sm text-slate-300 break-all">{entry.event}</span>
              </div>
            ))}
            {(logsData?.logs ?? []).length === 0 && (
              <div className="flex items-center justify-center h-40">
                <p className="text-slate-400 text-sm">표시할 로그가 없습니다</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
