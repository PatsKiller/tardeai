import CountryFlag from './CountryFlag'
import ProAnalystPill from './ProAnalystPill'
import AnalystReviews from './AnalystReviews'
import HoldingProtectionActions from './HoldingProtectionActions'
import HoldingReportLinks from './HoldingReportLinks'
import { EvidenceBlock } from './EvidenceBlock'
import { fmt$ } from '../lib/format'
import { buildHoldingsRowModel, plMetrics } from '../lib/holdingsRowModel'
import {
  BB, type HoldingsCvdMode, primaryActionBg, primaryActionColor,
  semanticSigned, stopStatusBg, stopStatusColor,
} from '../lib/holdingsTerminalTokens'
import { mergeLiveStop, stopReviewTooltip } from '../lib/stopReviewTooltip'
import { holdingReportEligible } from '../lib/reportLinks'
import { useTerminalUi } from '../lib/terminalUi'

const rsiZoneColor = (s?: string, cvd: HoldingsCvdMode = 'default') =>
  s === 'oversold' ? (cvd === 'cvd' ? BB.blue : BB.green) : s === 'overbought' ? BB.amber : BB.text3
const signalColor = (s?: string, cvd: HoldingsCvdMode = 'default') => {
  const t = (s || '').toUpperCase()
  if (['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE'].includes(t)) return cvd === 'cvd' ? BB.blue : BB.green
  if (['TRIM', 'SELL', 'REDUCE', 'EXIT'].includes(t)) return BB.red
  if (['MONITOR', 'WATCH', 'CAUTION'].includes(t)) return BB.amber
  return BB.text3
}

function LlmHealthChip({ health, action }: { health?: string; action?: string }) {
  if (!health) return null
  const c: Record<string, string> = { HEALTHY: BB.green, WATCH: BB.amber, CONCERN: BB.red, TRIM: '#fb923c', HOLD: '#60a5fa' }
  const col = c[String(health).toUpperCase()] || BB.text3
  return (
    <span title={action ? `LLM action: ${action}` : 'Holdings LLM health assessment'}
      style={{ fontSize: 8, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: `${col}1f`, color: col, border: `1px solid ${col}44`, cursor: 'help' }}>
      {health}
    </span>
  )
}

