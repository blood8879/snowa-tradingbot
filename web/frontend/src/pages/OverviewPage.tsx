import { useMemo, useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatCard } from '@/components/ui/StatCard';
import { DataTable } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useStatus } from '@/hooks/useStatus';
import { useTrades } from '@/hooks/useTrades';
import { useMarket } from '@/hooks/useMarket';
import { useMarketControl } from '@/hooks/useMarketControl';
import { useAccountReset } from '@/hooks/useAccountReset';
import { formatPrice, currencySymbol } from '@/lib/format';
import type { Column } from '@/components/ui/DataTable';
import type { BadgeVariant } from '@/components/ui/Badge';
import type { Trade, AccountResetResponse } from '@/types/api';

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function mapTradeStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'filled':
      return 'success';
    case 'pending':
    case 'submitted':
      return 'default';
    case 'cancelled':
    case 'rejected':
      return 'danger';
    default:
      return 'default';
  }
}

function getTradeColumns(market: string): Column<Trade>[] {
  return [
    {
      key: 'time',
      header: '시간',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatTime(row.created_at)}</span>
      ),
    },
    {
      key: 'ticker',
      header: '종목',
      render: (row) => <span className="font-medium text-slate-100">{row.ticker}</span>,
    },
    {
      key: 'side',
      header: '매매',
      render: (row) => (
        <Badge variant={row.side.toLowerCase() === 'buy' ? 'buy' : 'sell'}>
          {row.side}
        </Badge>
      ),
    },
    {
      key: 'shares',
      header: '수량',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{row.requested_shares.toLocaleString()}</span>
      ),
    },
    {
      key: 'price',
      header: '가격',
      render: (row) => (
        <span className="text-slate-300 tabular-nums">{formatPrice(row.requested_price, market)}</span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (row) => (
        <Badge variant={mapTradeStatusVariant(row.status)}>{row.status}</Badge>
      ),
    },
  ];
}

const MARKET_FLAGS: Record<string, string> = {
  US: '\u{1F1FA}\u{1F1F8}',
  KR: '\u{1F1F0}\u{1F1F7}',
};

