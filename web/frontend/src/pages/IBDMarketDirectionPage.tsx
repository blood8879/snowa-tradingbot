import { PageHeader } from '../components/ui/PageHeader';
import { useMarket } from '../hooks/useMarket';
import { useIBDStatus, useIBDDistributionDays } from '../hooks/useIBDMarketDirection';

const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  CONFIRMED_UPTREND: { bg: 'bg-green-500/20', text: 'text-green-400', label: '확인된 상승추세' },
  UPTREND_UNDER_PRESSURE: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: '상승추세 압박' },
  RALLY_ATTEMPT: { bg: 'bg-orange-500/20', text: 'text-orange-400', label: '반등 시도' },
  MARKET_IN_CORRECTION: { bg: 'bg-red-500/20', text: 'text-red-400', label: '조정장' },
};

const DAY_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  DISTRIBUTION: { label: '분배일', color: 'text-red-400' },
  STALLING: { label: '스톨링', color: 'text-yellow-400' },
  FOLLOW_THROUGH: { label: 'FTD', color: 'text-green-400' },
};

export function IBDMarketDirectionPage() {
  const { market } = useMarket();
  const { data: status, isLoading: statusLoading } = useIBDStatus(market);
  const { data: distDays, isLoading: distLoading } = useIBDDistributionDays(market, true);
  const currencyPrefix = market === 'KR' ? '₩' : '$';

  if (statusLoading || distLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  const overall = status?.overall_status ?? 'MARKET_IN_CORRECTION';
  const overallStyle = STATUS_COLORS[overall] ?? STATUS_COLORS.MARKET_IN_CORRECTION;
  const indexes = status?.indexes ?? [];
  const days = distDays?.distribution_days ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="IBD 시장 방향" subtitle="분배일 기반 시장 추세 판단 (로깅 전용)" />

      {/* No data yet */}
      {indexes.length === 0 && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">아직 데이터가 없습니다. 장 마감 후 첫 데이터가 기록됩니다.</p>
        </div>
      )}

      {/* Overall Status */}
      {indexes.length > 0 && (
        <>
          <div className={`${overallStyle.bg} border border-slate-700 rounded-xl p-6`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-slate-400 uppercase tracking-wider mb-1">종합 시장 방향</p>
                <p className={`text-2xl font-bold ${overallStyle.text}`}>{overallStyle.label}</p>
                <p className="text-xs text-slate-500 mt-1">{indexes[0]?.date}</p>
              </div>
              <div className={`text-5xl font-black ${overallStyle.text} opacity-30`}>
                {overall === 'CONFIRMED_UPTREND' ? '▲' : overall === 'MARKET_IN_CORRECTION' ? '▼' : '◆'}
              </div>
            </div>
          </div>

          {/* Per-Index Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {indexes.map((idx) => {
              const style = STATUS_COLORS[idx.status] ?? STATUS_COLORS.MARKET_IN_CORRECTION;
              return (
                <div key={idx.index_ticker} className="bg-slate-800/50 border border-slate-700 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-lg font-semibold text-slate-100">{idx.display_name ?? idx.index_ticker}</h3>
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${style.bg} ${style.text}`}>
                      {style.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-slate-500">분배일 수</p>
                      <p className={`font-semibold ${idx.distribution_count >= 5 ? 'text-red-400' : idx.distribution_count >= 3 ? 'text-yellow-400' : 'text-slate-200'}`}>
                        {idx.distribution_count}일
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-500">랠리 일수</p>
                      <p className="font-semibold text-slate-200">{idx.rally_day_count > 0 ? `Day ${idx.rally_day_count}` : '—'}</p>
                    </div>
                    <div>
                      <p className="text-slate-500">FTD 확인일</p>
                      <p className="font-semibold text-slate-200">{idx.ftd_date ?? '—'}</p>
                    </div>
                    <div>
                      <p className="text-slate-500">FTD 저가</p>
                      <p className="font-semibold text-slate-200">{idx.ftd_low ? `${currencyPrefix}${idx.ftd_low.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '—'}</p>
                    </div>
                  </div>
                  {idx.notes && (
                    <p className="mt-3 text-xs text-slate-500 border-t border-slate-700 pt-2">{idx.notes}</p>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Active Distribution Days Table */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-700">
          <h3 className="text-sm font-medium text-slate-300">활성 분배일 / 스톨링일</h3>
        </div>
        {days.length === 0 ? (
          <p className="p-5 text-sm text-slate-500">활성 분배일이 없습니다.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs uppercase border-b border-slate-700">
                  <th className="text-left px-4 py-2">날짜</th>
                  <th className="text-left px-4 py-2">지수</th>
                  <th className="text-left px-4 py-2">유형</th>
                  <th className="text-right px-4 py-2">종가</th>
                  <th className="text-right px-4 py-2">변화율</th>
                  <th className="text-right px-4 py-2">거래량</th>
                </tr>
              </thead>
              <tbody>
                {days.map((day, i) => {
                  const dtype = DAY_TYPE_LABELS[day.day_type] ?? { label: day.day_type, color: 'text-slate-300' };
                  return (
                    <tr key={`${day.date}-${day.index_ticker}-${i}`} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                      <td className="px-4 py-2 text-slate-300">{day.date}</td>
                      <td className="px-4 py-2 text-slate-300">{day.display_name ?? day.index_ticker}</td>
                      <td className={`px-4 py-2 font-medium ${dtype.color}`}>{dtype.label}</td>
                      <td className="px-4 py-2 text-right text-slate-300">{currencyPrefix}{day.close_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                      <td className={`px-4 py-2 text-right ${day.price_change_pct < 0 ? 'text-red-400' : 'text-green-400'}`}>
                        {(day.price_change_pct * 100).toFixed(2)}%
                      </td>
                      <td className="px-4 py-2 text-right text-slate-400">
                        {day.volume.toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
