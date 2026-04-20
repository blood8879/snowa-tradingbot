import { useState } from 'react';
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

function IBDHelpModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-slate-800 border border-slate-600 rounded-2xl max-w-3xl w-full max-h-[85vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between rounded-t-2xl z-10">
          <h2 className="text-lg font-bold text-slate-100">IBD 시장 방향 가이드</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-xl font-bold px-2">
            &times;
          </button>
        </div>

        <div className="px-6 py-5 space-y-6 text-sm text-slate-300 leading-relaxed">

          {/* 개요 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-2">IBD 시장 방향이란?</h3>
            <p>
              IBD(Investor's Business Daily) 시장 방향은 <strong className="text-slate-100">분배일(Distribution Day) 누적</strong>을
              기반으로 시장의 건강 상태를 판단하는 시스템입니다.
              William O'Neil이 개발한 이 방법론은 기관 투자자의 매도 압력을 감지하여 시장 전환점을 조기에 포착합니다.
            </p>
            <div className="mt-3 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-xs text-blue-300">
              <strong>참고:</strong> 본 시스템에서 IBD 시장 방향은 <strong>로깅 전용</strong>이며 자동 매매에 직접 영향을 주지 않습니다.
              실제 매매 필터는 SPY/KODEX200 &gt; 200일 이동평균으로 판단합니다.
            </div>
          </section>

          {/* 4가지 상태 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-3">시장 상태 4단계</h3>
            <div className="space-y-2">
              <div className="flex items-start gap-3 p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <span className="text-green-400 font-bold text-lg mt-0.5">▲</span>
                <div>
                  <p className="font-semibold text-green-400">확인된 상승추세 (Confirmed Uptrend)</p>
                  <p className="text-xs text-slate-400 mt-1">
                    FTD(Follow-Through Day)가 확인된 건강한 상승장. 분배일이 3일 미만.
                    <strong className="text-slate-300"> 신규 매수에 가장 유리한 환경.</strong>
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                <span className="text-yellow-400 font-bold text-lg mt-0.5">◆</span>
                <div>
                  <p className="font-semibold text-yellow-400">상승추세 압박 (Uptrend Under Pressure)</p>
                  <p className="text-xs text-slate-400 mt-1">
                    분배일이 3~4일 누적. 기관의 매도 압력이 감지됨.
                    <strong className="text-slate-300"> 신규 매수 시 신중해야 하며, 기존 포지션 관리에 집중.</strong>
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-orange-500/10 border border-orange-500/20 rounded-lg">
                <span className="text-orange-400 font-bold text-lg mt-0.5">◆</span>
                <div>
                  <p className="font-semibold text-orange-400">반등 시도 (Rally Attempt)</p>
                  <p className="text-xs text-slate-400 mt-1">
                    조정장에서 지수가 상승 마감한 첫날부터 시작. 4~10거래일 내 FTD가 나와야 상승추세로 전환.
                    <strong className="text-slate-300"> 아직 확인되지 않은 반등이므로 관망 권장.</strong>
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <span className="text-red-400 font-bold text-lg mt-0.5">▼</span>
                <div>
                  <p className="font-semibold text-red-400">조정장 (Market in Correction)</p>
                  <p className="text-xs text-slate-400 mt-1">
                    분배일 5일 이상 누적, 또는 랠리 실패. 기관이 적극적으로 매도 중.
                    <strong className="text-slate-300"> 신규 매수를 삼가고 현금 비중을 높이는 것이 유리.</strong>
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* 상태 전환 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-2">상태 전환 흐름</h3>
            <div className="p-4 bg-slate-700/30 rounded-lg font-mono text-xs text-center space-y-1">
              <p><span className="text-red-400">조정장</span> &rarr; <span className="text-slate-400">(지수 상승 마감)</span> &rarr; <span className="text-orange-400">반등 시도</span></p>
              <p><span className="text-orange-400">반등 시도</span> &rarr; <span className="text-slate-400">(Day 4~10에 FTD 발생)</span> &rarr; <span className="text-green-400">확인된 상승추세</span></p>
              <p><span className="text-orange-400">반등 시도</span> &rarr; <span className="text-slate-400">(Day1 저가 이탈 또는 Day 10 초과)</span> &rarr; <span className="text-red-400">조정장</span></p>
              <p><span className="text-green-400">확인된 상승추세</span> &rarr; <span className="text-slate-400">(분배일 3일+)</span> &rarr; <span className="text-yellow-400">상승추세 압박</span></p>
              <p><span className="text-green-400 inline">확인된 상승추세</span> / <span className="text-yellow-400">압박</span> &rarr; <span className="text-slate-400">(분배일 5일+)</span> &rarr; <span className="text-red-400">조정장</span></p>
            </div>
          </section>

          {/* 핵심 개념 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-3">핵심 개념</h3>

            <div className="space-y-4">
              <div className="p-3 bg-slate-700/30 rounded-lg">
                <p className="font-semibold text-red-400 mb-1">분배일 (Distribution Day)</p>
                <p className="text-xs text-slate-400">
                  지수 종가가 전일 대비 <strong className="text-slate-300">-0.2% 이상 하락</strong>하면서,
                  동시에 <strong className="text-slate-300">거래량이 전일보다 증가</strong>한 날.
                  기관 투자자가 대량으로 주식을 매도하고 있다는 신호입니다.
                </p>
                <div className="mt-2 text-xs text-slate-500">
                  <p>계산: 종가 변동률 &le; -0.2% AND 당일 거래량 &ge; 전일 거래량</p>
                  <p>만료: 25거래일 경과 또는 분배일 종가 대비 5% 이상 상승 시 자동 소멸</p>
                </div>
              </div>

              <div className="p-3 bg-slate-700/30 rounded-lg">
                <p className="font-semibold text-yellow-400 mb-1">스톨링 (Stalling Day)</p>
                <p className="text-xs text-slate-400">
                  지수가 <strong className="text-slate-300">소폭 상승(0~0.4%)</strong>하면서 <strong className="text-slate-300">종가가 일중 하단</strong>에 위치하고,
                  <strong className="text-slate-300">거래량이 높은</strong> 날. 상승 동력이 약화되고 있다는 신호.
                  분배일과 유사하게 분배일 수에 가산됩니다(최대 2일).
                </p>
              </div>

              <div className="p-3 bg-slate-700/30 rounded-lg">
                <p className="font-semibold text-green-400 mb-1">FTD (Follow-Through Day)</p>
                <p className="text-xs text-slate-400">
                  반등 시도 시작 후 <strong className="text-slate-300">4~10거래일 사이</strong>에 나타나야 하는 확인 신호.
                  지수가 <strong className="text-slate-300">+1.25% 이상 상승</strong>하면서 <strong className="text-slate-300">거래량이 전일보다 증가</strong>해야 합니다.
                  대규모 기관 매수가 유입되고 있다는 의미로, 조정장에서 상승추세로 전환되는 핵심 신호입니다.
                </p>
              </div>
            </div>
          </section>

          {/* UI 설명 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-3">화면 구성 안내</h3>
            <div className="space-y-3 text-xs">
              <div className="flex gap-2">
                <span className="text-slate-500 font-semibold min-w-[100px]">종합 시장 방향</span>
                <span className="text-slate-400">추적 중인 모든 지수 중 가장 나쁜 상태를 표시. SPY와 QQQ(미국) 또는 KODEX200과 KOSDAQ150(한국) 중 더 약한 쪽 기준.</span>
              </div>
              <div className="flex gap-2">
                <span className="text-slate-500 font-semibold min-w-[100px]">분배일 수</span>
                <span className="text-slate-400">현재 활성 분배일+스톨링일의 합계. <span className="text-green-400">0~2일: 안전</span>, <span className="text-yellow-400">3~4일: 주의</span>, <span className="text-red-400">5일+: 위험(조정장 전환)</span>.</span>
              </div>
              <div className="flex gap-2">
                <span className="text-slate-500 font-semibold min-w-[100px]">랠리 일수</span>
                <span className="text-slate-400">반등 시도가 시작된 이후 거래일 수. Day 4~10 사이에 FTD가 나와야 합니다. Day 10 초과 시 랠리 실패.</span>
              </div>
              <div className="flex gap-2">
                <span className="text-slate-500 font-semibold min-w-[100px]">FTD 확인일</span>
                <span className="text-slate-400">Follow-Through Day가 발생한 날짜. 이 날의 저가(FTD 저가) 아래로 하락하면 FTD가 무효화됩니다.</span>
              </div>
              <div className="flex gap-2">
                <span className="text-slate-500 font-semibold min-w-[100px]">활성 분배일</span>
                <span className="text-slate-400">아직 만료되지 않은 분배일/스톨링일 목록. 25거래일 경과 또는 5% 상승 시 자동 만료.</span>
              </div>
            </div>
          </section>

          {/* 투자 활용 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-3">투자 활용법</h3>
            <div className="space-y-2 text-xs text-slate-400">
              <div className="p-3 bg-green-500/5 border border-green-500/10 rounded-lg">
                <p className="font-semibold text-green-400 mb-1">확인된 상승추세일 때</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>CANSLIM 기준 통과 종목 중 돌파 신호에 적극 대응</li>
                  <li>포지션 사이즈를 정상(100%) 수준으로 유지</li>
                  <li>피라미딩(추가 매수)에 유리한 환경</li>
                </ul>
              </div>
              <div className="p-3 bg-yellow-500/5 border border-yellow-500/10 rounded-lg">
                <p className="font-semibold text-yellow-400 mb-1">상승추세 압박일 때</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>신규 매수 비중 축소 (50% 이하)</li>
                  <li>기존 포지션의 수익 실현 고려</li>
                  <li>손절선을 더 타이트하게 관리</li>
                </ul>
              </div>
              <div className="p-3 bg-orange-500/5 border border-orange-500/10 rounded-lg">
                <p className="font-semibold text-orange-400 mb-1">반등 시도일 때</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>FTD 확인 전까지 신규 매수 자제</li>
                  <li>워치리스트 업데이트에 집중 (돌파 대비)</li>
                  <li>FTD 발생 시 소규모 시범 매수 가능</li>
                </ul>
              </div>
              <div className="p-3 bg-red-500/5 border border-red-500/10 rounded-lg">
                <p className="font-semibold text-red-400 mb-1">조정장일 때</p>
                <ul className="list-disc list-inside space-y-1">
                  <li>신규 매수 중단, 현금 비중 극대화</li>
                  <li>기존 포지션은 손절선에 의해 기계적으로 관리</li>
                  <li>다음 랠리를 위한 종목 발굴에 집중</li>
                </ul>
              </div>
            </div>
          </section>

          {/* 분배일 임계값 */}
          <section>
            <h3 className="text-base font-semibold text-slate-100 mb-2">시스템 설정값</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1.5">항목</th>
                  <th className="text-right py-1.5">값</th>
                </tr>
              </thead>
              <tbody className="text-slate-400">
                <tr className="border-b border-slate-700/50"><td className="py-1.5">분배일 기준 하락률</td><td className="text-right">&le; -0.2%</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">분배일 만료 기간</td><td className="text-right">25 거래일</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">분배일 랠리 만료</td><td className="text-right">종가 대비 +5% 상승</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">압박 전환 임계값</td><td className="text-right">분배일 3일+</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">조정장 전환 임계값</td><td className="text-right">분배일 5일+</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">FTD 최소 상승률</td><td className="text-right">&ge; +1.25%</td></tr>
                <tr className="border-b border-slate-700/50"><td className="py-1.5">FTD 가능 기간</td><td className="text-right">Day 4 ~ Day 10</td></tr>
                <tr><td className="py-1.5">FTD 취약 기간</td><td className="text-right">FTD 후 2일 이내</td></tr>
              </tbody>
            </table>
          </section>

        </div>
      </div>
    </div>
  );
}

export function IBDMarketDirectionPage() {
  const { market } = useMarket();
  const { data: status, isLoading: statusLoading } = useIBDStatus(market);
  const { data: distDays, isLoading: distLoading } = useIBDDistributionDays(market, true);
  const currencyPrefix = market === 'KR' ? '₩' : '$';
  const [showHelp, setShowHelp] = useState(false);

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
      <div className="flex items-center justify-between">
        <PageHeader title="IBD 시장 방향" subtitle="분배일 기반 시장 추세 판단 (로깅 전용)" />
        <button
          onClick={() => setShowHelp(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-400 bg-slate-700/50 hover:bg-slate-700 border border-slate-600 rounded-lg transition-colors"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          도움말
        </button>
      </div>

      {showHelp && <IBDHelpModal onClose={() => setShowHelp(false)} />}

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