export function OverviewPage() {
  const { market } = useMarket();
  const { data: status, isLoading: statusLoading, error: statusError } = useStatus(market);
  const { data: trades, isLoading: tradesLoading, error: tradesError } = useTrades(5, 0, market);
  const { markets, toggleMarket } = useMarketControl();
  const { resetAccount, isResetting, error: resetError } = useAccountReset();
  const [showResetModal, setShowResetModal] = useState(false);
  const [showRegimeHelp, setShowRegimeHelp] = useState(false);
  const [resetResult, setResetResult] = useState<AccountResetResponse | null>(null);

  const handleToggle = (marketId: string, currentEnabled: boolean) => {
    const action = currentEnabled ? '종료' : '시작';
    const name = markets.find((m) => m.market_id === marketId)?.display_name ?? marketId;
    if (!window.confirm(`${name} 자동매매를 ${action}하시겠습니까?`)) return;
    toggleMarket(marketId, !currentEnabled);
  };

  const handleReset = async () => {
    const result = await resetAccount();
    if (result) {
      setResetResult(result);
    }
    setShowResetModal(false);
  };

  const tradeColumns = useMemo(() => getTradeColumns(market), [market]);

  const chartData = useMemo(() => {
    if (!status) return [];
    return [
      { label: '현재', equity: status.account_equity },
    ];
  }, [status]);

  if (statusLoading || tradesLoading) {
    return <LoadingSpinner />;
  }

  if (statusError || tradesError) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-loss text-sm">데이터를 불러오는 중 오류가 발생했습니다.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PageHeader title="대시보드" subtitle="SNOWA 트레이딩 봇 실시간 현황" />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowRegimeHelp(true)}
            className="px-3 py-2 text-sm font-medium text-blue-400 bg-blue-500/10 border border-blue-500/30 rounded-lg hover:bg-blue-500/20 hover:text-blue-300 transition-colors"
            title="시장 레짐 판단 기준"
          >
            <svg className="w-4 h-4 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
            </svg>
            시장 레짐
          </button>
          <button
            type="button"
            onClick={() => setShowResetModal(true)}
            disabled={isResetting}
            className="px-4 py-2 text-sm font-medium text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg hover:bg-red-500/20 hover:text-red-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isResetting ? '초기화 중...' : '계좌 초기화'}
          </button>
        </div>
      </div>

      {/* Market Regime Help Modal */}
      {showRegimeHelp && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowRegimeHelp(false)}>
          <div className="bg-slate-800 border border-slate-600 rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-slate-100">시장 추세 판단 기준 (3단계 레짐)</h3>
              <button onClick={() => setShowRegimeHelp(false)} className="text-slate-400 hover:text-slate-200">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-5 text-sm text-slate-300">
              {/* Signal 1 */}
              <div>
                <h4 className="text-base font-semibold text-slate-100 mb-2">1. 벤치마크 200일 이동평균 (SMA)</h4>
                <p className="mb-2">가장 기본적인 시장 추세 필터입니다.</p>
                <ul className="list-disc list-inside space-y-1 text-slate-400">
                  <li><span className="text-slate-200">US</span>: SPY 종가 &gt; SPY 200일 SMA</li>
                  <li><span className="text-slate-200">KR</span>: KODEX200(069500) 종가 &gt; 200일 SMA</li>
                  <li>200 SMA 아래이면 <span className="text-yellow-400 font-semibold">YELLOW</span> (유닛 50% 축소, 단독으로 RED 아님)</li>
                </ul>
              </div>

              {/* Signal 2 */}
              <div>
                <h4 className="text-base font-semibold text-slate-100 mb-2">2. 시장 브레드스 (Market Breadth)</h4>
                <p className="mb-2">전체 유니버스 중 종가가 자체 200일 SMA 위에 있는 종목 비율입니다.</p>
                <div className="bg-slate-700/50 rounded-lg p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full bg-green-500" />
                    <span><span className="text-green-400 font-semibold">&gt; 55%</span> — 건강한 시장, 대다수 종목이 상승 추세</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full bg-yellow-500" />
                    <span><span className="text-yellow-400 font-semibold">35~55%</span> — 시장 약화, 좁은 랠리 가능성 (narrow rally)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full bg-red-500" />
                    <span><span className="text-red-400 font-semibold">&lt; 35%</span> — 시장 전반적 하락, 대부분 종목이 하락 추세</span>
                  </div>
                </div>
                <p className="mt-2 text-slate-500 text-xs">US: ~6,800개 종목 / KR: ~3,600개 종목 기준으로 계산</p>
              </div>

              {/* Signal 3 */}
              <div>
                <h4 className="text-base font-semibold text-slate-100 mb-2">3. 125일 변화율 (ROC, Rate of Change)</h4>
                <p className="mb-2">벤치마크의 약 6개월간 모멘텀을 측정합니다.</p>
                <div className="bg-slate-700/50 rounded-lg p-3 space-y-1">
                  <p className="text-slate-200 font-mono text-xs mb-2">ROC = (오늘 종가 / 125거래일 전 종가) - 1</p>
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full bg-green-500" />
                    <span><span className="text-green-400 font-semibold">ROC &gt; -5%</span> — 모멘텀 양호</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-full bg-red-500" />
                    <span><span className="text-red-400 font-semibold">ROC &lt; -5%</span> — 6개월 전보다 5% 이상 하락, 추세 이탈 초기 신호</span>
                  </div>
                </div>
                <p className="mt-2 text-slate-500 text-xs">200 SMA 이탈보다 2~4주 빠르게 하락 추세를 포착합니다.</p>
              </div>

              {/* Combined */}
              <div>
                <h4 className="text-base font-semibold text-slate-100 mb-3">종합 레짐 판단</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-slate-600">
                        <th className="text-left py-2 px-2 text-slate-400">SMA 통과</th>
                        <th className="text-left py-2 px-2 text-slate-400">브레드스</th>
                        <th className="text-left py-2 px-2 text-slate-400">ROC</th>
                        <th className="text-left py-2 px-2 text-slate-400">레짐</th>
                        <th className="text-left py-2 px-2 text-slate-400">행동</th>
                      </tr>
                    </thead>
                    <tbody className="text-slate-300">
                      <tr className="border-b border-slate-700/50">
                        <td className="py-1.5 px-2">O</td>
                        <td className="py-1.5 px-2">&gt;55%</td>
                        <td className="py-1.5 px-2">&gt;-5%</td>
                        <td className="py-1.5 px-2"><span className="text-green-400 font-bold">GREEN</span></td>
                        <td className="py-1.5 px-2">풀 진입 (100% 유닛)</td>
                      </tr>
                      <tr className="border-b border-slate-700/50">
                        <td className="py-1.5 px-2">O</td>
                        <td className="py-1.5 px-2">&gt;55%</td>
                        <td className="py-1.5 px-2">&lt;-5%</td>
                        <td className="py-1.5 px-2"><span className="text-yellow-400 font-bold">YELLOW</span></td>
                        <td className="py-1.5 px-2">진입 허용, 유닛 50%</td>
                      </tr>
                      <tr className="border-b border-slate-700/50">
                        <td className="py-1.5 px-2">O</td>
                        <td className="py-1.5 px-2">&lt;55%</td>
                        <td className="py-1.5 px-2">&gt;-5%</td>
                        <td className="py-1.5 px-2"><span className="text-yellow-400 font-bold">YELLOW</span></td>
                        <td className="py-1.5 px-2">진입 허용, 유닛 50%</td>
                      </tr>
                      <tr className="border-b border-slate-700/50">
                        <td className="py-1.5 px-2">X</td>
                        <td className="py-1.5 px-2">-</td>
                        <td className="py-1.5 px-2">-</td>
                        <td className="py-1.5 px-2"><span className="text-yellow-400 font-bold">YELLOW</span></td>
                        <td className="py-1.5 px-2">진입 허용, 유닛 50%</td>
                      </tr>
                      <tr>
                        <td className="py-1.5 px-2">O/X</td>
                        <td className="py-1.5 px-2">&lt;35%</td>
                        <td className="py-1.5 px-2">&lt;-5%</td>
                        <td className="py-1.5 px-2"><span className="text-red-400 font-bold">RED</span></td>
                        <td className="py-1.5 px-2">신규 진입 차단</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Note */}
              <div className="bg-slate-700/30 rounded-lg p-3 text-xs text-slate-400">
                <p className="font-semibold text-slate-300 mb-1">참고</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li>기존 보유 포지션은 레짐과 무관하게 Turtle 손절/Donchian 청산 규칙으로 관리</li>
                  <li>YELLOW에서는 신규 진입은 허용하되, 포지션 크기를 50%로 축소</li>
                  <li>레짐은 장전(pre-market)에 1회 계산되어 장중 유지됨</li>
                  <li>스크리닝 탈락 종목은 레짐과 무관하게 피라미딩(추가 매수) 차단</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Reset Confirmation Modal */}
      {showResetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-800 border border-slate-600 rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center">
                <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5Z" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-slate-100">계좌 데이터 초기화</h3>
            </div>

            <div className="space-y-3 mb-6">
              <p className="text-sm text-slate-300">
                현재 모드: <span className="font-semibold text-amber-400">{status?.mode?.toUpperCase() ?? 'PAPER'}</span>
              </p>
              <div className="bg-slate-900/50 rounded-lg p-3 text-sm text-slate-400 space-y-1">
                <p className="text-slate-300 font-medium mb-2">다음 데이터가 초기화됩니다:</p>
                <p>- 열린 포지션 전체 종료 (ACCOUNT_RESET)</p>
                <p>- 미체결 주문 전체 취소</p>
                <p>- 봇 런타임 상태 초기화</p>
                <p>- 브로커에서 최신 계좌 잔고 다시 조회</p>
              </div>
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 text-sm text-blue-300">
                스크리닝 데이터(watchlist, 가격, 펀더멘털)와 이전 거래 기록은 보존됩니다.
              </div>
              {status?.mode === 'live' && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-300 font-medium">
                  실전 투자 모드입니다. 실제 브로커 계좌의 보유 종목에는 영향이 없지만, DB 기록이 초기화됩니다.
                </div>
              )}
            </div>

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setShowResetModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-300 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors"
              >
                취소
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={isResetting}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-500 transition-colors disabled:opacity-50"
              >
                {isResetting ? '처리 중...' : '초기화 실행'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reset Result Banner */}
      {resetResult && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center justify-between">
          <div className="text-sm text-green-300">
            <span className="font-medium">초기화 완료</span>
            {' '} &mdash; 포지션 {resetResult.closed_positions}개 종료, 주문 {resetResult.cancelled_orders}개 취소
            {resetResult.account_equity != null && (
              <span className="ml-2 text-slate-400">
                (계좌 잔고: {resetResult.currency === 'KRW' ? '\u20A9' : '$'}
                {resetResult.account_equity.toLocaleString(undefined, { maximumFractionDigits: 2 })})
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setResetResult(null)}
            className="text-slate-500 hover:text-slate-300 text-lg leading-none"
          >
            &times;
          </button>
        </div>
      )}

      {/* Reset Error Banner */}
      {resetError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-sm text-red-300">
          초기화 실패: {resetError}
        </div>
      )}

      {/* Market Toggle Cards */}
      {markets.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-400 mb-3">자동매매 설정</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {markets.map((m) => (
              <div
                key={m.market_id}
                className="bg-panel rounded-xl p-4 border border-slate-700/50 flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{MARKET_FLAGS[m.market_id] ?? ''}</span>
                  <div>
                    <span className="text-sm font-medium text-slate-100">{m.display_name}</span>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {m.currency} · {m.exchanges.join(', ')}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleToggle(m.market_id, m.enabled)}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
                    m.enabled ? 'bg-green-500' : 'bg-slate-600'
                  }`}
                  role="switch"
                  aria-checked={m.enabled}
                  aria-label={`${m.display_name} 자동매매 ${m.enabled ? '켜짐' : '꺼짐'}`}
                >
                  <span
                    className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out ${
                      m.enabled ? 'translate-x-5' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="계좌 자산"
          value={status ? `${currencySymbol(market)}${status.account_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
          delta={
            status
              ? `현금 ${currencySymbol(market)}${status.cash_balance.toLocaleString(undefined, { maximumFractionDigits: 0 })} / 주식 ${currencySymbol(market)}${status.positions_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              : undefined
          }
          deltaType="neutral"
        />
        <StatCard
          label="포지션"
          value={status ? `${status.positions}개` : '—'}
        />
        <StatCard
          label="유닛"
          value={status ? `${status.units}개` : '—'}
        />
        <StatCard
          label="시장 레짐"
          value={status?.regime ?? status?.market_filter ?? '—'}
          delta={
            status?.benchmark?.close && status?.benchmark?.sma200
              ? <>
                  <span className={status.benchmark.close > status.benchmark.sma200 ? 'text-green-400' : 'text-yellow-400'}>
                    {status.benchmark.name} {currencySymbol(market)}{status.benchmark.close.toLocaleString(undefined, { maximumFractionDigits: 0 })} / SMA200 {currencySymbol(market)}{status.benchmark.sma200.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                  {status?.breadth_pct != null && <>
                    <span className="text-slate-500"> | </span>
                    <span className={status.breadth_pct >= 0.55 ? 'text-green-400' : status.breadth_pct >= 0.35 ? 'text-yellow-400' : 'text-red-400'}>
                      브레드스 {(status.breadth_pct * 100).toFixed(1)}%
                    </span>
                  </>}
                  {status?.roc != null && <>
                    <span className="text-slate-500"> | </span>
                    <span className={status.roc >= -0.05 ? 'text-green-400' : 'text-red-400'}>
                      ROC {(status.roc * 100).toFixed(1)}%
                    </span>
                  </>}
                </>
              : status?.market_filter_pass ? '통과' : '미통과'
          }
          deltaType="neutral"
        />
        <StatCard
          label="모드"
          value={status?.mode?.toUpperCase() ?? '—'}
        />
      </div>

      {/* Equity Curve */}
      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">자산 곡선</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="label"
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
              />
              <YAxis
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
                tickFormatter={(v: number) => `${currencySymbol(market)}${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  color: '#f1f5f9',
                }}
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="url(#equityGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Trades */}
      <div className="bg-panel rounded-xl p-4 border border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-400 mb-4">최근 거래</h3>
        <DataTable<Trade>
          columns={tradeColumns}
          data={trades?.trades ?? []}
          rowKey={(row) => row.id}
          emptyMessage="최근 거래가 없습니다"
        />
      </div>
    </div>
  );
}
