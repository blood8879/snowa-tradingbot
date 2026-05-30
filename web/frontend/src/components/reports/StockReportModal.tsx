import { Badge } from '@/components/ui/Badge';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useStockReport } from '@/hooks/useStockReport';
import type { StockReportJson } from '@/types/api';

interface StockReportModalProps {
  ticker: string;
  name?: string | null;
  market: string;
  onClose: () => void;
}

function verdictVariant(verdict: string) {
  if (verdict === 'PASS') return 'success';
  if (verdict === 'FAIL') return 'danger';
  return 'default';
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatScore(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(0) : '—';
}

function ScoreCard({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-100 tabular-nums">
        {formatScore(value)}
      </p>
    </div>
  );
}

function BulletList({ title, items, color }: { title: string; items: string[]; color: string }) {
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{title}</h4>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">없음</p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm text-slate-300">
          {items.map((item) => (
            <li key={item} className="leading-relaxed">- {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReportBody({ report }: { report: StockReportJson }) {
  const canslimKeys = ['C', 'A', 'N', 'S', 'L', 'I', 'M'];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={verdictVariant(report.verdict)}>{report.verdict}</Badge>
        <span className="text-sm text-slate-400">신뢰도 {formatScore(report.confidence)}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <ScoreCard label="종합 적합도" value={report.overall_fit_score} />
        <ScoreCard label="CANSLIM" value={report.canslim_fit_score} />
        <ScoreCard label="미너비니" value={report.minervini_fit_score} />
        <ScoreCard label="신뢰도" value={report.confidence} />
      </div>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">요약</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">{report.summary}</p>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section>
          <h3 className="text-sm font-semibold text-slate-200">오닐/CANSLIM 해석</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">{report.oneil_thesis}</p>
        </section>
        <section>
          <h3 className="text-sm font-semibold text-slate-200">미너비니 해석</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">{report.minervini_thesis}</p>
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <BulletList title="강점" items={report.strengths ?? []} color="text-emerald-400" />
        <BulletList title="약점" items={report.weaknesses ?? []} color="text-amber-400" />
        <BulletList title="Red flags" items={report.red_flags ?? []} color="text-red-400" />
      </div>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">CANSLIM 항목별 코멘트</h3>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {canslimKeys.map((key) => {
            const item = report.canslim_breakdown?.[key];
            return (
              <div key={key} className="rounded-lg border border-slate-700/60 bg-slate-900/30 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-100">{key}</span>
                  <span className="text-xs text-slate-400 tabular-nums">{formatScore(item?.score)}</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-300">{item?.comment ?? '데이터 없음'}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-slate-200">관심종목 편입 코멘트</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">{report.watchlist_reason}</p>
        <h3 className="mt-4 text-sm font-semibold text-slate-200">리스크 코멘트</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">{report.risk_note}</p>
      </section>
    </div>
  );
}

export function StockReportModal({ ticker, name, market, onClose }: StockReportModalProps) {
  const { data, isLoading, error } = useStockReport(ticker, market);

  const report = data?.report?.report_json ?? null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="max-h-[88vh] w-full max-w-5xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur">
          <div>
            <p className="text-xs font-medium uppercase text-emerald-400">최신 분기 AI 재무 리포트</p>
            <h2 className="text-lg font-semibold text-slate-100">
              {ticker} {name && <span className="text-sm font-normal text-slate-400">{name}</span>}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              최신 재무 기준: {data?.report_period ?? '—'} · 모델: {data?.report?.model ?? '—'} · 생성: {formatDate(data?.report?.updated_at)}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-800 hover:text-slate-100">
            닫기
          </button>
        </div>

        <div className="p-5">
          {isLoading && <LoadingSpinner />}
          {error && <p className="text-sm text-red-400">리포트를 불러오는 중 오류가 발생했습니다.</p>}
          {!isLoading && !error && !data?.eligible && (
            <p className="text-sm text-slate-400">ACTIVE 관심종목 또는 OPEN 포지션 종목만 리포트를 생성할 수 있습니다.</p>
          )}
          {!isLoading && !error && data?.eligible && !data.has_financial_data && (
            <p className="text-sm text-amber-300">저장된 재무 데이터가 없어 리포트를 생성할 수 없습니다.</p>
          )}
          {!isLoading && !error && data?.eligible && data.has_financial_data && !report && (
            <div className="rounded-xl border border-slate-700 bg-slate-900/40 p-5 text-center">
              <p className="text-sm text-slate-300">아직 최신 재무 기준 AI 리포트가 없습니다.</p>
              <p className="mt-2 text-xs text-slate-500">리포트는 스크리닝 파이프라인에서 자동 생성되며, 같은 재무 데이터 hash는 재사용됩니다.</p>
            </div>
          )}
          {report && <ReportBody report={report} />}
        </div>
      </div>
    </div>
  );
}