function LlmBadges({ cov }: { cov?: any[] }) {
  const LLM_LANE: Record<string, { label: string; c: string }> = {
    local: { label: 'GEMMA', c: '#2dd4bf' }, grok: { label: 'GROK', c: '#f59e0b' },
    chatgpt: { label: 'GPT', c: '#a3e635' }, claude: { label: 'CLAUDE', c: '#d97757' },
  }
  if (!cov?.length) return <span title="No LLM research in last 30d" style={{ fontSize: 8, color: BB.text3 }}>no LLM review</span>
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 3, flexWrap: 'wrap' }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return <span key={lane} title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review(s)`}
          style={{ fontSize: 7.5, fontWeight: 800, padding: '1px 5px', borderRadius: 3, background: `${m.c}1f`, color: m.c, border: `1px solid ${m.c}44`, cursor: 'help' }}>
          {m.label}</span>
      })}
    </span>
  )
}

export interface HoldingsCardProps {
  h: any
  acctColor: string
  isFocus: boolean
  cvdMode?: HoldingsCvdMode
  paMap: any
  aMap: any
  fv?: any
  scard?: any
  pr?: any
  stopCuration?: any
  monitored?: any
  confirmedStop?: any
  brokerStopsFetchedAt?: string | null
  reportEntry?: any
  coverage?: any[]
  onClick: () => void
  onAction: () => void
  onRefreshMonitored?: () => void
  onPreflightUpdate?: (symbol: string, account: string, patch: { holding?: Record<string, unknown>; protection?: Record<string, unknown> }) => void
}

export default function HoldingsCard({
  h, acctColor, isFocus, cvdMode = 'default', paMap, aMap, fv, scard, pr, stopCuration,
  monitored, confirmedStop, brokerStopsFetchedAt, reportEntry, coverage,
  onClick, onAction, onRefreshMonitored, onPreflightUpdate,
}: HoldingsCardProps) {
  const [terminalUi] = useTerminalUi()
  const { dollars: pl$, pct: pl } = plMetrics(h)
  const sc = signalColor(h.signal, cvdMode)
  const zc = rsiZoneColor(h.rsi_status, cvdMode)
  const dayPct = h.day_change_pct
  const row = buildHoldingsRowModel({ h, pr, confirmedStop, monitored })
  const stopColor = stopStatusColor(row.stopStatus)
  const actionColor = primaryActionColor(row.primaryAction.tone, cvdMode)
  const isAmber = row.primaryAction.tone === 'amber'
  const isRed = row.primaryAction.tone === 'red'
  const liveConf = mergeLiveStop(confirmedStop, undefined)
  const stopTip = pr ? stopReviewTooltip({
    advisoryAt: pr.at, advisoryModel: pr.model,
    priceAt: h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at,
    brokerFetchedAt: liveConf?.fetched_at ?? brokerStopsFetchedAt,
    brokerOrderId: liveConf?.order_id,
    confirmedAt: liveConf?.confirmed_at,
  }) : ''
  const sh = Number(h.shares) || 0
  const acct = String(h.account ?? '')
  const schwabSmall = acct.startsWith('schwab') && sh > 0 && sh < 40

  return (
    <div
      id={`hold-${h.symbol}-${h.account}`}
      onClick={onClick}
      title={`${h.symbol} · ${h.account}${row.needsAction ? ' · Action needed' : ''}`}
      style={{
        background: terminalUi ? BB.bgRow : 'var(--bg1)',
        border: isFocus
          ? `1px solid ${terminalUi ? BB.amber : '#60a5fa'}`
          : `1px solid ${terminalUi ? BB.border : 'var(--border)'}`,
        borderLeft: `4px solid ${row.needsAction ? (isRed ? BB.red : BB.amberAlt) : sc === BB.text3 ? acctColor : sc}`,
        boxShadow: isFocus ? `0 0 0 2px ${terminalUi ? BB.amber : '#60a5fa'}44` : row.needsAction ? '0 2px 12px rgba(255,176,0,.08)' : 'none',
        borderRadius: terminalUi ? 2 : 10,
        padding: terminalUi ? '6px 10px' : '14px 16px',
        cursor: 'pointer',
        transition: 'box-shadow .15s, border-color .15s',
      }}
      onMouseEnter={e => { if (!isFocus) e.currentTarget.style.boxShadow = '0 2px 14px rgba(255,176,0,.1)' }}
      onMouseLeave={e => { if (!isFocus) e.currentTarget.style.boxShadow = row.needsAction ? '0 2px 12px rgba(255,176,0,.08)' : 'none' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <CountryFlag symbol={h.symbol} country={h.country} countryName={h.country_name} size={20} />
        <span title={h.name} style={{ fontSize: 17, fontWeight: 800, color: BB.text0, fontFamily: BB.mono }}>{h.symbol}</span>
        <ProAnalystPill symbol={h.symbol} map={paMap} compact />
        <span style={{ flex: 1, minWidth: 8 }} />
        <span title={row.stopTooltip} style={{
          fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 4,
          background: stopStatusBg(row.stopStatus), color: stopColor, border: `1px solid ${stopColor}55`, cursor: 'help',
        }}>{row.stopLabel}</span>
        {h.signal
          ? <span title={`Signal: ${h.signal}`} style={{ fontSize: 10, fontWeight: 800, padding: '2px 9px', borderRadius: 4, background: `${sc}22`, color: sc }}>{h.signal}</span>
          : <span style={{ fontSize: 9, color: BB.text3 }}>—</span>}
      </div>
      <div style={{ fontSize: 9, color: BB.text3, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={h.name}>{h.name}</div>

      <div style={{ marginTop: 6, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span title={h.account} style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: `${acctColor}22`, color: acctColor, border: `1px solid ${acctColor}44` }}>
          ● {(h.account ?? 'unknown').replace(/_/g, ' ')}</span>
        {h.shares != null && <span title="Share count" style={{ fontSize: 9, color: BB.text3, fontFamily: BB.mono }}>{h.shares} sh</span>}
      </div>

      {fv && (
        <div title="Finviz daily metrics" style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8, padding: '5px 9px', borderRadius: 6, background: 'rgba(59,130,246,.08)', border: `1px solid ${BB.border}` }}>
          <span style={{ fontSize: 9, color: BB.text3 }}>RSI <b style={{ color: fv.rsi == null ? BB.text3 : fv.rsi >= 70 ? BB.red : fv.rsi <= 30 ? semanticSigned(1, cvdMode) : BB.text1, fontFamily: BB.mono }}>{fv.rsi ?? '—'}</b></span>
          {([['W', fv.perf_week], ['M', fv.perf_month], ['YTD', fv.perf_ytd]] as [string, any][]).map(([l, v]) => (
            <span key={l} style={{ fontSize: 9, color: BB.text3 }}>{l} <b style={{ color: v == null ? BB.text3 : semanticSigned(Number(v), cvdMode), fontFamily: BB.mono }}>{v == null ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`}</b></span>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
        <span title="Market value" style={{ fontSize: 20, fontWeight: 800, color: BB.text0, fontFamily: BB.mono }}>{fmt$(h.market_value, 0)}</span>
        {pl$ != null ? (
          <span title={pl != null ? `Unrealized ${pl >= 0 ? '+' : ''}${pl.toFixed(2)}% on cost ${fmt$(h.cost_basis, 0)}` : undefined}
            style={{ fontSize: 14, fontWeight: 800, color: semanticSigned(pl$, cvdMode), fontFamily: BB.mono }}>
            {pl$ >= 0 ? '+' : ''}{fmt$(pl$, 0)}
            {pl != null && <span style={{ fontSize: 12, opacity: 0.9 }}> ({pl >= 0 ? '+' : ''}{pl.toFixed(1)}%)</span>}
          </span>
        ) : (
          <span title="No cost basis (e.g. 401k fund)" style={{ fontSize: 13, fontWeight: 800, color: BB.text3 }}>— P/L</span>
        )}
        {dayPct != null && (
          <span title="Today's change" style={{ fontSize: 10, fontWeight: 700, color: semanticSigned(Number(dayPct), cvdMode), fontFamily: BB.mono }}>
            today {Number(dayPct) >= 0 ? '+' : ''}{Number(dayPct).toFixed(1)}%
          </span>
        )}
      </div>

      {(() => {
        const cur = h.current_price != null ? Number(h.current_price)
          : sh > 0 && h.market_value != null ? Number(h.market_value) / sh : null
        const buy = sh > 0 && h.cost_basis != null && Number(h.cost_basis) > 0 ? Number(h.cost_basis) / sh : null
        if (cur == null) return null
        return (
          <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 12, fontWeight: 700, flexWrap: 'wrap' }}>
            <span title="Last price" style={{ color: BB.text2 }}>Price <b style={{ fontFamily: BB.mono, fontSize: 13, color: BB.text0 }}>${cur.toFixed(2)}</b></span>
            <span title={buy != null ? 'Avg purchase price (cost basis ÷ shares)' : 'No per-lot cost basis'} style={{ color: BB.text3 }}>
              Cost <b style={{ fontFamily: BB.mono, color: BB.text1 }}>{buy != null ? `$${buy.toFixed(2)}` : '—'}</b></span>
          </div>
        )
      })()}

      <div style={{ marginTop: 8, height: 6, background: BB.bg, borderRadius: 3, border: `1px solid ${BB.borderSubtle}` }}>
        <div title={`${h.portfolio_pct?.toFixed(1) ?? 0}% of portfolio`} style={{ width: `${Math.min(100, (h.portfolio_pct ?? 0) * 4)}%`, height: '100%', background: acctColor, borderRadius: 3, minWidth: 2 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: BB.text3, marginTop: 3 }}>
        <span>{h.portfolio_pct != null ? `${h.portfolio_pct.toFixed(1)}% of portfolio` : ''}</span>
      </div>

      <div title={row.stopTooltip} style={{ marginTop: 10, padding: '8px 10px', borderRadius: 6, background: stopStatusBg(row.stopStatus), border: `1px solid ${stopColor}44` }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: row.needsAction ? BB.amberAlt : BB.text0, fontFamily: BB.mono }}>{row.stopInstruction}</div>
        {row.stopContext && <div style={{ fontSize: 9, color: BB.text3, marginTop: 3 }}>{row.stopContext}</div>}
      </div>

      <div style={{ marginTop: 10 }} onClick={e => e.stopPropagation()}>
        <button type="button" title={row.primaryActionTooltip} onClick={onAction} style={{
          width: '100%', padding: isAmber || isRed ? '9px 12px' : '7px 10px', fontSize: 11, fontWeight: 800, borderRadius: 6, cursor: 'pointer',
          border: isAmber ? `2px solid ${BB.amberAlt}` : isRed ? `2px solid ${BB.red}` : `1px solid ${actionColor}55`,
          background: isAmber ? 'rgba(255,160,40,.28)' : isRed ? BB.redDim : primaryActionBg(row.primaryAction.tone, cvdMode),
          color: isAmber ? BB.amberAlt : actionColor,
          boxShadow: isAmber ? '0 0 12px rgba(255,176,0,.2)' : undefined,
        }}>{row.needsAction ? '▸ ' : ''}{row.primaryAction.label}</button>
      </div>

      <div style={{ display: 'flex', gap: 5, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {h.rsi != null && (
          <span title={h.proxy ? `proxy: ${h.proxy.ticker}` : h.rsi_status}
            style={{ fontSize: 8.5, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: `${zc}1a`, color: zc, cursor: 'help' }}>
            RSI {Math.round(h.rsi)}{h.proxy ? '*' : ''}</span>
        )}
        {pr && (
          <span title={`${stopTip}\n\n${row.stopTooltip}`}
            style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: BB.amberDim, border: `1px solid ${BB.amber}33`, color: BB.amber, cursor: 'help' }}>
            {row.stopLabel}</span>
        )}
        <LlmHealthChip health={h.llm_health} action={h.llm_action} />
        <span style={{ flex: 1 }} />
        <LlmBadges cov={coverage} />
      </div>

      {(h.llm_evidence?.length > 0 || (h.llm_data_i_doubt && h.llm_data_i_doubt !== 'none')) && (
        <EvidenceBlock title={h.llm_health ? `Holdings health · ${h.llm_health}` : 'Holdings LLM evidence'} evidence={h.llm_evidence} dataIDoubt={h.llm_data_i_doubt} compact maxItems={3} />
      )}
      {(pr?.evidence?.length > 0 || stopCuration?.evidence?.length > 0) && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {pr?.evidence?.length > 0 && <EvidenceBlock title={`Stop advisory${pr.model ? ` · ${pr.model}` : ''}`} evidence={pr.evidence} dataIDoubt={pr.data_i_doubt} compact maxItems={3} />}
          {stopCuration?.evidence?.length > 0 && <EvidenceBlock title={`Grok stop curation${stopCuration.grade ? ` · ${stopCuration.grade}` : ''}`} evidence={stopCuration.evidence} dataIDoubt={stopCuration.data_i_doubt} compact maxItems={2} />}
        </div>
      )}
      {holdingReportEligible(h) && (
        <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
          <HoldingReportLinks symbol={h.symbol} entry={reportEntry} reportType={reportEntry?.report_type} />
        </div>
      )}
      {(pr?.stop_price || schwabSmall) && (
        <HoldingProtectionActions h={h} pr={pr} monitored={monitored} confirmedStop={confirmedStop}
          brokerStopsFetchedAt={brokerStopsFetchedAt} onRefresh={onRefreshMonitored} onPreflightUpdate={onPreflightUpdate} />
      )}
      {scard && (
        <div style={{ borderTop: `1px solid ${BB.border}`, marginTop: 10, paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {scard.description && <div style={{ fontSize: 11, color: BB.text2, lineHeight: 1.5 }}>{scard.description}</div>}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 8.5 }}>
            {scard.sector && <span style={{ color: '#60a5fa' }}>{scard.sector}{scard.sector_etf ? ` (${scard.sector_etf})` : ''}</span>}
            {scard.vs_sector_week != null && (
              <span title={`symbol ${scard.perf_week}% vs ${scard.sector_etf} ${scard.sector_perf_week}% (week)`}
                style={{ color: semanticSigned(scard.vs_sector_week, cvdMode), fontWeight: 700 }}>
                {scard.vs_sector_week >= 0 ? '+' : ''}{scard.vs_sector_week}% vs sector</span>
            )}
            {scard.analyst?.rating && (
              <span title={`Yahoo consensus · target $${scard.analyst.target_low}–$${scard.analyst.target_high}`}
                style={{ color: String(scard.analyst.rating).includes('buy') ? semanticSigned(1, cvdMode) : BB.text2 }}>
                {String(scard.analyst.rating).replace('_', ' ')} · {scard.analyst.opinions} analysts · target ${scard.analyst.target}</span>
            )}
            {scard.earnings && (scard.earnings.next_date || scard.earnings.surprise_pct != null) && (
              <span title={scard.earnings.next_date ? `Next earnings ${scard.earnings.next_date}` : 'Last earnings'}>
                {scard.earnings.next_date && <span style={{ color: BB.text2 }}>{new Date(scard.earnings.next_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>}
                {scard.earnings.surprise_pct != null && (
                  <span style={{ color: scard.earnings.beat ? semanticSigned(1, cvdMode) : BB.red, fontWeight: 700, marginLeft: 4 }}>
                    {scard.earnings.beat ? 'BEAT' : 'MISS'} {scard.earnings.surprise_pct >= 0 ? '+' : ''}{scard.earnings.surprise_pct}%</span>
                )}
              </span>
            )}
            {scard.distribution && (scard.distribution.next_est || scard.distribution.last_date) && (
              <span title={scard.distribution.cadence ? `${scard.distribution.cadence} distribution` : 'distribution'} style={{ color: BB.text2 }}>
                {scard.distribution.next_est
                  ? `next ~${new Date(scard.distribution.next_est + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                  : scard.distribution.cadence || 'distribution'}
              </span>
            )}
          </div>
          <AnalystReviews symbol={h.symbol} map={aMap} />
          {(scard.news ?? []).slice(0, 3).map((n: any, i: number) => (
            <div key={i} style={{ fontSize: 9, lineHeight: 1.35, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span style={{ color: BB.text3 }}>{n.source} · </span>
              {n.url ? <a href={n.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#93c5fd', textDecoration: 'none' }} title={n.title}>{n.title}</a>
                : <span style={{ color: BB.text2 }} title={n.title}>{n.title}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}