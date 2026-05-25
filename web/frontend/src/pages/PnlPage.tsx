import { useState, useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { usePnl } from '@/hooks/usePnl';
import { usePositions } from '@/hooks/usePositions';
import { useMarket } from '@/hooks/useMarket';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import type { PnlDataPoint } from '@/types/api';


type ViewMode = 'calendar' | 'chart';
type PeriodMode = 'daily' | 'monthly' | 'yearly';

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const MONTH_LABELS = [
  '1월', '2월', '3월', '4월', '5월', '6월',
  '7월', '8월', '9월', '10월', '11월', '12월',
];

const PERIOD_TABS: { key: PeriodMode; label: string }[] = [
  { key: 'daily', label: '일별' },
  { key: 'monthly', label: '월별' },
  { key: 'yearly', label: '연도별' },
];

// ── Icons ──────────────────────────────────────

function CalendarIcon({ active }: { active: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"
      className={active ? 'text-white' : 'text-slate-500'}>
      <rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 8h14" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 2v4M13 2v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ChartIcon({ active }: { active: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"
      className={active ? 'text-white' : 'text-slate-500'}>
      <path d="M3 17V7l4 4 4-6 6 4" stroke="currentColor" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Helpers ─────────────────────────────────────

function getCellBg(pnl: number | undefined): string {
  if (pnl === undefined) return '';
  if (pnl > 0) return 'bg-emerald-800/60';
  if (pnl < 0) return 'bg-red-900/60';
  return 'bg-slate-700/40';
}

function getCellTextColor(pnl: number | undefined): string {
  if (pnl === undefined) return 'text-slate-500';
  return 'text-slate-200';
}

function getPnlColor(pnl: number): string {
  return pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
}

function fmtPnl(value: number, market: string): string {
  const sign = value > 0 ? '+' : '';
  const abs = Math.abs(value);
  const isKR = market === 'KR';
  const formatted = isKR
    ? Math.round(abs).toLocaleString('en-US')
    : abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sym = isKR ? '₩' : '$';
  return `${sign}${value < 0 ? '-' : ''}${sym}${formatted}`;
}

function fmtPnlCompact(value: number, market: string): string {
  const abs = Math.abs(value);
  const isKR = market === 'KR';
  const sym = isKR ? '₩' : '$';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  let num: string;
  if (isKR) {
    num = Math.round(abs).toLocaleString('en-US');
  } else if (abs >= 1_000_000) {
    num = `${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  } else if (abs >= 1_000) {
    num = `${(abs / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`;
  } else {
    num = abs.toFixed(0);
  }
  return `${sign}${sym}${num}`;
}

// ── Aggregation helpers ────────────────────────

function buildDayPnlMap(points: PnlDataPoint[], year: number, month: number): Map<number, number> {
  const map = new Map<number, number>();
  for (const p of points) {
    const d = new Date(p.period);
    if (d.getFullYear() === year && d.getMonth() + 1 === month) {
      map.set(d.getDate(), p.pnl);
    }
  }
  return map;
}

function buildMonthPnlMap(points: PnlDataPoint[], year: number): Map<number, number> {
  const map = new Map<number, number>();
  for (const p of points) {
    const d = new Date(p.period);
    if (d.getFullYear() === year) {
      const m = d.getMonth() + 1;
      map.set(m, (map.get(m) ?? 0) + p.pnl);
    }
  }
  return map;
}

function buildYearPnlMap(points: PnlDataPoint[]): Map<number, number> {
  const map = new Map<number, number>();
  for (const p of points) {
    const y = new Date(p.period).getFullYear();
    map.set(y, (map.get(y) ?? 0) + p.pnl);
  }
  return map;
}

function getAvailableYears(points: PnlDataPoint[]): number[] {
  const years = new Set<number>();
  for (const p of points) {
    years.add(new Date(p.period).getFullYear());
  }
  return [...years].sort();
}

interface CumulativePoint {
  date: string;
  cumPnl: number;
}

function buildCumulativeData(points: PnlDataPoint[]): CumulativePoint[] {
  const sorted = [...points].sort(
    (a, b) => new Date(a.period).getTime() - new Date(b.period).getTime(),
  );
  let cum = 0;
  return sorted.map((p) => {
    cum += p.pnl;
    const parts = p.period.split('-');
    return {
      date: `${parts[1]}-${parts[2]}`,
      cumPnl: Math.round(cum * 100) / 100,
    };
  });
}

// ── Component ──────────────────────────────────

export function PnlPage() {
  const { market } = useMarket();
  const [viewMode, setViewMode] = useState<ViewMode>('calendar');
  const [periodMode, setPeriodMode] = useState<PeriodMode>('daily');

  const now = new Date();
  const [calYear, setCalYear] = useState(now.getFullYear());
  const [calMonth, setCalMonth] = useState(now.getMonth() + 1);

  const { data, error, isLoading } = usePnl('daily', market);
  const { data: positionsData } = usePositions(market);
  const points = data?.data ?? [];

  const holdingsPnl = useMemo(() => {
    if (!positionsData) return null;
    let pnlSum = 0;
    let costSum = 0;
    let evalSum = 0;
    let count = 0;
    for (const p of positionsData.positions) {
      if (p.unrealized_pnl !== null && p.unrealized_pnl !== undefined) {
        pnlSum += p.unrealized_pnl;
        evalSum += p.eval_amount ?? 0;
        costSum += p.total_cost ?? 0;
        count += 1;
      }
    }
    for (const bp of positionsData.broker_positions) {
      pnlSum += bp.pnl_amount;
      evalSum += bp.eval_amount;
      costSum += bp.avg_price * bp.quantity;
      count += 1;
    }
    if (count === 0) return null;
    const pct = costSum > 0 ? (pnlSum / costSum) * 100 : 0;
    return { pnl: pnlSum, pct, evalSum, costSum, count };
  }, [positionsData]);

  const dayMap = useMemo(() => buildDayPnlMap(points, calYear, calMonth), [points, calYear, calMonth]);
  const monthMap = useMemo(() => buildMonthPnlMap(points, calYear), [points, calYear]);
  const yearMap = useMemo(() => buildYearPnlMap(points), [points]);
  const availableYears = useMemo(() => getAvailableYears(points), [points]);
  const cumulativeData = useMemo(() => buildCumulativeData(points), [points]);
  const lastCum = cumulativeData.length > 0 ? cumulativeData[cumulativeData.length - 1] : null;

  const firstDow = new Date(calYear, calMonth - 1, 1).getDay();
  const daysInMonth = new Date(calYear, calMonth, 0).getDate();

  const prevMonth = () => {
    if (calMonth === 1) { setCalYear((y) => y - 1); setCalMonth(12); }
    else setCalMonth((m) => m - 1);
  };
  const nextMonth = () => {
    if (calMonth === 12) { setCalYear((y) => y + 1); setCalMonth(1); }
    else setCalMonth((m) => m + 1);
  };
  const prevYear = () => setCalYear((y) => y - 1);
  const nextYear = () => setCalYear((y) => y + 1);

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-loss">
        데이터를 불러오는 중 오류가 발생했습니다.
      </div>
    );
  }

  const periodTitle = periodMode === 'daily' ? '일별 손익' : periodMode === 'monthly' ? '월별 손익' : '연도별 손익';

  return (
    <div className="max-w-3xl mx-auto px-1 sm:px-0">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <h2 className="text-lg sm:text-xl font-bold text-slate-100 truncate">{periodTitle}</h2>
        <div className="flex bg-slate-800 rounded-lg overflow-hidden border border-slate-700/50 shrink-0">
          <button type="button" onClick={() => setViewMode('chart')}
            className={`p-2 transition-colors ${viewMode === 'chart' ? 'bg-slate-600' : 'hover:bg-slate-700'}`}>
            <ChartIcon active={viewMode === 'chart'} />
          </button>
          <button type="button" onClick={() => setViewMode('calendar')}
            className={`p-2 transition-colors ${viewMode === 'calendar' ? 'bg-slate-600' : 'hover:bg-slate-700'}`}>
            <CalendarIcon active={viewMode === 'calendar'} />
          </button>
        </div>
      </div>

      {/* Period Tabs */}
      <div className="flex gap-2 mb-5">
        {PERIOD_TABS.map((t) => (
          <button key={t.key} type="button" onClick={() => setPeriodMode(t.key)}
            className={
              periodMode === t.key
                ? 'px-4 py-1.5 text-sm rounded-lg bg-blue-600 text-white transition-colors'
                : 'px-4 py-1.5 text-sm rounded-lg bg-slate-700/50 text-slate-400 hover:text-slate-200 transition-colors'
            }>
            {t.label}
          </button>
        ))}
      </div>

      {/* ─── 현재 보유 평가손익 ─── */}
      {holdingsPnl && (
        <div className="mb-6 bg-panel rounded-xl p-4 border border-slate-700/50">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-semibold text-slate-300">현재 보유 평가손익</h3>
              <p className="text-[11px] text-slate-500 mt-0.5">
                보유 {holdingsPnl.count}종목 · 매입가 대비 미실현 손익
              </p>
            </div>
            <div className="text-right">
              <p className={`text-xl sm:text-2xl font-bold tabular-nums ${holdingsPnl.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {fmtPnl(holdingsPnl.pnl, market)}
              </p>
              <p className={`text-xs tabular-nums ${holdingsPnl.pnl >= 0 ? 'text-emerald-400/80' : 'text-red-400/80'}`}>
                {holdingsPnl.pnl >= 0 ? '+' : ''}{holdingsPnl.pct.toFixed(2)}%
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ─── Daily View ─── */}
      {periodMode === 'daily' && viewMode === 'calendar' && (
        <div className="mb-8">
          <div className="flex items-center justify-center gap-4 mb-4">
            <button type="button" onClick={prevMonth} className="text-slate-400 hover:text-white text-lg px-2">◀</button>
            <span className="text-slate-200 font-semibold text-lg">{calYear}-{String(calMonth).padStart(2, '0')}</span>
            <button type="button" onClick={nextMonth} className="text-slate-400 hover:text-white text-lg px-2">▶</button>
          </div>
          <div className="grid grid-cols-7 gap-1 mb-1">
            {WEEKDAYS.map((d, i) => (
              <div key={i} className="text-center text-xs text-slate-500 font-medium py-1">{d}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: firstDow }).map((_, i) => <div key={`e-${i}`} />)}
            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1;
              const pnl = dayMap.get(day);
              const hasPnl = pnl !== undefined;
              return (
                <div key={day} className={`rounded-md py-1.5 px-0.5 text-center min-h-[52px] sm:min-h-[56px] flex flex-col items-center justify-center overflow-hidden ${getCellBg(pnl)}`}>
                  <span className={`text-xs sm:text-sm font-semibold ${getCellTextColor(pnl)}`}>{day}</span>
                  {hasPnl && <span className={`text-[9px] sm:text-[10px] font-medium mt-0.5 tabular-nums leading-tight ${getPnlColor(pnl)}`}>{fmtPnlCompact(pnl, market)}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {periodMode === 'daily' && viewMode === 'chart' && (
        <div className="mb-8 bg-panel rounded-xl p-4 border border-slate-700/50">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={points
                .filter((p) => { const d = new Date(p.period); return d.getFullYear() === calYear && d.getMonth() + 1 === calMonth; })
                .sort((a, b) => new Date(a.period).getTime() - new Date(b.period).getTime())
                .map((p) => ({ date: p.period.split('-')[2], pnl: p.pnl }))}
            >
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Line type="monotone" dataKey="pnl" stroke="#f59e0b" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3">
            <button type="button" onClick={prevMonth} className="text-slate-400 hover:text-white text-sm px-2">◀</button>
            <span className="text-slate-400 text-sm">{calYear}-{String(calMonth).padStart(2, '0')}</span>
            <button type="button" onClick={nextMonth} className="text-slate-400 hover:text-white text-sm px-2">▶</button>
          </div>
        </div>
      )}

      {/* ─── Monthly View ─── */}
      {periodMode === 'monthly' && viewMode === 'calendar' && (
        <div className="mb-8">
          <div className="flex items-center justify-center gap-4 mb-4">
            <button type="button" onClick={prevYear} className="text-slate-400 hover:text-white text-lg px-2">◀</button>
            <span className="text-slate-200 font-semibold text-lg">{calYear}년</span>
            <button type="button" onClick={nextYear} className="text-slate-400 hover:text-white text-lg px-2">▶</button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {MONTH_LABELS.map((label, i) => {
              const m = i + 1;
              const pnl = monthMap.get(m);
              const hasPnl = pnl !== undefined;
              return (
                <div key={m} className={`rounded-lg py-3 px-1 sm:px-2 text-center flex flex-col items-center justify-center min-h-[64px] sm:min-h-[72px] overflow-hidden ${getCellBg(pnl)}`}>
                  <span className={`text-xs sm:text-sm font-semibold ${getCellTextColor(pnl)}`}>{label}</span>
                  {hasPnl && <span className={`text-[11px] sm:text-xs font-medium mt-1 tabular-nums leading-tight ${getPnlColor(pnl)}`}>{fmtPnlCompact(pnl, market)}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {periodMode === 'monthly' && viewMode === 'chart' && (
        <div className="mb-8 bg-panel rounded-xl p-4 border border-slate-700/50">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={MONTH_LABELS.map((label, i) => ({
                month: label,
                pnl: monthMap.get(i + 1) ?? 0,
              })).filter((d) => d.pnl !== 0)}
            >
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Line type="monotone" dataKey="pnl" stroke="#f59e0b" strokeWidth={2} dot={{ r: 4, fill: '#f59e0b' }} />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3">
            <button type="button" onClick={prevYear} className="text-slate-400 hover:text-white text-sm px-2">◀</button>
            <span className="text-slate-400 text-sm">{calYear}년</span>
            <button type="button" onClick={nextYear} className="text-slate-400 hover:text-white text-sm px-2">▶</button>
          </div>
        </div>
      )}

      {/* ─── Yearly View ─── */}
      {periodMode === 'yearly' && viewMode === 'calendar' && (
        <div className="mb-8">
          <div className="grid grid-cols-3 gap-3">
            {(availableYears.length > 0 ? availableYears : [now.getFullYear()]).map((yr) => {
              const pnl = yearMap.get(yr);
              const hasPnl = pnl !== undefined;
              return (
                <div key={yr} className={`rounded-lg py-4 sm:py-5 px-2 sm:px-3 text-center flex flex-col items-center justify-center min-h-[72px] sm:min-h-[80px] overflow-hidden ${getCellBg(pnl)}`}>
                  <span className={`text-base sm:text-lg font-semibold ${getCellTextColor(pnl)}`}>{yr}</span>
                  {hasPnl && <span className={`text-xs sm:text-sm font-medium mt-1 tabular-nums leading-tight ${getPnlColor(pnl)}`}>{fmtPnlCompact(pnl, market)}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {periodMode === 'yearly' && viewMode === 'chart' && (
        <div className="mb-8 bg-panel rounded-xl p-4 border border-slate-700/50">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={availableYears.map((yr) => ({
                year: String(yr),
                pnl: yearMap.get(yr) ?? 0,
              }))}
            >
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
              <Line type="monotone" dataKey="pnl" stroke="#f59e0b" strokeWidth={2} dot={{ r: 4, fill: '#f59e0b' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ─── 누적 손익 ─── */}
      {cumulativeData.length > 0 && lastCum && (
        <div className="mb-8">
          <h2 className="text-lg sm:text-xl font-bold text-slate-100 mb-1">누적 손익</h2>
          <p className="text-xs sm:text-sm text-slate-500 mb-1">
            {points.length > 0
              ? [...points].sort((a, b) => new Date(b.period).getTime() - new Date(a.period).getTime())[0].period
              : ''}
          </p>
          <p className={`text-xl sm:text-2xl font-bold mb-4 tabular-nums break-all ${lastCum.cumPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {fmtPnl(lastCum.cumPnl, market)}
          </p>
          <div className="bg-panel rounded-xl p-3 sm:p-4 border border-slate-700/50">
            <ResponsiveContainer width="100%" height={256}>
              <LineChart data={cumulativeData}>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  formatter={(value: number | undefined) => {
                    const v = value ?? 0;
                    return [
                      fmtPnl(v, market),
                      '누적 손익',
                    ];
                  }}
                />
                <Line type="monotone" dataKey="cumPnl" stroke="#f59e0b" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
